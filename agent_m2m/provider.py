"""
판매창구. 파는 쪽 역할을 흉내 내는 코드다.

돈을 받았는지 스스로 확인한 뒤에만 결과를 준다. 구매 쪽이 "보냈다"고 말한 것을 믿지 않고,
체인의 거래 기록을 직접 읽어 요청 번호·수신자·금액을 대조한다.
모델 출력 자체는 Mock이다. 실제 OpenAI·Anthropic·Google API를 부르지 않는다.
"""

from typing import Any

from eth_abi import decode
from web3 import Web3

from agent_m2m.domain import PaymentResult
from agent_m2m.payment import payment_config, request_id_hash, web3_for

# Paid(bytes32 indexed requestId, address indexed from, address indexed to, uint256 amount)
PAID_TOPIC = Web3.to_hex(Web3.keccak(text="Paid(bytes32,address,address,uint256)"))


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
