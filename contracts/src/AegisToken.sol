// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";

import {PaymentRules} from "./rules/PaymentRules.sol";
import {LimitRule} from "./rules/LimitRule.sol";
import {ReplayRule} from "./rules/ReplayRule.sol";

/// @title AEGIS 토큰
/// @notice 구매 에이전트가 모델 값을 치르는 ERC-20. 소수점 6자리.
/// 구매 결제는 x402(exact, ERC-3009) 로 한다. 두 단계다.
///   1. 운영자가 openDeal 로 흥정 합의와 송금 직전 감사 결과를 체인에 올린다. 감사가 막았으면 합의는 열리지 않는다.
///   2. 구매자가 transferWithAuthorization 에 서명하고(nonce = 합의 해시), x402 정산 서버가 그 서명을 체인에 올린다.
///      토큰은 nonce 로 열린 합의를 찾아, 감사를 통과했고 보내는 사람·받는 사람·금액이 합의와 같을 때만 송금한다.
/// 그래서 감사 기록이 없거나 막힌 결제, 합의와 다른 결제는 체인이 거절한다. 송금 뒤 감사 결과는 recordAudit 로 남긴다.
/// 감사 규칙은 contracts/src/rules/ 에 파일로 따로 두고, 아래 상속 목록과 _checkPayment 의 override 목록에 이름만 더한다.
contract AegisToken is ERC20, EIP712, Ownable, PaymentRules, LimitRule, ReplayRule {
    /// @notice ERC-3009 서명 내용. 구매자는 이 내용에 서명만 하고, 거래는 x402 정산 서버가 보낸다(가스비도 정산 서버가 낸다).
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
    /// 그래서 구매자 서명은 합의 내용 전체에 대한 동의가 된다.
    bytes32 public constant DEAL_TYPEHASH = keccak256(
        "Deal(bytes32 requestId,address buyer,address seller,bytes32 modelKey,uint256 askUnits,uint256 agreedUnits,bytes32 transcriptHash,bytes32 decisionHash)"
    );

    /// @notice 감사 단계. 송금 직전(openDeal 이 남김)과 송금 뒤(recordAudit 이 남김).
    uint8 public constant STAGE_BEFORE_SEND = 1;
    uint8 public constant STAGE_AFTER_SEND = 2;
    /// @notice 감사 결과. 통과·알림(결제는 진행)·막음.
    uint8 public constant RESULT_PASS = 1;
    uint8 public constant RESULT_ALERT = 2;
    uint8 public constant RESULT_BLOCK = 3;
    /// @notice 합의 상태.
    uint8 public constant DEAL_OPEN = 1;
    uint8 public constant DEAL_SETTLED = 2;

    /// @notice 감사 한 번의 결과. 감사 보고서 원문은 서버 DB 에 두고 해시만 담는다.
    struct AuditRecord {
        uint8 result;
        bytes32 reportHash;
    }

    /// @notice 체인에 저장된 합의. 요청 번호로 누구나 읽는다.
    mapping(bytes32 requestId => Deal) public deals;
    /// @notice 합의 상태(0 없음, DEAL_OPEN, DEAL_SETTLED).
    mapping(bytes32 requestId => uint8) public dealStatus;
    /// @notice 열린 합의를 합의 해시로 찾는다. x402 결제의 nonce 가 합의 해시다.
    mapping(bytes32 dealHash => bytes32 requestId) public dealByHash;
    /// @notice 단계별 감사 결과. 같은 요청 번호의 이전 기록은 AuditRecorded 이벤트로 남는다.
    mapping(bytes32 requestId => mapping(uint8 stage => AuditRecord)) public audits;

    /// @notice 구매 결제 한 건. 판매창구는 이 이벤트로 요청 번호·수신자·금액을 대조한다.
    event Paid(bytes32 indexed requestId, address indexed from, address indexed to, uint256 amount);
    /// @notice ERC-3009: 서명 한 장이 쓰였다. nonce 는 합의 해시다.
    event AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce);
    /// @notice 운영자가 합의를 열었다. 이 합의 해시를 nonce 로 서명한 결제만 받는다.
    event DealOpened(bytes32 indexed requestId, address indexed buyer, address indexed seller, bytes32 dealHash);
    /// @notice 감사 결과가 체인에 남았다. rules 는 걸린 규칙 이름(쉼표로 구분, 통과면 빈 문자열)이다.
    event AuditRecorded(bytes32 indexed requestId, uint8 indexed stage, uint8 result, string rules, bytes32 reportHash);
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
    error NoOpenDeal(bytes32 dealHash);
    error DealMismatch(bytes32 requestId);
    error DealNotSettled(bytes32 requestId);
    error InvalidAudit(uint8 stage, uint8 result);
    error AuditAlreadyRecorded(bytes32 requestId, uint8 stage);

    mapping(address authorizer => mapping(bytes32 nonce => bool used)) private _authorizationStates;

    constructor(address initialOwner) ERC20("AEGIS", "AEGIS") EIP712("AEGIS", "1") Ownable(initialOwner) {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice 운영자만 새로 발급한다.
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /// @notice x402 가 토큰 버전을 읽는다. EIP712("AEGIS", "1") 과 같다.
    function version() external pure returns (string memory) {
        return "1";
    }

    /// @notice 운영자가 흥정 합의와 송금 직전 감사 결과를 올린다. 막음(RESULT_BLOCK)이면 합의는 열지 않고 감사 기록만 남긴다.
    /// 아직 결제되지 않은 요청 번호는 다시 열 수 있다(송금 전에 실패한 구매를 다시 보낼 때). 이전 기록은 이벤트에 남는다.
    function openDeal(Deal calldata deal, uint8 result, string calldata rules, bytes32 reportHash) external onlyOwner {
        if (result < RESULT_PASS || result > RESULT_BLOCK) revert InvalidAudit(STAGE_BEFORE_SEND, result);
        bytes32 requestId = deal.requestId;
        if (dealStatus[requestId] == DEAL_SETTLED) revert DealAlreadySettled(requestId);
        if (dealStatus[requestId] == DEAL_OPEN) {
            delete dealByHash[hashDeal(deals[requestId])];
            delete dealStatus[requestId];
        }

        audits[requestId][STAGE_BEFORE_SEND] = AuditRecord(result, reportHash);
        emit AuditRecorded(requestId, STAGE_BEFORE_SEND, result, rules, reportHash);
        if (result == RESULT_BLOCK) return;

        bytes32 dealHash = hashDeal(deal);
        deals[requestId] = deal;
        dealStatus[requestId] = DEAL_OPEN;
        dealByHash[dealHash] = requestId;
        emit DealOpened(requestId, deal.buyer, deal.seller, dealHash);
    }

    /// @notice 운영자가 송금 뒤 감사 결과를 올린다. 결제된 합의에 한 번만 남긴다.
    function recordAudit(bytes32 requestId, uint8 result, string calldata rules, bytes32 reportHash) external onlyOwner {
        if (result < RESULT_PASS || result > RESULT_BLOCK) revert InvalidAudit(STAGE_AFTER_SEND, result);
        if (dealStatus[requestId] != DEAL_SETTLED) revert DealNotSettled(requestId);
        if (audits[requestId][STAGE_AFTER_SEND].result != 0) revert AuditAlreadyRecorded(requestId, STAGE_AFTER_SEND);
        audits[requestId][STAGE_AFTER_SEND] = AuditRecord(result, reportHash);
        emit AuditRecorded(requestId, STAGE_AFTER_SEND, result, rules, reportHash);
    }

    /// @notice x402(exact) 결제. 구매자가 서명한 내용 그대로 누구든(x402 정산 서버) 대신 보낼 수 있다.
    /// nonce 는 합의 해시다. 열린 합의가 없거나(감사 기록이 없거나 막힘) 보내는 사람·받는 사람·금액이 합의와 다르면 거절한다.
    /// 체인 감사 규칙을 모두 통과하면 합의대로 송금하고 합의를 결제됨으로 바꾼다.
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
        bytes32 requestId = dealByHash[nonce];
        if (requestId == bytes32(0) || dealStatus[requestId] != DEAL_OPEN) revert NoOpenDeal(nonce);
        Deal memory deal = deals[requestId];
        if (deal.buyer != from || deal.seller != to || deal.agreedUnits != value) revert DealMismatch(requestId);

        _checkPayment(from, to, value, requestId);
        dealStatus[requestId] = DEAL_SETTLED;
        delete dealByHash[nonce];
        _transfer(from, to, value);
        emit Paid(requestId, from, to, value);
        emit DealSettled(requestId, from, to, nonce, deal.askUnits, value, deal.transcriptHash);
    }

    /// @notice 합의 내용의 해시. 서버도 같은 방식으로 계산해 구매자 서명의 nonce 로 쓴다.
    function hashDeal(Deal memory deal) public pure returns (bytes32) {
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

    /// @notice ERC-3009: 이 서명(nonce = 합의 해시)이 이미 쓰였는지. x402 정산 서버가 확인 단계에서 읽는다.
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
        override(PaymentRules, LimitRule, ReplayRule)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}
