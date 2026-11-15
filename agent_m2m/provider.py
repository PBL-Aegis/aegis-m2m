"""
판매창구. 파는 쪽 역할을 흉내 내는 코드다. x402 로 돈을 받고(deliver, HTTP 402 왕복), 받았는지 스스로 확인한 뒤에만 결과를 준다.

  결제 없이 오면        402 와 결제 조건(합의가, 판매자 주소, AEGIS). 조건은 DB 의 합의로 정한다.
  서명을 담아 오면      x402 정산 서버로 확인·정산(x402_payment.py). 토큰은 열린 합의(감사 통과)와 같은 결제만 받는다.
  정산이 끝나면        구매 쪽이 "보냈다"고 말한 것을 믿지 않고 체인의 기록을 직접 읽어 대조한다.
                       Paid(요청 번호·수신자·금액), DealSettled(합의 해시·대화 해시), 체인의 송금 직전 감사 해시를
                       DB 의 기록으로 다시 계산한 값과 비교한다. 다르면 결과를 주지 않는다.
모델 출력 자체는 Mock이다. 실제 OpenAI·Anthropic·Google API를 부르지 않는다.
"""

from typing import Any

from eth_abi import decode
from web3 import Web3

from x402.http import decode_payment_signature_header, encode_payment_required_header, encode_payment_response_header
from x402.schemas import PaymentPayload, PaymentRequired, ResourceInfo

from agent_m2m import store, x402_payment
from agent_m2m.deal import content_hash, hash_deal, transcript_hash
from agent_m2m.domain import PaymentResult
from agent_m2m.payment import (
    LOCAL_FACILITATOR_INDEX,
    STAGE_BEFORE_SEND,
    anvil_account,
    chain_audit,
    payment_config,
    request_id_hash,
    web3_for,
)

# Paid(bytes32 indexed requestId, address indexed from, address indexed to, uint256 amount)
PAID_TOPIC = Web3.to_hex(Web3.keccak(text="Paid(bytes32,address,address,uint256)"))
# DealSettled(bytes32 indexed requestId, address indexed buyer, address indexed seller,
#             bytes32 dealHash, uint256 askUnits, uint256 agreedUnits, bytes32 transcriptHash)
DEAL_SETTLED_TOPIC = Web3.to_hex(Web3.keccak(text="DealSettled(bytes32,address,address,bytes32,uint256,uint256,bytes32)"))


class DeliveryError(Exception):
    pass


def get_receipt(tx_hash: str) -> dict[str, Any]:
    """체인에서 거래 영수증을 읽는다. 테스트는 이 함수를 바꿔 끼워 미리 만든 영수증을 준다."""
    return dict(web3_for(payment_config()).eth.get_transaction_receipt(tx_hash))


def _hex(value: Any) -> str:
    return value.lower() if isinstance(value, str) else Web3.to_hex(value)


def _topic_address(topic: Any) -> str:
    return Web3.to_checksum_address("0x" + _hex(topic)[-40:])


def _is_paid(log: dict[str, Any], token: str, expected_request: str, expected_to: str, amount: int) -> bool:
    try:
        if Web3.to_checksum_address(log["address"]) != token:
            return False
        topics = [_hex(topic) for topic in log["topics"]]
        if len(topics) != 4 or topics[0] != PAID_TOPIC:
            return False
        data = log["data"]
        (paid_amount,) = decode(["uint256"], bytes.fromhex(data[2:]) if isinstance(data, str) else bytes(data))
        return topics[1] == expected_request and _topic_address(topics[3]) == expected_to and paid_amount == amount
    except Exception:  # noqa: BLE001 — 모양이 다른 기록은 이 결제가 아니다.
        return False


def verify_payment(payment: PaymentResult, winner: dict[str, Any], request_id: str) -> None:
    """체인에 남은 전송 기록이 이 구매의 조건과 같은지 확인한다."""
    receipt = get_receipt(payment["txHash"])
    if receipt["status"] not in (1, "success"):
        raise DeliveryError("체인에서 실패한 거래입니다")

    token = Web3.to_checksum_address(payment["tokenAddress"])
    expected_to = Web3.to_checksum_address(winner["recipient"])
    expected_request = request_id_hash(request_id)
    if not any(_is_paid(log, token, expected_request, expected_to, winner["amountUnits"]) for log in receipt["logs"]):
        raise DeliveryError("이 거래에는 이 요청 번호로 약속한 수신자에게 약속한 금액을 보낸 기록이 없습니다")


def _settled_deal(log: dict[str, Any], token: str) -> dict[str, Any] | None:
    """DealSettled 기록이면 그 내용, 아니면 None."""
    try:
        if Web3.to_checksum_address(log["address"]) != token:
            return None
        topics = [_hex(topic) for topic in log["topics"]]
        if len(topics) != 4 or topics[0] != DEAL_SETTLED_TOPIC:
            return None
        data = log["data"]
        deal_hash, ask, agreed, transcript = decode(
            ["bytes32", "uint256", "uint256", "bytes32"], bytes.fromhex(data[2:]) if isinstance(data, str) else bytes(data)
        )
        return {
            "requestId": topics[1],
            "buyer": _topic_address(topics[2]),
            "seller": _topic_address(topics[3]),
            "dealHash": Web3.to_hex(deal_hash),
            "askUnits": ask,
            "agreedUnits": agreed,
            "transcriptHash": Web3.to_hex(transcript),
        }
    except Exception:  # noqa: BLE001 — 모양이 다른 기록은 이 합의가 아니다.
        return None


def verify_deal(payment: PaymentResult, decision: dict[str, Any]) -> None:
    """체인에 저장된 합의가 DB 기록과 같은지 확인한다. 합의 해시와 대화 해시를 DB 의 기록으로 다시 계산해 대조한다."""
    deal = decision["deal"]
    if transcript_hash(decision["negotiation"]) != deal["transcriptHash"]:
        raise DeliveryError("DB 의 흥정 대화가 합의에 남긴 해시와 다릅니다")
    receipt = get_receipt(payment["txHash"])
    token = Web3.to_checksum_address(payment["tokenAddress"])
    expected = {
        "requestId": deal["requestId"].lower(),
        "buyer": Web3.to_checksum_address(deal["buyer"]),
        "seller": Web3.to_checksum_address(deal["seller"]),
        "dealHash": hash_deal(deal),
        "askUnits": deal["askUnits"],
        "agreedUnits": deal["agreedUnits"],
        "transcriptHash": deal["transcriptHash"].lower(),
    }
    if not any(_settled_deal(log, token) == expected for log in receipt["logs"]):
        raise DeliveryError("이 거래에는 DB 의 합의와 같은 DealSettled 기록이 없습니다")


def verify_audit(audit: dict[str, Any] | None, request_hash: str) -> None:
    """DB 의 송금 직전 감사 보고서가 체인에 남은 해시와 같고, 막음이 아닌지 확인한다."""
    before = (audit or {}).get("beforeSend")
    if not before:
        raise DeliveryError("DB 에 송금 직전 감사 기록이 없습니다")
    if content_hash(before["report"]) != before["hash"]:
        raise DeliveryError("DB 의 감사 보고서가 남겨 둔 해시와 다릅니다")
    on_chain = chain_audit(request_hash, STAGE_BEFORE_SEND)
    if on_chain["hash"].lower() != before["hash"].lower():
        raise DeliveryError("DB 의 감사 보고서가 체인에 남은 감사 해시와 다릅니다")
    if on_chain["result"] == 3:
        raise DeliveryError("체인에 남은 송금 직전 감사 결과가 막음입니다")


def _payment_required(resource: ResourceInfo, required: Any, reason: str) -> tuple[int, dict[str, str], dict[str, Any]]:
    body = PaymentRequired(error=reason, resource=resource, accepts=[required])
    return 402, {x402_payment.PAYMENT_REQUIRED: encode_payment_required_header(body)}, x402_payment.to_wire(body)


def deliver(purchase_id: str, url: str, headers: Any) -> tuple[int, dict[str, str], dict[str, Any]]:
    """판매창구의 결과 주소 하나. (상태 코드, 헤더, 본문). 본문은 200 이면 {payment, resultText}, 아니면 {error, ...}."""
    record = store.get_purchase(purchase_id)
    if record is None:
        return 404, {}, {"error": "없는 구매입니다"}
    if record["status"] != "PROCESSING":
        return 409, {}, {"error": f"결제를 기다리는 구매가 아닙니다: {record['status']}"}
    decision = record["decision"]
    deal, winner = decision["deal"], decision["winner"]
    required = x402_payment.requirements(deal["agreedUnits"], deal["seller"])
    resource = ResourceInfo(url=url, description=f"{winner['displayName']} 응답", mime_type="application/json")

    header = headers.get(x402_payment.PAYMENT_SIGNATURE)
    if header is None:
        return _payment_required(resource, required, f"{x402_payment.PAYMENT_SIGNATURE} 헤더가 필요합니다")
    try:
        payment = decode_payment_signature_header(header)
        if not isinstance(payment, PaymentPayload):
            raise x402_payment.PaymentRejected("x402 v2 결제가 아닙니다")
        x402_payment.verify(payment, required)
        settlement = x402_payment.settle(payment, required)
    except (ValueError, x402_payment.PaymentRejected) as error:
        return _payment_required(resource, required, str(error))

    config = payment_config()
    receipt = get_receipt(settlement.transaction)
    result: PaymentResult = {
        "mode": config["mode"],
        "protocol": "x402",
        "network": settlement.network,
        "txHash": settlement.transaction,
        "from": Web3.to_checksum_address(deal["buyer"]),
        "facilitator": anvil_account(LOCAL_FACILITATOR_INDEX).address,
        "to": Web3.to_checksum_address(deal["seller"]),
        "amountUnits": deal["agreedUnits"],
        "tokenAddress": config["tokenAddress"],
        "chainId": config["chainId"],
        "requestIdHash": deal["requestId"],
        "dealHash": hash_deal(deal),
        "blockNumber": str(receipt["blockNumber"]),
    }
    try:
        verify_payment(result, winner, record["requestId"])
        verify_deal(result, decision)
        verify_audit(record.get("audit"), deal["requestId"])
    except DeliveryError as error:
        # 돈은 이미 나갔다. 거래 기록을 함께 돌려준다.
        return 502, {}, {"error": str(error), "payment": result}
    body = {"payment": result, "resultText": mock_result(record["prompt"], winner)}
    return 200, {x402_payment.PAYMENT_RESPONSE: encode_payment_response_header(settlement)}, body


def mock_result(prompt: str, winner: dict[str, Any]) -> str:
    """결제가 확인된 뒤에만 불린다. 실제 모델 호출 자리를 Mock 문장으로 채운다."""
    head = prompt.strip()[:60]
    return "\n".join(
        [
            f"[Mock 응답 · {winner['displayName']}]",
            f"요청 요약: {head}{'…' if len(prompt.strip()) > 60 else ''}",
            "",
            "이 문장은 실제 모델 출력이 아니라 이 프로젝트가 만든 고정된 mock 예시 응답입니다.",
        ]
    )
