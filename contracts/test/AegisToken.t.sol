// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {PaymentRules} from "../src/rules/PaymentRules.sol";

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

contract AegisTokenTest is Test {
    AegisToken token;
    address owner = makeAddr("owner");
    address buyer;
    uint256 buyerKey;
    address seller = makeAddr("seller");
    address relayer = makeAddr("relayer");

    function setUp() public {
        (buyer, buyerKey) = makeAddrAndKey("buyer");
        token = new AegisToken(owner);
    }

    /// 구매자가 서명한 ERC-3009 결제를 중개자가 보낸다. 유효기간은 지금부터 10분.
    function _payWithAuthorization(AegisToken target, uint256 signerKey, address to, uint256 value, bytes32 requestId)
        internal
    {
        address from = vm.addr(signerKey);
        uint256 validBefore = block.timestamp + 600;
        (uint8 v, bytes32 r, bytes32 s) = _sign(target, signerKey, from, to, value, 0, validBefore, requestId);
        vm.prank(relayer);
        target.transferWithAuthorization(from, to, value, 0, validBefore, requestId, v, r, s);
    }

    function _sign(
        AegisToken target,
        uint256 signerKey,
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce
    ) internal view returns (uint8, bytes32, bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(target.TRANSFER_WITH_AUTHORIZATION_TYPEHASH(), from, to, value, validAfter, validBefore, nonce)
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", target.DOMAIN_SEPARATOR(), structHash));
        return vm.sign(signerKey, digest);
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

    function test_authorizationPaysFromSignerAndEmitsPaid() public {
        vm.prank(owner);
        token.mint(buyer, 400_000);
        bytes32 requestId = keccak256("req-3009");
        vm.expectEmit(address(token));
        emit AegisToken.AuthorizationUsed(buyer, requestId);
        vm.expectEmit(address(token));
        emit AegisToken.Paid(requestId, buyer, seller, 400_000);
        _payWithAuthorization(token, buyerKey, seller, 400_000, requestId);
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

    function test_ruleBlocksAuthorization() public {
        RuledToken ruled = new RuledToken(owner);
        vm.prank(owner);
        ruled.mint(buyer, 1_000);
        bytes32 requestId = keccak256("req-big");
        uint256 validBefore = block.timestamp + 600;
        (uint8 v, bytes32 r, bytes32 s) = _sign(ruled, buyerKey, buyer, seller, 101, 0, validBefore, requestId);
        vm.prank(relayer);
        vm.expectRevert(abi.encodeWithSelector(MaxHundredRule.OverHundred.selector, 101));
        ruled.transferWithAuthorization(buyer, seller, 101, 0, validBefore, requestId, v, r, s);
        assertEq(ruled.balanceOf(seller), 0);
        assertFalse(ruled.authorizationState(buyer, requestId));
    }
}
