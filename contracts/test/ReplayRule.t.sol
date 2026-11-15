// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {ReplayRule} from "../src/rules/ReplayRule.sol";
import {AegisTest} from "./AegisTest.sol";

contract ReplayRuleTest is AegisTest {
    AegisToken token;
    address owner = makeAddr("owner");
    address buyer;
    uint256 buyerKey;
    address other;
    uint256 otherKey;
    address seller = makeAddr("seller");
    uint256 constant AMOUNT = 1_000;

    function setUp() public {
        (buyer, buyerKey) = makeAddrAndKey("buyer");
        (other, otherKey) = makeAddrAndKey("other");
        token = new AegisToken(owner);
        vm.startPrank(owner);
        token.mint(buyer, 1_000_000_000);
        token.mint(other, 1_000_000_000);
        vm.stopPrank();
    }

    function _id(string memory name, uint256 index) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(name, index));
    }

    function test_sameRequestIdPaysOnlyOnce() public {
        bytes32 requestId = keccak256("req-replay");
        _pay(token, buyerKey, seller, AMOUNT, requestId);
        AegisToken.Deal memory again = _deal(buyer, seller, AMOUNT, requestId);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.DealAlreadySettled.selector, requestId));
        vm.prank(owner);
        token.openDeal(again, 1, "", keccak256("report"));
        assertEq(token.balanceOf(seller), AMOUNT);
    }

    function test_burstOverLimitReverts() public {
        uint256 max = token.rateLimit();
        for (uint256 i = 0; i < max; i++) _pay(token, buyerKey, seller, AMOUNT, _id("burst", i));
        _payReverting(token, buyerKey, seller, AMOUNT, _id("burst", max), abi.encodeWithSelector(ReplayRule.TooManyPayments.selector, buyer, max + 1));
        assertEq(token.balanceOf(seller), AMOUNT * max);
    }

    function test_failedPaymentCanRetryWithSameRequestId() public {
        uint256 max = token.rateLimit();
        for (uint256 i = 0; i < max; i++) _pay(token, buyerKey, seller, AMOUNT, _id("retry", i));
        bytes32 requestId = _id("retry", max);
        _payReverting(token, buyerKey, seller, AMOUNT, requestId, abi.encodeWithSelector(ReplayRule.TooManyPayments.selector, buyer, max + 1));
        assertEq(token.dealStatus(requestId), token.DEAL_OPEN()); // 송금 전에 막혀 합의는 열린 채로 남는다

        vm.warp(block.timestamp + token.rateWindow());
        _pay(token, buyerKey, seller, AMOUNT, requestId);
        assertEq(token.dealStatus(requestId), token.DEAL_SETTLED());
    }

    function test_windowResetsAfterRateWindow() public {
        uint256 max = token.rateLimit();
        uint256 start = vm.getBlockTimestamp();
        for (uint256 i = 0; i < max; i++) _pay(token, buyerKey, seller, AMOUNT, _id("first", i));
        vm.warp(start + token.rateWindow() - 1);
        _payReverting(token, buyerKey, seller, AMOUNT, _id("first", max), abi.encodeWithSelector(ReplayRule.TooManyPayments.selector, buyer, max + 1));

        vm.warp(start + token.rateWindow());
        _pay(token, buyerKey, seller, AMOUNT, _id("second", 0));
        assertEq(token.paymentsInWindow(buyer), 1);
    }

    /// 모든 결제를 같은 x402 정산 서버가 보내도 구매자(from)별로 따로 센다.
    function test_limitIsPerBuyerNotFacilitator() public {
        uint256 max = token.rateLimit();
        for (uint256 i = 0; i < max; i++) _pay(token, buyerKey, seller, AMOUNT, _id("buyer", i));
        _pay(token, otherKey, seller, AMOUNT, _id("other", 0));
        assertEq(token.paymentsInWindow(other), 1);
        assertEq(token.paymentsInWindow(facilitator), 0);
    }

    function test_ownerChangesLimit() public {
        uint256 max = token.rateLimit() + 2;
        uint256 window = token.rateWindow() * 2;
        vm.prank(owner);
        token.setRateLimit(max, window);
        assertEq(token.rateLimit(), max);
        assertEq(token.rateWindow(), window);
        for (uint256 i = 0; i < max; i++) _pay(token, buyerKey, seller, AMOUNT, _id("raised", i));
        _payReverting(token, buyerKey, seller, AMOUNT, _id("raised", max), abi.encodeWithSelector(ReplayRule.TooManyPayments.selector, buyer, max + 1));
    }

    function test_buyerAndFacilitatorCannotChangeLimit() public {
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, buyer));
        token.setRateLimit(100, 1);
        vm.prank(facilitator);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, facilitator));
        token.setRateLimit(100, 1);
    }

    function test_zeroLimitRejected() public {
        vm.prank(owner);
        vm.expectRevert(ReplayRule.InvalidRateLimit.selector);
        token.setRateLimit(0, 60);
    }
}
