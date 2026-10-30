import pytest
from eth_abi import encode
from web3 import Web3

from agent_m2m import provider
from agent_m2m.payment import request_id_hash
from agent_m2m.provider import PAID_TOPIC, DeliveryError, verify_payment

TOKEN = "0x2222222222222222222222222222222222222222"
BUYER = "0x1111111111111111111111111111111111111111"
RECIPIENT = "0xF00E8e0ecEF3B405250242F932849edB409497a0"

PAYMENT = {"mode": "live", "txHash": "0xabc", "from": BUYER, "to": RECIPIENT, "amountUnits": 9_600, "tokenAddress": TOKEN, "chainId": 84532}
WINNER = {"recipient": RECIPIENT, "amountUnits": 9_600}


def address_topic(address: str) -> str:
    return "0x" + "0" * 24 + address[2:].lower()


def paid_log(request_id: str, amount: int) -> dict:
    return {
        "address": TOKEN,
        "topics": [PAID_TOPIC, request_id_hash(request_id), address_topic(BUYER), address_topic(RECIPIENT)],
        "data": Web3.to_hex(encode(["uint256"], [amount])),
    }


@pytest.fixture
def receipt_logs(monkeypatch):
    """체인 대신 미리 만든 거래 영수증을 돌려준다."""
    logs: list[dict] = []
    monkeypatch.setattr(provider, "get_receipt", lambda tx_hash: {"status": 1, "logs": logs})
    return logs


def test_요청_번호_수신자_금액이_맞는_Paid_기록이_있으면_통과한다(receipt_logs):
    receipt_logs.append(paid_log("req-1", 9_600))
    verify_payment(PAYMENT, WINNER, "req-1")


def test_다른_요청_번호의_결제면_거절한다(receipt_logs):
    receipt_logs.append(paid_log("req-other", 9_600))
    with pytest.raises(DeliveryError):
        verify_payment(PAYMENT, WINNER, "req-1")


def test_금액이_다르면_거절한다(receipt_logs):
    receipt_logs.append(paid_log("req-1", 1))
    with pytest.raises(DeliveryError):
        verify_payment(PAYMENT, WINNER, "req-1")
