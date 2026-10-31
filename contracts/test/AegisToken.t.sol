// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {PaymentRules} from "../src/rules/PaymentRules.sol";
import {AegisTest} from "./AegisTest.sol";

/// 규칙이 결제에 끼어드는지 보려고 만든 시험용 규칙. 금액이 100 을 넘으면 막는다.
abstract contract MaxHundredRule is PaymentRules {
    error OverHundred(uint256 amount);

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId) internal virtual override {
        super._checkPayment(from, to, amount, requestId);
        if (amount > 100) revert OverHundred(amount);
    }
}

contract RuledToken is AegisToken, MaxHundredRule {
    constructor(address initialOwner) AegisToken(initialOwner) {}

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal
        override(AegisToken, MaxHundredRule)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}

contract AegisTokenTest is AegisTest {
    AegisToken token;
    address owner = makeAddr("owner");
    address buyer;
    uint256 buyerKey;
    address seller = makeAddr("seller");

    function setUp() public {
        (buyer, buyerKey) = makeAddrAndKey("buyer");
        token = new AegisToken(owner);
    }

    function test_decimalsIsSix() public view {
        assertEq(token.decimals(), 6);
    }

    function test_ownerMints() public {
        vm.prank(owner);
        token.mint(buyer, 3_000_000);
        assertEq(token.balanceOf(buyer), 3_000_000);
    }

    function test_othersCannotMint() public {
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, buyer));
        token.mint(buyer, 1);
    }

    function test_transferMovesBalance() public {
        vm.prank(owner);
        token.mint(buyer, 400_000);
        vm.prank(buyer);
        token.transfer(seller, 400_000);
        assertEq(token.balanceOf(seller), 400_000);
        assertEq(token.balanceOf(buyer), 0);
    }

    function test_authorizationPaysFromSignerAndEmitsPaid() public {
        vm.prank(owner);
        token.mint(buyer, 400_000);
        bytes32 requestId = keccak256("req-1");
        vm.expectEmit(address(token));
        emit AegisToken.AuthorizationUsed(buyer, requestId);
        vm.expectEmit(address(token));
        emit AegisToken.Paid(requestId, buyer, seller, 400_000);
        _pay(token, buyerKey, seller, 400_000, requestId);
        assertEq(token.balanceOf(seller), 400_000);
        assertEq(token.balanceOf(buyer), 0);
        assertTrue(token.authorizationState(buyer, requestId));
    }

    function test_authorizationCannotBeReused() public {
        vm.prank(owner);
        token.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-again");
        uint256 validBefore = block.timestamp + 600;
        (uint8 v, bytes32 r, bytes32 s) = _sign(token, buyerKey, buyer, seller, 100, 0, validBefore, requestId);
        vm.prank(relayer);
        token.transferWithAuthorization(buyer, seller, 100, 0, validBefore, requestId, v, r, s);
        vm.prank(relayer);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.AuthorizationAlreadyUsed.selector, buyer, requestId));
        token.transferWithAuthorization(buyer, seller, 100, 0, validBefore, requestId, v, r, s);
        assertEq(token.balanceOf(seller), 100);
    }

    function test_authorizationRejectsChangedRecipient() public {
        vm.prank(owner);
        token.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-swap");
        uint256 validBefore = block.timestamp + 600;
        (uint8 v, bytes32 r, bytes32 s) = _sign(token, buyerKey, buyer, seller, 100, 0, validBefore, requestId);
        vm.prank(relayer);
        vm.expectRevert(AegisToken.InvalidAuthorization.selector);
        token.transferWithAuthorization(buyer, relayer, 100, 0, validBefore, requestId, v, r, s);
        assertEq(token.balanceOf(buyer), 1_000);
    }

    function test_authorizationExpires() public {
        vm.prank(owner);
        token.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-late");
        uint256 validBefore = block.timestamp + 600;
        (uint8 v, bytes32 r, bytes32 s) = _sign(token, buyerKey, buyer, seller, 100, 0, validBefore, requestId);
        vm.warp(validBefore);
        vm.prank(relayer);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.AuthorizationExpired.selector, validBefore));
        token.transferWithAuthorization(buyer, seller, 100, 0, validBefore, requestId, v, r, s);
    }

    function test_ruleBlocksPayment() public {
        RuledToken ruled = new RuledToken(owner);
        vm.prank(owner);
        ruled.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-big");
        vm.expectRevert(abi.encodeWithSelector(MaxHundredRule.OverHundred.selector, 101));
        _pay(ruled, buyerKey, seller, 101, requestId);
        assertEq(ruled.balanceOf(seller), 0);
        assertFalse(ruled.authorizationState(buyer, requestId));
    }
}
