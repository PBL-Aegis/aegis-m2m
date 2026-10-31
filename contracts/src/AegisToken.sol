// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {PaymentRules} from "./rules/PaymentRules.sol";

/// @title AEGIS 토큰
/// @notice 구매 에이전트가 모델 값을 치르는 ERC-20. 소수점 6자리.
/// 구매 결제는 transfer 가 아니라 transferWithAuthorization(ERC-3009) 으로 한다.
/// 구매자가 서명하고 중개자가 보내며, 요청 번호를 서명의 nonce 로 받아 송금 전에 감사 규칙을 돌리고 Paid 를 남긴다.
/// 감사 규칙은 contracts/src/rules/ 에 파일로 따로 두고, 아래 상속 목록과 _checkPayment 의 override 목록에 이름만 더한다.
contract AegisToken is ERC20, EIP712, Ownable, PaymentRules {
    /// @notice ERC-3009 서명 내용. 구매자는 이 내용에 서명만 하고, 거래는 중개자가 보낸다(가스비도 중개자가 낸다).
    bytes32 public constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );

    /// @notice 구매 결제 한 건. 판매창구는 이 이벤트로 요청 번호·수신자·금액을 대조한다.
    event Paid(bytes32 indexed requestId, address indexed from, address indexed to, uint256 amount);
    /// @notice ERC-3009: 서명 한 장이 쓰였다. nonce 는 요청 번호다.
    event AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce);

    error AuthorizationNotYetValid(uint256 validAfter);
    error AuthorizationExpired(uint256 validBefore);
    error AuthorizationAlreadyUsed(address authorizer, bytes32 nonce);
    error InvalidAuthorization();

    mapping(address authorizer => mapping(bytes32 nonce => bool used)) private _authorizationStates;

    constructor(address initialOwner) ERC20("AEGIS", "AEGIS") EIP712("AEGIS", "1") Ownable(initialOwner) {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice 운영자만 새로 발급한다.
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /// @notice ERC-3009 구매 결제. from 이 서명한 내용 그대로, 누구든 대신 보낼 수 있다.
    /// nonce 자리에 요청 번호를 넣는다. 같은 서명(같은 요청 번호)은 한 번만 쓰인다.
    /// 감사 규칙을 모두 통과해야 송금한다.
    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external {
        if (block.timestamp <= validAfter) revert AuthorizationNotYetValid(validAfter);
        if (block.timestamp >= validBefore) revert AuthorizationExpired(validBefore);
        if (_authorizationStates[from][nonce]) revert AuthorizationAlreadyUsed(from, nonce);

        bytes32 structHash =
            keccak256(abi.encode(TRANSFER_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce));
        if (ECDSA.recover(_hashTypedDataV4(structHash), v, r, s) != from) revert InvalidAuthorization();

        _authorizationStates[from][nonce] = true;
        emit AuthorizationUsed(from, nonce);
        _checkPayment(from, to, value, nonce);
        _transfer(from, to, value);
        emit Paid(nonce, from, to, value);
    }

    /// @notice ERC-3009: 이 서명(요청 번호)이 이미 쓰였는지.
    function authorizationState(address authorizer, bytes32 nonce) external view returns (bool) {
        return _authorizationStates[authorizer][nonce];
    }

    /// @notice 서명에 쓰는 EIP-712 도메인 구분값.
    function DOMAIN_SEPARATOR() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal
        virtual
        override(PaymentRules)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}
