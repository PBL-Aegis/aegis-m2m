// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {AegisToken} from "../src/AegisToken.sol";

/// @notice 결제를 시험하는 테스트가 함께 쓰는 바탕. 구매 한 건은 두 단계다.
///   1. 운영자가 합의와 송금 직전 감사 결과를 연다(openDeal).
///   2. 구매자가 합의 해시를 nonce 로 ERC-3009 서명을 하고, x402 정산 서버(facilitator)가 체인에 올린다.
/// 규칙 테스트는 이 컨트랙트를 상속하고 _pay(...) 로 결제한다. 결제가 막히는지 볼 때는 _payReverting(...) 을 쓴다.
abstract contract AegisTest is Test {
    address facilitator = makeAddr("facilitator");

    // 서명·해시 계산에 토큰을 부르지 않으려고 토큰과 같은 값을 여기서 직접 만든다.
    // 그래야 vm.expectRevert 바로 뒤의 첫 호출이 실제 결제 호출이 된다.
    bytes32 private constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant DEAL_TYPEHASH = keccak256(
        "Deal(bytes32 requestId,address buyer,address seller,bytes32 modelKey,uint256 askUnits,uint256 agreedUnits,bytes32 transcriptHash,bytes32 decisionHash)"
    );

    struct Signature {
        uint256 validBefore;
        uint8 v;
        bytes32 r;
        bytes32 s;
    }

    function _deal(address buyer, address seller, uint256 agreedUnits, bytes32 requestId)
        internal
        pure
        returns (AegisToken.Deal memory)
    {
        return AegisToken.Deal({
            requestId: requestId,
            buyer: buyer,
            seller: seller,
            modelKey: keccak256("openai/gpt-6.1-sol"),
            askUnits: agreedUnits + 1,
            agreedUnits: agreedUnits,
            transcriptHash: keccak256("transcript"),
            decisionHash: keccak256("decision")
        });
    }

    function _hashDeal(AegisToken.Deal memory deal) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                DEAL_TYPEHASH,
                deal.requestId,
                deal.buyer,
                deal.seller,
                deal.modelKey,
                deal.askUnits,
                deal.agreedUnits,
                deal.transcriptHash,
                deal.decisionHash
            )
        );
    }

    /// @notice 운영자가 합의와 송금 직전 감사 결과(통과)를 연다.
    function _open(AegisToken token, AegisToken.Deal memory deal) internal {
        _openWith(token, deal, 1);
    }

    function _openWith(AegisToken token, AegisToken.Deal memory deal, uint8 result) internal {
        vm.prank(token.owner());
        token.openDeal(deal, result, "", keccak256("report"));
    }

    /// @notice 구매자(signerKey)가 합의 해시를 nonce 로 서명한다. 토큰을 부르지 않는다.
    function _signDeal(AegisToken token, uint256 signerKey, AegisToken.Deal memory deal)
        internal
        view
        returns (Signature memory sig)
    {
        sig.validBefore = block.timestamp + 600;
        (sig.v, sig.r, sig.s) =
            _sign(token, signerKey, deal.buyer, deal.seller, deal.agreedUnits, 0, sig.validBefore, _hashDeal(deal));
    }

    /// @notice x402 정산 서버가 서명을 체인에 올린다.
    function _submit(AegisToken token, AegisToken.Deal memory deal, Signature memory sig) internal {
        vm.prank(facilitator);
        token.transferWithAuthorization(
            deal.buyer, deal.seller, deal.agreedUnits, 0, sig.validBefore, _hashDeal(deal), sig.v, sig.r, sig.s
        );
    }

    /// @notice 합의를 열고 결제한다.
    function _pay(AegisToken token, uint256 signerKey, address to, uint256 value, bytes32 requestId) internal {
        AegisToken.Deal memory deal = _deal(vm.addr(signerKey), to, value, requestId);
        _open(token, deal);
        _submit(token, deal, _signDeal(token, signerKey, deal));
    }

    /// @notice 합의를 열고, 결제가 err 로 막히는지 본다.
    function _payReverting(
        AegisToken token,
        uint256 signerKey,
        address to,
        uint256 value,
        bytes32 requestId,
        bytes memory err
    ) internal {
        AegisToken.Deal memory deal = _deal(vm.addr(signerKey), to, value, requestId);
        _open(token, deal);
        Signature memory sig = _signDeal(token, signerKey, deal);
        vm.expectRevert(err);
        _submit(token, deal, sig);
    }

    /// @notice ERC-3009 결제 내용에 대한 EIP-712 서명.
    function _sign(
        AegisToken token,
        uint256 signerKey,
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce
    ) internal view returns (uint8, bytes32, bytes32) {
        bytes32 domainSeparator = keccak256(
            abi.encode(DOMAIN_TYPEHASH, keccak256("AEGIS"), keccak256("1"), block.chainid, address(token))
        );
        bytes32 structHash =
            keccak256(abi.encode(TRANSFER_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce));
        return vm.sign(signerKey, keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash)));
    }
}
