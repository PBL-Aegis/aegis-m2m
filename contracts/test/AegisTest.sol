// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {AegisToken} from "../src/AegisToken.sol";

/// @notice 결제를 시험하는 테스트가 함께 쓰는 바탕. 구매자 서명과 중개자 전송을 대신 해 준다.
/// 규칙 테스트는 이 컨트랙트를 상속하고 _pay(...) 로 결제한다.
abstract contract AegisTest is Test {
    address relayer = makeAddr("relayer");

    // 서명 계산에 토큰을 부르지 않으려고 토큰과 같은 값을 여기서 직접 만든다.
    // 그래야 vm.expectRevert 바로 뒤에 _pay 를 불러도 expectRevert 가 실제 결제 호출에 걸린다.
    bytes32 private constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");

    /// @notice 구매자(signerKey)가 서명한 ERC-3009 결제를 중개자가 보낸다. 유효기간은 지금부터 10분.
    function _pay(AegisToken token, uint256 signerKey, address to, uint256 value, bytes32 requestId) internal {
        address from = vm.addr(signerKey);
        uint256 validBefore = block.timestamp + 600;
        (uint8 v, bytes32 r, bytes32 s) = _sign(token, signerKey, from, to, value, 0, validBefore, requestId);
        vm.prank(relayer);
        token.transferWithAuthorization(from, to, value, 0, validBefore, requestId, v, r, s);
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
