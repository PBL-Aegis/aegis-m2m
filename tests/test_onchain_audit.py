"""감사 결과가 체인에 남는지, x402 왕복이 합의대로만 결제하는지, 감사 기록 없는 결제를 체인이 거절하는지 본다."""

import copy
import json
from pathlib import Path

import pytest
from web3 import Web3

from agent_m2m import audit, payment, provider, purchase, store, x402_payment
from agent_m2m.deal import content_hash
from agent_m2m.payment import buyer_balance, payment_config, web3_for
from agent_m2m.provider import DeliveryError, verify_audit
from agent_m2m.purchase import run_purchase

INPUT = {"prompt": "이 글 싸게 요약해 줘", "budgetUnits": 10_000_000}
ARTIFACT = Path(__file__).resolve().parent.parent / "contracts" / "out" / "AegisToken.sol" / "AegisToken.json"


@pytest.fixture(autouse=True)
def empty_rules():
    """규칙은 테스트마다 직접 넣는다."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def token():
    config = payment_config()
    abi = json.loads(ARTIFACT.read_text())["abi"]
    return web3_for(config).eth.contract(address=config["tokenAddress"], abi=abi)


def on_chain(record: dict, stage: int) -> tuple[int, str]:
    result, report_hash = token().functions.audits(Web3.to_bytes(hexstr=record["decision"]["deal"]["requestId"]), stage).call()
    return result, Web3.to_hex(report_hash)


def deal_status(record: dict) -> int:
    return token().functions.dealStatus(Web3.to_bytes(hexstr=record["decision"]["deal"]["requestId"])).call()


def test_송금_전후_감사_보고서의_해시가_체인에_남고_DB_보고서와_같다():
    audit.AFTER_PAYMENT_CHECKS.append(lambda ctx, record: None)
    record = run_purchase({**INPUT, "requestId": "req-audit"})

    assert record["status"] == "SETTLED"
    before, after = record["audit"]["beforeSend"], record["audit"]["afterSend"]
    assert before["report"]["result"] == "pass" and before["txHash"]
    assert content_hash(before["report"]) == before["hash"]
    assert on_chain(record, 1) == (1, before["hash"])
    assert after["report"]["stage"] == "after-send" and after["txHash"]
    assert on_chain(record, 2) == (1, after["hash"])
    assert deal_status(record) == 2


def test_알림만_남긴_규칙은_체인에_알림_결과와_규칙_이름으로_남고_결제는_된다():
    audit.BEFORE_PAYMENT_CHECKS.append(lambda ctx: ctx.alert("test-alert", "알림만 남긴다"))
    record = run_purchase({**INPUT, "requestId": "req-alert"})

    assert record["status"] == "SETTLED"
    before = record["audit"]["beforeSend"]
    assert [finding["rule"] for finding in before["report"]["findings"]] == ["test-alert"]
    assert on_chain(record, 1) == (2, before["hash"])
    receipt = web3_for(payment_config()).eth.get_transaction_receipt(before["txHash"])
    [event] = token().events.AuditRecorded().process_receipt(receipt)
    assert event["args"]["rules"] == "test-alert" and event["args"]["result"] == 2


def test_막힌_구매는_체인에_막음_기록만_남고_합의는_열리지_않는다():
    def block(ctx):
        raise audit.AuditBlockedError("test-block", "테스트 규칙이 막았습니다")

    audit.BEFORE_PAYMENT_CHECKS.append(block)
    balance = buyer_balance()["units"]
    record = run_purchase({**INPUT, "requestId": "req-blocked"})

    assert (record["status"], record["failureStage"], record["blockedRule"]) == ("FAILED", "before-send", "test-block")
    assert record["payment"] is None and buyer_balance()["units"] == balance
    assert on_chain(record, 1) == (3, record["audit"]["beforeSend"]["hash"])
    assert deal_status(record) == 0
    assert "afterSend" not in record["audit"]


def test_DB_의_감사_보고서를_고치면_체인의_해시와_달라_판매창구가_알아챈다():
    audit.BEFORE_PAYMENT_CHECKS.append(lambda ctx: ctx.alert("test-alert", "알림"))
    record = run_purchase({**INPUT, "requestId": "req-audit-tamper"})
    saved = store.get_purchase(record["id"])
    request_hash = saved["decision"]["deal"]["requestId"]
    verify_audit(saved["audit"], request_hash)

    edited = copy.deepcopy(saved["audit"])
    edited["beforeSend"]["report"]["findings"] = []
    with pytest.raises(DeliveryError, match="해시"):
        verify_audit(edited, request_hash)

    edited["beforeSend"]["hash"] = content_hash(edited["beforeSend"]["report"])
    with pytest.raises(DeliveryError, match="체인"):
        verify_audit(edited, request_hash)


def test_판매창구는_결제_없이_오면_402_와_합의대로의_결제_조건을_준다(monkeypatch):
    seen = {}
    original = purchase._pay_with_x402

    def peek(purchase_id, deal):
        with purchase.provider_client() as client:
            seen["response"] = client.get(f"/api/provider/purchases/{purchase_id}")
        seen["deal"] = deal
        return original(purchase_id, deal)

    monkeypatch.setattr(purchase, "_pay_with_x402", peek)
    record = run_purchase({**INPUT, "requestId": "req-402"})

    response, deal = seen["response"], seen["deal"]
    assert record["status"] == "SETTLED"
    assert response.status_code == 402 and x402_payment.PAYMENT_REQUIRED in response.headers
    [accepted] = response.json()["accepts"]
    assert accepted["amount"] == str(deal["agreedUnits"])
    assert accepted["payTo"] == Web3.to_checksum_address(deal["seller"])
    assert accepted["asset"] == payment_config()["tokenAddress"]
    assert accepted["extra"]["assetTransferMethod"] == "eip3009"


def test_판매창구가_합의와_다른_금액을_요구하면_구매자는_서명하지_않는다(monkeypatch):
    original = x402_payment.requirements
    monkeypatch.setattr(x402_payment, "requirements", lambda amount, pay_to: original(amount + 1, pay_to))
    balance = buyer_balance()["units"]

    record = run_purchase({**INPUT, "requestId": "req-greedy"})

    assert (record["status"], record["failureStage"]) == ("FAILED", "before-send")
    assert "서명하지 않았습니다" in record["failureReason"]
    assert record["payment"] is None and buyer_balance()["units"] == balance
    assert deal_status(record) == 1  # 합의는 열렸지만 결제되지 않았다


def test_체인에_감사_기록과_합의가_없으면_x402_결제가_거절된다(monkeypatch):
    # 서버가 감사를 건너뛰고(체인에 합의를 열지 않고) 결제하려는 경우.
    monkeypatch.setattr(purchase, "open_deal", lambda deal, summary: "0x" + "00" * 32)
    balance = buyer_balance()["units"]

    record = run_purchase({**INPUT, "requestId": "req-skip-audit"})

    assert (record["status"], record["failureStage"]) == ("FAILED", "before-send")
    assert record["payment"] is None and buyer_balance()["units"] == balance
    assert on_chain(record, 1) == (0, "0x" + "00" * 32)


def test_같은_요청_번호로_다시_보내도_체인이_한_번만_결제한다():
    first = run_purchase({**INPUT, "requestId": "req-once"})
    balance = buyer_balance()["units"]
    again = run_purchase({**INPUT, "requestId": "req-once"})

    assert first["status"] == "SETTLED"
    assert (again["status"], again["failureStage"]) == ("FAILED", "before-send")
    assert "DealAlreadySettled" in again["failureReason"] or "합의와 감사 결과를 올리지 못했습니다" in again["failureReason"]
    assert buyer_balance()["units"] == balance


def test_운영자_거래는_가스_추정치에_여유를_둔다(monkeypatch):
    sent = []
    original = payment._send

    def spy(w3, function, sender, chain_id):
        estimate = function.estimate_gas({"from": sender.address})
        receipt, tx_hash = original(w3, function, sender, chain_id)
        sent.append((estimate, w3.eth.get_transaction(tx_hash)["gas"]))
        return receipt, tx_hash

    monkeypatch.setattr(payment, "_send", spy)
    run_purchase({**INPUT, "requestId": "req-gas"})
    assert sent and all(gas >= estimate * (1 + payment.GAS_MARGIN) - 1 for estimate, gas in sent)
