// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {PaymentRules} from "../src/rules/PaymentRules.sol";

/// 규칙이 pay 에 끼어드는지 보려고 만든 시험용 규칙. 금액이 100 을 넘으면 막는다.
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

contract AegisTokenTest is Test {
    AegisToken token;
    address owner = makeAddr("owner");
    address buyer = makeAddr("buyer");
    address seller = makeAddr("seller");

    function setUp() public {
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

    function test_payMovesBalanceAndEmitsPaid() public {
        vm.prank(owner);
        token.mint(buyer, 400_000);
        bytes32 requestId = keccak256("req-1");
        vm.expectEmit(address(token));
        emit AegisToken.Paid(requestId, buyer, seller, 400_000);
        vm.prank(buyer);
        token.pay(seller, 400_000, requestId);
        assertEq(token.balanceOf(seller), 400_000);
    }

    function test_ruleBlocksPay() public {
        RuledToken ruled = new RuledToken(owner);
        vm.prank(owner);
        ruled.mint(buyer, 1_000);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(MaxHundredRule.OverHundred.selector, 101));
        ruled.pay(seller, 101, keccak256("req-2"));
        assertEq(ruled.balanceOf(seller), 0);
    }
}
