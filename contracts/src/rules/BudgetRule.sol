// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {PaymentRules} from "./PaymentRules.sol";

/// @title 시나리오 3 · 구매자 한 건 예산
/// @notice 운영자가 등록한 구매자 지갑(from)의 한 건 상한을 넘는 결제를 막는다.
/// 서버(agent_m2m/rules/budget.py)가 뚫려도 체인에서 한 번 더 막는다.
/// 상한은 운영자(owner)만 바꾼다. 구매자 지갑 키는 결제 서버에 있어서, 지갑 주인이 바꿀 수 있으면 해커가 상한부터 올린다.
/// 기본 상한은 서버 설정값 AEGIS_BUYER_BUDGET_PER_PAYMENT 의 기본값(0.1 AEGIS)과 같다. 한쪽을 바꾸면 다른 쪽도 바꾼다.
/// 서버가 설정값이 비어 있으면 규칙을 끄듯, 운영자가 등록하지 않은 지갑에는 상한을 걸지 않는다.
/// 금액은 units(1 AEGIS = 1,000,000) 다.
/// Ownable 을 PaymentRules 앞에 둔다. AegisToken 의 상속 순서(…, Ownable, PaymentRules, …)와 같아야 컴파일된다.
abstract contract BudgetRule is Ownable, PaymentRules {
    /// @notice 등록된 지갑에 따로 정한 상한이 없을 때 쓰는 기본 상한. 0.1 AEGIS.
    uint256 public defaultBudgetPerPayment = 100_000;

    /// @notice 운영자가 상한을 건 지갑인지.
    mapping(address wallet => bool enabled) public budgetEnabled;
    /// 지갑별로 따로 정한 상한. 0 이면 기본 상한을 쓴다.
    mapping(address wallet => uint256 units) private _walletBudget;

    event DefaultBudgetPerPaymentSet(uint256 units);
    /// @notice units 가 0 이면 기본 상한을 쓴다.
    event BudgetPerPaymentSet(address indexed wallet, uint256 units);
    event BudgetDisabled(address indexed wallet);

    error OverBuyerBudget(address from, uint256 amount, uint256 budget);

    /// @notice 이 지갑의 한 건 상한. 등록하지 않은 지갑은 상한이 없다(uint256 최댓값).
    function budgetPerPayment(address wallet) public view returns (uint256) {
        if (!budgetEnabled[wallet]) return type(uint256).max;
        uint256 units = _walletBudget[wallet];
        return units == 0 ? defaultBudgetPerPayment : units;
    }

    /// @notice 운영자만 기본 상한을 바꾼다. 따로 정한 상한이 없는 등록 지갑에 바로 적용된다.
    function setDefaultBudgetPerPayment(uint256 units) external onlyOwner {
        defaultBudgetPerPayment = units;
        emit DefaultBudgetPerPaymentSet(units);
    }

    /// @notice 운영자만 지갑에 기본 상한을 건다.
    function enableBudget(address wallet) external onlyOwner {
        _setBudget(wallet, 0);
    }

    /// @notice 운영자만 지갑에 상한을 따로 정해 건다. 0 이면 기본 상한을 쓴다.
    function setBudgetPerPayment(address wallet, uint256 units) external onlyOwner {
        _setBudget(wallet, units);
    }

    /// @notice 운영자만 지갑의 상한을 푼다.
    function disableBudget(address wallet) external onlyOwner {
        delete budgetEnabled[wallet];
        delete _walletBudget[wallet];
        emit BudgetDisabled(wallet);
    }

    function _setBudget(address wallet, uint256 units) private {
        budgetEnabled[wallet] = true;
        _walletBudget[wallet] = units;
        emit BudgetPerPaymentSet(wallet, units);
    }

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId) internal virtual override {
        super._checkPayment(from, to, amount, requestId);
        uint256 budget = budgetPerPayment(from);
        if (amount > budget) revert OverBuyerBudget(from, amount, budget);
    }
}
