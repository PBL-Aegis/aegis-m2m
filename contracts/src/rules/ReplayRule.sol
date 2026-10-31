// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {PaymentRules} from "./PaymentRules.sol";

/// @title 연타 막기
/// @notice 한 지갑(from)이 창(기본 60초) 안에 결제를 rateLimit(기본 5)건 넘게 하지 못한다.
/// 거래를 보내는 msg.sender 는 중개자라서, 구매자는 from 으로 센다.
/// 창은 첫 결제 때 열리고, rateWindow 가 지난 뒤의 첫 결제에서 새로 열린다.
/// 같은 요청 번호의 재결제는 AegisToken 이 ERC-3009 nonce 로 막는다(AuthorizationAlreadyUsed).
/// 서버의 agent_m2m/rules/replay.py 는 같은 요청 번호와 같은 문장 반복을 막는다.
/// 숫자는 운영자만 바꿀 수 있다.
abstract contract ReplayRule is Ownable, PaymentRules {
    uint256 public rateLimit = 5;
    uint256 public rateWindow = 60;

    mapping(address => uint256) public windowStart;
    mapping(address => uint256) public paymentsInWindow;

    error TooManyPayments(address from, uint256 count);
    error InvalidRateLimit();

    event RateLimitChanged(uint256 rateLimit, uint256 rateWindow);

    function setRateLimit(uint256 limit, uint256 window) external onlyOwner {
        if (limit == 0 || window == 0) revert InvalidRateLimit();
        rateLimit = limit;
        rateWindow = window;
        emit RateLimitChanged(limit, window);
    }

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId) internal virtual override {
        super._checkPayment(from, to, amount, requestId);

        uint256 count;
        if (paymentsInWindow[from] == 0 || block.timestamp >= windowStart[from] + rateWindow) {
            windowStart[from] = block.timestamp;
            count = 1;
        } else {
            count = paymentsInWindow[from] + 1;
        }
        if (count > rateLimit) revert TooManyPayments(from, count);
        paymentsInWindow[from] = count;
    }
}
