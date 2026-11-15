// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {AegisTest} from "./AegisTest.sol";
import {RuledToken, MaxHundredRule} from "./AegisToken.t.sol";

/// 흥정한 구매의 결제. 운영자가 합의와 송금 직전 감사 결과를 열고(openDeal), 구매자 서명을 x402 정산 서버가 올린다.
/// 감사 기록이 없거나 막힌 결제, 합의와 다른 결제는 체인이 거절하는지 본다.
contract DealSettlementTest is AegisTest {
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

    function test_openedDealIsPaidAndStored() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-deal"));
        bytes32 dealHash = _hashDeal(deal);

        vm.expectEmit(address(token));
        emit AegisToken.AuditRecorded(deal.requestId, 1, 2, "persona-gap", keccak256("report"));
        vm.expectEmit(address(token));
        emit AegisToken.DealOpened(deal.requestId, buyer, seller, dealHash);
        vm.prank(owner);
        token.openDeal(deal, 2, "persona-gap", keccak256("report"));

        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.expectEmit(address(token));
        emit AegisToken.Paid(deal.requestId, buyer, seller, 64_300);
        vm.expectEmit(address(token));
        emit AegisToken.DealSettled(deal.requestId, buyer, seller, dealHash, deal.askUnits, 64_300, deal.transcriptHash);
        _submit(token, deal, sig);

        assertEq(token.balanceOf(seller), 64_300);
        assertEq(token.dealStatus(deal.requestId), token.DEAL_SETTLED());
        (, address storedBuyer,,,, uint256 agreed,,) = token.deals(deal.requestId);
        assertEq(storedBuyer, buyer);
        assertEq(agreed, 64_300);
        (uint8 result, bytes32 reportHash) = token.audits(deal.requestId, 1);
        assertEq(result, 2);
        assertEq(reportHash, keccak256("report"));
    }

    function test_paymentWithoutOpenDealIsRejected() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-no-audit"));
        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.NoOpenDeal.selector, _hashDeal(deal)));
        _submit(token, deal, sig);
        assertEq(token.balanceOf(seller), 0);
    }

    function test_blockedAuditIsRecordedButDealIsNotOpened() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-blocked"));
        _openWith(token, deal, 3);
        (uint8 result,) = token.audits(deal.requestId, 1);
        assertEq(result, 3);
        assertEq(token.dealStatus(deal.requestId), 0);

        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.NoOpenDeal.selector, _hashDeal(deal)));
        _submit(token, deal, sig);
    }

    function test_blockingAnOpenDealClosesIt() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-reblocked"));
        _open(token, deal);
        _openWith(token, deal, 3);
        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.NoOpenDeal.selector, _hashDeal(deal)));
        _submit(token, deal, sig);
    }

    function test_buyerSignatureForAnotherPriceDoesNotMatchTheDeal() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-price"));
        _open(token, deal);
        // 구매자가 합의 해시를 nonce 로 쓰되 금액을 바꿔 서명해도, 체인은 합의 금액과 다르다며 거절한다.
        uint256 validBefore = block.timestamp + 600;
        bytes32 dealHash = _hashDeal(deal);
        (uint8 v, bytes32 r, bytes32 s) = _sign(token, buyerKey, buyer, seller, 80_000, 0, validBefore, dealHash);
        vm.prank(facilitator);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.DealMismatch.selector, deal.requestId));
        token.transferWithAuthorization(buyer, seller, 80_000, 0, validBefore, dealHash, v, r, s);
    }

    function test_changedTranscriptIsADifferentDeal() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-transcript"));
        _open(token, deal);
        AegisToken.Deal memory edited = deal;
        edited.transcriptHash = keccak256("edited transcript");
        Signature memory sig = _signDeal(token, buyerKey, edited);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.NoOpenDeal.selector, _hashDeal(edited)));
        _submit(token, edited, sig);
    }

    function test_onlyOwnerOpensDealsAndRecordsAudits() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-owner"));
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, buyer));
        token.openDeal(deal, 1, "", bytes32(0));
        vm.prank(facilitator);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, facilitator));
        token.recordAudit(deal.requestId, 1, "", bytes32(0));
    }

    function test_invalidAuditResultIsRejected() public {
        AegisToken.Deal memory deal = _deal(buyer, seller, 64_300, keccak256("req-invalid"));
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.InvalidAudit.selector, 1, 4));
        token.openDeal(deal, 4, "", bytes32(0));
    }

    function test_afterSendAuditOnlyOncePerSettledDeal() public {
        bytes32 requestId = keccak256("req-after");
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.DealNotSettled.selector, requestId));
        token.recordAudit(requestId, 1, "", bytes32(0));

        _pay(token, buyerKey, seller, 64_300, requestId);
        vm.prank(owner);
        token.recordAudit(requestId, 2, "seller-collusion", keccak256("after"));
        (uint8 result, bytes32 reportHash) = token.audits(requestId, 2);
        assertEq(result, 2);
        assertEq(reportHash, keccak256("after"));

        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.AuditAlreadyRecorded.selector, requestId, 2));
        token.recordAudit(requestId, 1, "", bytes32(0));
    }

    function test_settledDealCannotBeReopened() public {
        bytes32 requestId = keccak256("req-once");
        _pay(token, buyerKey, seller, 64_300, requestId);
        AegisToken.Deal memory again = _deal(buyer, seller, 50_000, requestId);
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.DealAlreadySettled.selector, requestId));
        token.openDeal(again, 1, "", bytes32(0));
        assertEq(token.balanceOf(seller), 64_300);
    }

    function test_ruleBlocksDealAndItStaysOpen() public {
        RuledToken ruled = new RuledToken(owner);
        vm.prank(owner);
        ruled.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-ruled");
        _payReverting(ruled, buyerKey, seller, 101, requestId, abi.encodeWithSelector(MaxHundredRule.OverHundred.selector, 101));
        assertEq(ruled.dealStatus(requestId), ruled.DEAL_OPEN());
        assertEq(ruled.balanceOf(seller), 0);
    }
}
