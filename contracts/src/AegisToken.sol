// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {PaymentRules} from "./rules/PaymentRules.sol";
import {ReplayRule} from "./rules/ReplayRule.sol";

/// @title AEGIS 토큰
/// @notice 구매 에이전트가 모델 값을 치르는 ERC-20. 소수점 6자리.
/// 구매 결제는 transfer 가 아니라 transferWithAuthorization(ERC-3009) 으로 한다.
/// 구매자가 서명하고 중개자가 보내며, 요청 번호를 서명의 nonce 로 받아 송금 전에 감사 규칙을 돌리고 Paid 를 남긴다.
/// 흥정한 구매는 settleDeal 로 결제한다. 합의 내용을 체인에 저장하고 그 합의대로만 송금한다.
/// 감사 규칙은 contracts/src/rules/ 에 파일로 따로 두고, 아래 상속 목록과 _checkPayment 의 override 목록에 이름만 더한다.
contract AegisToken is ERC20, EIP712, Ownable, PaymentRules, ReplayRule {
    /// @notice ERC-3009 서명 내용. 구매자는 이 내용에 서명만 하고, 거래는 중개자가 보낸다(가스비도 중개자가 낸다).
    bytes32 public constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );

    /// @notice 구매 에이전트와 판매 에이전트의 합의. 대화 원문과 결정 근거는 서버 DB 에 두고 해시만 담는다.
    struct Deal {
        bytes32 requestId; // 요청 번호 문자열의 keccak256
        address buyer; // 구매 에이전트 지갑. 송금하는 쪽
        address seller; // 판매 에이전트(회사) 수신 주소
        bytes32 modelKey; // 모델 키 문자열의 keccak256. 예: keccak256("anthropic/claude-opus-5.5")
        uint256 askUnits; // 판매자 첫 호가
        uint256 agreedUnits; // 합의가. 실제 송금액
        bytes32 transcriptHash; // 흥정 대화 기록의 해시
        bytes32 decisionHash; // 후보·점수 등 결정 근거의 해시
    }

    /// @notice 합의 내용의 해시를 만드는 형식. 구매자는 이 해시를 ERC-3009 서명의 nonce 로 쓴다.
    bytes32 public constant DEAL_TYPEHASH = keccak256(
        "Deal(bytes32 requestId,address buyer,address seller,bytes32 modelKey,uint256 askUnits,uint256 agreedUnits,bytes32 transcriptHash,bytes32 decisionHash)"
    );

    /// @notice 체인에 저장된 합의. 요청 번호로 누구나 읽는다.
    mapping(bytes32 requestId => Deal) public deals;

    /// @notice 구매 결제 한 건. 판매창구는 이 이벤트로 요청 번호·수신자·금액을 대조한다.
    event Paid(bytes32 indexed requestId, address indexed from, address indexed to, uint256 amount);
    /// @notice ERC-3009: 서명 한 장이 쓰였다. nonce 는 요청 번호(흥정한 구매는 합의 해시)다.
    event AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce);
    /// @notice 합의가 체인에 저장되고 그 합의대로 송금됐다.
    event DealSettled(
        bytes32 indexed requestId,
        address indexed buyer,
        address indexed seller,
        bytes32 dealHash,
        uint256 askUnits,
        uint256 agreedUnits,
        bytes32 transcriptHash
    );

    error AuthorizationNotYetValid(uint256 validAfter);
    error AuthorizationExpired(uint256 validBefore);
    error AuthorizationAlreadyUsed(address authorizer, bytes32 nonce);
    error InvalidAuthorization();
    error DealAlreadySettled(bytes32 requestId);

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
        _useAuthorization(from, to, value, validAfter, validBefore, nonce, v, r, s);
        _checkPayment(from, to, value, nonce);
        _transfer(from, to, value);
        emit Paid(nonce, from, to, value);
    }

    /// @notice 흥정한 구매의 결제. 합의 내용을 받아 해시를 다시 계산하고, 구매자가 그 해시를 nonce 로 서명했는지 확인한다.
    /// 그래서 구매자 서명은 합의 내용 전체에 대한 동의가 되고, 합의가 아닌 금액이나 수신자로는 송금되지 않는다.
    /// 감사 규칙을 통과하면 합의를 저장하고 합의가만큼 송금한다. 같은 요청 번호의 합의는 한 번만 받는다.
    function settleDeal(Deal calldata deal, uint256 validBefore, uint8 v, bytes32 r, bytes32 s) external {
        if (deals[deal.requestId].buyer != address(0)) revert DealAlreadySettled(deal.requestId);
        bytes32 dealHash = hashDeal(deal);
        _useAuthorization(deal.buyer, deal.seller, deal.agreedUnits, 0, validBefore, dealHash, v, r, s);
        _checkPayment(deal.buyer, deal.seller, deal.agreedUnits, deal.requestId);
        deals[deal.requestId] = deal;
        _transfer(deal.buyer, deal.seller, deal.agreedUnits);
        emit Paid(deal.requestId, deal.buyer, deal.seller, deal.agreedUnits);
        emit DealSettled(
            deal.requestId, deal.buyer, deal.seller, dealHash, deal.askUnits, deal.agreedUnits, deal.transcriptHash
        );
    }

    /// @notice 합의 내용의 해시. 서버도 같은 방식으로 계산해 구매자 서명의 nonce 로 쓴다.
    function hashDeal(Deal calldata deal) public pure returns (bytes32) {
        return keccak256(
            abi.encode(
                DEAL_TYPEHASH,
                deal.requestId,
                deal.buyer,
                deal.seller,
                deal.modelKey,
                deal.askUnits,
                deal.agreedUnits,
                deal.transcriptHash,
                deal.decisionHash
            )
        );
    }

    /// @notice ERC-3009: 이 서명(요청 번호)이 이미 쓰였는지.
    function authorizationState(address authorizer, bytes32 nonce) external view returns (bool) {
        return _authorizationStates[authorizer][nonce];
    }

    /// @notice 서명에 쓰는 EIP-712 도메인 구분값.
    function DOMAIN_SEPARATOR() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    /// @notice ERC-3009 서명을 확인하고 쓴 것으로 표시한다. 유효기간·재사용·서명자를 검사한다.
    function _useAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) private {
        if (block.timestamp <= validAfter) revert AuthorizationNotYetValid(validAfter);
        if (block.timestamp >= validBefore) revert AuthorizationExpired(validBefore);
        if (_authorizationStates[from][nonce]) revert AuthorizationAlreadyUsed(from, nonce);

        bytes32 structHash = keccak256(
            abi.encode(TRANSFER_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce)
        );
        if (ECDSA.recover(_hashTypedDataV4(structHash), v, r, s) != from) revert InvalidAuthorization();

        _authorizationStates[from][nonce] = true;
        emit AuthorizationUsed(from, nonce);
    }

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal
        virtual
        override(PaymentRules, ReplayRule)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}
