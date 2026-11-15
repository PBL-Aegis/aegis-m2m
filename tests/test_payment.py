import pytest

from agent_m2m import audit
from agent_m2m.payment import (
    LOCAL_FACILITATOR_INDEX,
    PaymentError,
    anvil_account,
    buyer_balance,
    payment_config,
    web3_for,
)
from agent_m2m.purchase import run_purchase

# 결제는 pytest 가 띄운 테스트 전용 로컬 체인(tests/conftest.py)에 진짜로 보낸다(x402 왕복 포함).
INPUT = {"prompt": "이 글 싸게 요약해 줘", "budgetUnits": 10_000_000}


@pytest.fixture(autouse=True)
def empty_rules():
    """결제 경로만 시험하므로, 등록된 실제 감사 규칙을 잠시 비운다."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def test_구매자는_서명만_하고_정산_거래와_가스비는_x402_정산_서버가_낸다():
    config = payment_config()
    w3 = web3_for(config)
    buyer, facilitator = config["buyerAddress"], anvil_account(LOCAL_FACILITATOR_INDEX).address
    buyer_eth, facilitator_eth = w3.eth.get_balance(buyer), w3.eth.get_balance(facilitator)
    before = buyer_balance()["units"]

    record = run_purchase({**INPUT, "requestId": "req-gasless"})

    payment = record["payment"]
    assert record["status"] == "SETTLED"
    assert payment["protocol"] == "x402" and payment["network"] == "eip155:31337"
    transaction = w3.eth.get_transaction(payment["txHash"])
    assert transaction["from"] == facilitator == payment["facilitator"]
    assert payment["from"] == buyer
    assert w3.eth.get_balance(buyer) == buyer_eth
    assert w3.eth.get_balance(facilitator) < facilitator_eth
    assert buyer_balance()["units"] == before - payment["amountUnits"]


def test_정산_서버와_운영자는_다른_지갑이다():
    assert anvil_account(LOCAL_FACILITATOR_INDEX).address != anvil_account(0).address


def test_로컬_체인은_anvil_첫_배포_주소와_공개_테스트_구매자를_쓴다():
    config = payment_config()
    assert config["mode"] == "local"
    assert config["chainId"] == 31337
    assert config["rpcUrl"] == "http://127.0.0.1:8546"
    assert config["tokenAddress"] == "0x5FbDB2315678afecb367f032d93F642f64180aa3"
    assert config["buyerAddress"] == "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def test_로컬_체인_주소가_이_컴퓨터가_아니면_거절한다(monkeypatch):
    monkeypatch.setenv("AEGIS_LOCAL_RPC_URL", "http://10.0.0.5:8545")
    with pytest.raises(PaymentError, match=r"127\.0\.0\.1"):
        payment_config()


def test_앞_테스트에서_쓴_금액은_다음_테스트에_남지_않는다_1_쓰기():
    run_purchase({**INPUT, "requestId": "spend"})
    assert buyer_balance()["units"] < 1_000_000_000


def test_앞_테스트에서_쓴_금액은_다음_테스트에_남지_않는다_2_확인():
    assert buyer_balance()["units"] == 1_000_000_000
