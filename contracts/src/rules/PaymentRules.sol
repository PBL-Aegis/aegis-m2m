// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title 결제 규칙의 공통 바탕
/// @notice 감사 규칙은 이 컨트랙트를 상속해 _checkPayment 를 덮어쓴다.
/// 덮어쓸 때는 먼저 super._checkPayment(...) 를 불러 다른 규칙도 돌게 하고, 막을 때는 revert 한다.
abstract contract PaymentRules {
    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId) internal virtual {}
}
