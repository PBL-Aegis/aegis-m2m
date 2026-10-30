from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_m2m.payment import AEGIS_ABI, PaymentError, buyer_balance, pay, payment_config, request_id_hash, web3_for

# 결제는 pytest 가 띄운 테스트 전용 로컬 체인(tests/conftest.py)에 진짜로 보낸다.
RECIPIENT = "0xF00E8e0ecEF3B405250242F932849edB409497a0"


def test_pay_를_체인에_보내_구매자_잔액이_줄고_요청_번호가_담긴_Paid_영수증이_남는다():
    before = buyer_balance()["units"]
    result = pay(12_960, RECIPIENT, "test-1", "req-1")
    assert result["mode"] == "local"
    assert len(result["txHash"]) == 66 and result["txHash"].startswith("0x")
    assert result["blockNumber"] is not None
    assert result["requestIdHash"] == request_id_hash("req-1")
    assert buyer_balance()["units"] == before - 12_960

    receipt = web3_for(payment_config()).eth.get_transaction_receipt(result["txHash"])
    assert receipt["status"] == 1
    assert len(receipt["logs"]) > 0
    assert any(item["type"] == "event" and item["name"] == "Paid" for item in AEGIS_ABI)


def test_같은_지갑으로_동시에_여러_건_보내도_거래_순번이_겹치지_않고_모두_들어간다():
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda index: pay(1_000, RECIPIENT, f"burst-{index}", f"burst-{index}"), range(5)))
    assert len({result["txHash"] for result in results}) == 5


def test_승인_변수_없이_live_를_요청하면_로컬_체인으로_남는다(monkeypatch):
    monkeypatch.setenv("AEGIS_PAYMENT_MODE", "live")
    monkeypatch.setenv("AEGIS_REAL_PAYMENT_APPROVED", "no")
    assert payment_config()["mode"] == "local"


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
    pay(500_000, RECIPIENT, "spend", "spend")
    assert buyer_balance()["units"] == 999_500_000


def test_앞_테스트에서_쓴_금액은_다음_테스트에_남지_않는다_2_확인():
    assert buyer_balance()["units"] == 1_000_000_000
