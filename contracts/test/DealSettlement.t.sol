// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AegisToken} from "../src/AegisToken.sol";
import {AegisTest} from "./AegisTest.sol";
import {RuledToken, MaxHundredRule} from "./AegisToken.t.sol";

/// 흥정한 구매의 결제(settleDeal). 합의가 체인에 저장되고, 합의와 다른 내용으로는 송금되지 않는지 본다.
contract DealSettlementTest is AegisTest {
    struct Signature {
        uint256 validBefore;
        uint8 v;
        bytes32 r;
        bytes32 s;
    }

    AegisToken token;
    address owner = makeAddr("owner");
    address buyer;
    uint256 buyerKey;
    address seller = makeAddr("seller");

    function setUp() public {
        (buyer, buyerKey) = makeAddrAndKey("buyer");
        token = new AegisToken(owner);
        vm.prank(owner);
        token.mint(buyer, 1_000_000);
    }

    function _deal(bytes32 requestId, uint256 agreedUnits) internal view returns (AegisToken.Deal memory) {
        return AegisToken.Deal({
            requestId: requestId,
            buyer: buyer,
            seller: seller,
            modelKey: keccak256("openai/gpt-6.1-sol"),
            askUnits: 80_012,
            agreedUnits: agreedUnits,
            transcriptHash: keccak256("transcript"),
            decisionHash: keccak256("decision")
        });
    }

    /// 구매자는 합의 해시를 nonce 로 ERC-3009 서명을 한다. 토큰을 부르므로 vm.expectRevert 보다 먼저 부른다.
    function _signDeal(AegisToken target, AegisToken.Deal memory deal) internal view returns (Signature memory sig) {
        sig.validBefore = block.timestamp + 600;
        (sig.v, sig.r, sig.s) = _sign(
            target, buyerKey, deal.buyer, deal.seller, deal.agreedUnits, 0, sig.validBefore, target.hashDeal(deal)
        );
    }

    /// 중개자가 구매자 서명과 합의를 보낸다.
    function _send(AegisToken target, AegisToken.Deal memory deal, Signature memory sig) internal {
        vm.prank(relayer);
        target.settleDeal(deal, sig.validBefore, sig.v, sig.r, sig.s);
    }

    function test_settleDealStoresTheDealAndPaysTheAgreedPrice() public {
        AegisToken.Deal memory deal = _deal(keccak256("req-deal"), 64_300);
        bytes32 dealHash = token.hashDeal(deal);
        Signature memory sig = _signDeal(token, deal);

        vm.expectEmit(address(token));
        emit AegisToken.AuthorizationUsed(buyer, dealHash);
        vm.expectEmit(address(token));
        emit AegisToken.Paid(deal.requestId, buyer, seller, 64_300);
        vm.expectEmit(address(token));
        emit AegisToken.DealSettled(deal.requestId, buyer, seller, dealHash, 80_012, 64_300, deal.transcriptHash);
        _send(token, deal, sig);

        assertEq(token.balanceOf(seller), 64_300);
        assertEq(token.balanceOf(buyer), 1_000_000 - 64_300);
        (
            bytes32 requestId,
            address storedBuyer,
            address storedSeller,,
            uint256 ask,
            uint256 agreed,
            bytes32 transcript,
        ) = token.deals(deal.requestId);
        assertEq(requestId, deal.requestId);
        assertEq(storedBuyer, buyer);
        assertEq(storedSeller, seller);
        assertEq(ask, 80_012);
        assertEq(agreed, 64_300);
        assertEq(transcript, deal.transcriptHash);
    }

    function test_relayerCannotChangeTheAgreedPrice() public {
        AegisToken.Deal memory deal = _deal(keccak256("req-price"), 64_300);
        Signature memory sig = _signDeal(token, deal);
        deal.agreedUnits = 80_012;
        vm.expectRevert(AegisToken.InvalidAuthorization.selector);
        _send(token, deal, sig);
        assertEq(token.balanceOf(seller), 0);
    }

    function test_relayerCannotChangeTheTranscript() public {
        AegisToken.Deal memory deal = _deal(keccak256("req-transcript"), 64_300);
        Signature memory sig = _signDeal(token, deal);
        deal.transcriptHash = keccak256("edited transcript");
        vm.expectRevert(AegisToken.InvalidAuthorization.selector);
        _send(token, deal, sig);
        (, address storedBuyer,,,,,,) = token.deals(deal.requestId);
        assertEq(storedBuyer, address(0));
    }

    function test_oneDealPerRequest() public {
        AegisToken.Deal memory first = _deal(keccak256("req-once"), 64_300);
        _send(token, first, _signDeal(token, first));
        AegisToken.Deal memory second = _deal(keccak256("req-once"), 50_000);
        Signature memory sig = _signDeal(token, second);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.DealAlreadySettled.selector, first.requestId));
        _send(token, second, sig);
        assertEq(token.balanceOf(seller), 64_300);
    }

    function test_ruleBlocksDealAndNothingIsStored() public {
        RuledToken ruled = new RuledToken(owner);
        vm.prank(owner);
        ruled.mint(buyer, 1_000);
        AegisToken.Deal memory deal = _deal(keccak256("req-ruled"), 101);
        Signature memory sig = _signDeal(ruled, deal);
        vm.expectRevert(abi.encodeWithSelector(MaxHundredRule.OverHundred.selector, 101));
        _send(ruled, deal, sig);
        (, address storedBuyer,,,,,,) = ruled.deals(deal.requestId);
        assertEq(storedBuyer, address(0));
        assertEq(ruled.balanceOf(seller), 0);
    }
}
