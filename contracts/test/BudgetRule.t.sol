// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisToken} from "../src/AegisToken.sol";
import {BudgetRule} from "../src/rules/BudgetRule.sol";
import {AegisTest} from "./AegisTest.sol";

/// AEGIS + 내 규칙(BudgetRule)만 붙인 시험용 토큰. 메모리 속 가짜 체인에 잠깐 올렸다 버린다.
contract BudgetToken is BudgetRule, AegisToken {
    constructor(address initialOwner) AegisToken(initialOwner) {}

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal
        override(AegisToken, BudgetRule)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}

/// 시나리오 3 · 요청 바꿔치기. 서버가 뚫려 비싼 모델 값이 결제로 넘어와도 운영자가 건 한 건 상한에서 막히는지 본다.
/// 금액은 숫자로 적지 않고 토큰의 기본 상한(서버 기본값과 같은 0.1 AEGIS)에서 계산한다.
contract BudgetRuleTest is AegisTest {
    BudgetToken token;
    address owner = makeAddr("owner");
    address seller = makeAddr("seller");
    address buyer;
    uint256 buyerKey;
    address otherBuyer;
    uint256 otherBuyerKey;
    uint256 budget;

    function setUp() public {
        (buyer, buyerKey) = makeAddrAndKey("buyer");
        (otherBuyer, otherBuyerKey) = makeAddrAndKey("otherBuyer");
        token = new BudgetToken(owner);
        budget = token.defaultBudgetPerPayment();
        vm.startPrank(owner);
        token.mint(buyer, budget * 10);
        token.mint(otherBuyer, budget * 10);
        vm.stopPrank();
    }

    function _enable(address wallet) internal {
        vm.prank(owner);
        token.enableBudget(wallet);
    }

    /// 운영자가 상한을 걸지 않은 지갑은 막지 않는다(서버 설정값이 비어 있으면 규칙을 끄는 것과 같다).
    function test_walletWithoutBudgetIsNotLimited() public {
        assertFalse(token.budgetEnabled(buyer));
        _pay(token, buyerKey, seller, budget * 2, keccak256("req-off"));
        assertEq(token.balanceOf(seller), budget * 2);
    }

    /// 기본 상한까지는 결제되고, 넘으면(바꿔치기로 비싼 모델) revert 한다.
    function test_paysUpToDefaultBudgetAndRevertsAbove() public {
        _enable(buyer);
        assertEq(token.budgetPerPayment(buyer), budget);
        _pay(token, buyerKey, seller, budget, keccak256("req-cheap"));
        assertEq(token.balanceOf(seller), budget);

        vm.expectRevert(abi.encodeWithSelector(BudgetRule.OverBuyerBudget.selector, buyer, budget + 1, budget));
        _pay(token, buyerKey, seller, budget + 1, keccak256("req-tampered"));
        assertEq(token.balanceOf(seller), budget);
    }

    /// 지갑마다 상한을 따로 정할 수 있고, 다른 지갑은 기본 상한 그대로다.
    function test_walletBudgetIsPerWallet() public {
        vm.prank(owner);
        token.setBudgetPerPayment(buyer, budget * 2);
        _enable(otherBuyer);

        _pay(token, buyerKey, seller, budget * 2, keccak256("req-raised"));
        assertEq(token.balanceOf(seller), budget * 2);
        vm.expectRevert(abi.encodeWithSelector(BudgetRule.OverBuyerBudget.selector, otherBuyer, budget + 1, budget));
        _pay(token, otherBuyerKey, seller, budget + 1, keccak256("req-other"));
    }

    /// 구매자는 중개자(msg.sender)가 아니라 from 으로 센다.
    function test_countsBuyerByFromNotRelayer() public {
        // 중개자 지갑의 상한을 1 unit 으로 걸어도 구매자 결제에는 상관없다.
        vm.prank(owner);
        token.setBudgetPerPayment(relayer, 1);
        _enable(buyer);
        _pay(token, buyerKey, seller, budget, keccak256("req-relayer"));
        assertEq(token.balanceOf(seller), budget);
    }

    /// 운영자가 기본 상한을 바꾸면 따로 정한 상한이 없는 등록 지갑에 바로 적용된다.
    function test_ownerChangesDefaultBudget() public {
        _enable(buyer);
        vm.expectEmit(address(token));
        emit BudgetRule.DefaultBudgetPerPaymentSet(budget * 2);
        vm.prank(owner);
        token.setDefaultBudgetPerPayment(budget * 2);
        _pay(token, buyerKey, seller, budget * 2, keccak256("req-default"));
        assertEq(token.balanceOf(seller), budget * 2);
    }

    /// 운영자가 상한을 풀면 다시 막지 않는다.
    function test_ownerDisablesBudget() public {
        _enable(buyer);
        vm.expectEmit(address(token));
        emit BudgetRule.BudgetDisabled(buyer);
        vm.prank(owner);
        token.disableBudget(buyer);
        _pay(token, buyerKey, seller, budget * 2, keccak256("req-disabled"));
        assertEq(token.balanceOf(seller), budget * 2);
    }

    /// 구매자 지갑은 상한을 풀거나 올릴 수 없다(서버가 뚫려 지갑 키가 넘어가도).
    function test_buyerCannotChangeBudget() public {
        _enable(buyer);
        bytes memory unauthorized = abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, buyer);
        vm.startPrank(buyer);
        vm.expectRevert(unauthorized);
        token.disableBudget(buyer);
        vm.expectRevert(unauthorized);
        token.setBudgetPerPayment(buyer, budget * 10);
        vm.expectRevert(unauthorized);
        token.setDefaultBudgetPerPayment(budget * 10);
        vm.stopPrank();
        assertEq(token.budgetPerPayment(buyer), budget);
    }

    /// 중개자 지갑도 상한을 바꿀 수 없다.
    function test_relayerCannotChangeBudget() public {
        _enable(buyer);
        bytes memory unauthorized = abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, relayer);
        vm.startPrank(relayer);
        vm.expectRevert(unauthorized);
        token.disableBudget(buyer);
        vm.expectRevert(unauthorized);
        token.setDefaultBudgetPerPayment(budget * 10);
        vm.stopPrank();
    }
}
