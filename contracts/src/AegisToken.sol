// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {PaymentRules} from "./rules/PaymentRules.sol";

/// @title AEGIS 토큰
/// @notice 구매 에이전트가 모델 값을 치르는 ERC-20. 소수점 6자리.
/// 구매 결제는 transfer 가 아니라 pay 로 한다. pay 는 요청 번호를 함께 받고, 송금 전에 감사 규칙을 돌린다.
/// 감사 규칙은 contracts/src/rules/ 에 파일로 따로 두고, 아래 상속 목록과 _checkPayment 의 override 목록에 이름만 더한다.
contract AegisToken is ERC20, Ownable, PaymentRules {
    /// @notice 구매 결제 한 건. 판매창구는 이 이벤트로 요청 번호·수신자·금액을 대조한다.
    event Paid(bytes32 indexed requestId, address indexed from, address indexed to, uint256 amount);

    constructor(address initialOwner) ERC20("AEGIS", "AEGIS") Ownable(initialOwner) {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice 운영자만 새로 발급한다.
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /// @notice 구매 결제. 감사 규칙을 모두 통과해야 송금한다.
    function pay(address to, uint256 amount, bytes32 requestId) external {
        _checkPayment(msg.sender, to, amount, requestId);
        _transfer(msg.sender, to, amount);
        emit Paid(requestId, msg.sender, to, amount);
    }

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal
        virtual
        override(PaymentRules)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}
