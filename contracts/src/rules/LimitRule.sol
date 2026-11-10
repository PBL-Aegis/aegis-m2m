// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {PaymentRules} from "./PaymentRules.sol";

abstract contract LimitRule is Ownable, PaymentRules {
    uint256 public limitPerPayment = 500_000;  // 0.5 AEGIS (units)
    uint256 public limitPerDay = 3_000_000;    // 3 AEGIS (units)

    // 지갑(from) => 날짜(UTC 일 번호) => 그날 쓴 합계
    mapping(address => mapping(uint256 => uint256)) public dailyUsed;

    error OverPaymentLimit(uint256 amount);
    error OverDailyLimit(address from, uint256 used, uint256 amount);

    function setLimitPerPayment(uint256 v) external onlyOwner {
        limitPerPayment = v;
    }

    function setLimitPerDay(uint256 v) external onlyOwner {
        limitPerDay = v;
    }

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal
        virtual
        override
    {
        super._checkPayment(from, to, amount, requestId);
        if (amount > limitPerPayment) revert OverPaymentLimit(amount);

        uint256 today = block.timestamp / 1 days;
        uint256 used = dailyUsed[from][today];
        if (used + amount > limitPerDay) revert OverDailyLimit(from, used, amount);
        dailyUsed[from][today] = used + amount;
    }
}