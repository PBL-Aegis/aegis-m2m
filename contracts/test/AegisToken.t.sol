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

    function test_versionMatchesSigningDomain() public view {
        assertEq(token.version(), "1");
        assertEq(token.name(), "AEGIS");
    }

    function test_authorizationPaysFromSignerAndEmitsPaid() public {
        vm.prank(owner);
        token.mint(buyer, 400_000);
        AegisToken.Deal memory deal = _deal(buyer, seller, 400_000, keccak256("req-1"));
        _open(token, deal);
        bytes32 dealHash = _hashDeal(deal);
        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.expectEmit(address(token));
        emit AegisToken.AuthorizationUsed(buyer, dealHash);
        vm.expectEmit(address(token));
        emit AegisToken.Paid(deal.requestId, buyer, seller, 400_000);
        _submit(token, deal, sig);
        assertEq(token.balanceOf(seller), 400_000);
        assertEq(token.balanceOf(buyer), 0);
        assertTrue(token.authorizationState(buyer, dealHash));
    }

    function test_authorizationCannotBeReused() public {
        vm.prank(owner);
        token.mint(buyer, 1_000);
        AegisToken.Deal memory deal = _deal(buyer, seller, 100, keccak256("req-again"));
        _open(token, deal);
        Signature memory sig = _signDeal(token, buyerKey, deal);
        _submit(token, deal, sig);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.AuthorizationAlreadyUsed.selector, buyer, _hashDeal(deal)));
        _submit(token, deal, sig);
        assertEq(token.balanceOf(seller), 100);
    }

    function test_authorizationRejectsChangedRecipient() public {
        vm.prank(owner);
        token.mint(buyer, 1_000);
        AegisToken.Deal memory deal = _deal(buyer, seller, 100, keccak256("req-swap"));
        _open(token, deal);
        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.prank(facilitator);
        vm.expectRevert(AegisToken.InvalidAuthorization.selector);
        token.transferWithAuthorization(buyer, facilitator, 100, 0, sig.validBefore, _hashDeal(deal), sig.v, sig.r, sig.s);
        assertEq(token.balanceOf(buyer), 1_000);
    }

    function test_authorizationExpires() public {
        vm.prank(owner);
        token.mint(buyer, 1_000);
        AegisToken.Deal memory deal = _deal(buyer, seller, 100, keccak256("req-late"));
        _open(token, deal);
        Signature memory sig = _signDeal(token, buyerKey, deal);
        vm.warp(sig.validBefore);
        vm.expectRevert(abi.encodeWithSelector(AegisToken.AuthorizationExpired.selector, sig.validBefore));
        _submit(token, deal, sig);
    }

    function test_ruleBlocksPayment() public {
        RuledToken ruled = new RuledToken(owner);
        vm.prank(owner);
        ruled.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-big");
        _payReverting(ruled, buyerKey, seller, 101, requestId, abi.encodeWithSelector(MaxHundredRule.OverHundred.selector, 101));
        assertEq(ruled.balanceOf(seller), 0);
        assertEq(ruled.dealStatus(requestId), ruled.DEAL_OPEN());
    }
}
