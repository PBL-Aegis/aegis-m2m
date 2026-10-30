import re

import pytest

from agent_m2m import audit, purchase, store
from agent_m2m.provider import DeliveryError
from agent_m2m.purchase import run_purchase

INPUT = {"prompt": "이 글 요약해 줘", "budgetUnits": 50_000, "priority": "price"}
TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def empty_rules():
    """이 파일은 감사 흐름 자체를 시험하므로, 등록된 실제 규칙을 잠시 비우고 테스트마다 시험용 규칙만 넣는다."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def test_성공하면_요청_번호_사용자와_함께_SETTLED_로_남는다():
    record = run_purchase({**INPUT, "requestId": "req-1", "userId": "user-1"})
    assert record["status"] == "SETTLED"
    saved = store.get_purchase(record["id"])
    assert saved["status"] == "SETTLED"
    assert saved["requestId"] == "req-1"
    assert saved["userId"] == "user-1"
    assert TX_HASH.match(saved["payment"]["txHash"])
    assert saved["updatedAt"] == record["updatedAt"]


def test_요청_번호가_없으면_서버가_만들고_사용자는_None_이다():
    record = run_purchase(INPUT)
    assert re.fullmatch(r"[0-9a-f-]{36}", record["requestId"])
    assert record["userId"] is None


def test_감사_규칙이_막으면_송금하지_않고_송금_전_실패로_남는다():
    def check(ctx):
        ctx.alert("test-rule", "알림만 남긴다")
        raise audit.AuditBlockedError("test-rule", "테스트 규칙이 막았습니다")

    audit.BEFORE_PAYMENT_CHECKS.append(check)
    record = run_purchase({**INPUT, "userId": "user-2"})
    saved = store.get_purchase(record["id"])
    assert saved["status"] == "FAILED"
    assert saved["failureStage"] == "before-send"
    assert saved["failureReason"] == "테스트 규칙이 막았습니다"
    assert saved["payment"] is None
    alert = next(item for item in store.list_alerts() if item["purchaseId"] == record["id"])
    assert alert["rule"] == "test-rule" and alert["userId"] == "user-2"


def test_송금_뒤_확인에서_실패하면_거래번호를_지우지_않고_송금_후_실패로_남는다(monkeypatch):
    def fail(*args):
        raise DeliveryError("확인 실패")

    monkeypatch.setattr(purchase, "verify_payment", fail)
    record = run_purchase(INPUT)
    saved = store.get_purchase(record["id"])
    assert saved["status"] == "FAILED"
    assert saved["failureStage"] == "after-send"
    assert TX_HASH.match(saved["payment"]["txHash"])


def test_요청_직후_규칙이_이전_기록을_돌려주면_새로_처리하지_않고_그_기록을_돌려준다():
    first = run_purchase({**INPUT, "requestId": "req-again"})
    audit.ON_REQUEST_CHECKS.append(
        lambda ctx: store.get_purchase(first["id"]) if ctx.request["requestId"] == "req-again" else None
    )
    before = len(store.list_purchases(500))
    again = run_purchase({**INPUT, "requestId": "req-again"})
    assert again["id"] == first["id"]
    assert len(store.list_purchases(500)) == before


def test_요청_직후_규칙이_막으면_기록_없이_AuditBlockedError_가_나간다():
    def check(ctx):
        raise audit.AuditBlockedError("test-request", "처리 중입니다")

    audit.ON_REQUEST_CHECKS.append(check)
    before = len(store.list_purchases(500))
    with pytest.raises(audit.AuditBlockedError):
        run_purchase(INPUT)
    assert len(store.list_purchases(500)) == before


def test_결제_후_규칙은_확정된_기록을_받고_실패해도_결과를_바꾸지_않고_알림만_남긴다():
    seen = []

    def block(ctx):
        raise audit.AuditBlockedError("test-rule", "막음")

    def broken(ctx, record):
        raise RuntimeError("되돌리기 실패")

    audit.BEFORE_PAYMENT_CHECKS.append(block)
    audit.AFTER_PAYMENT_CHECKS.append(lambda ctx, record: seen.append(f"{record['status']}:{record.get('failureStage')}"))
    audit.AFTER_PAYMENT_CHECKS.append(broken)
    record = run_purchase(INPUT)
    assert seen == ["FAILED:before-send"]
    assert store.get_purchase(record["id"])["status"] == "FAILED"
    alert = next(item for item in store.list_alerts() if item["purchaseId"] == record["id"] and item["rule"] == "after-payment")
    assert "되돌리기 실패" in alert["message"]


def test_송금_직전_규칙이_막으면_단계_요청_번호와_함께_차단_알림이_자동으로_남는다():
    def check(ctx):
        raise audit.AuditBlockedError("limit-test", "한도 초과")

    audit.BEFORE_PAYMENT_CHECKS.append(check)
    record = run_purchase({**INPUT, "requestId": "req-block", "userId": "user-b"})
    alerts = store.list_alerts_for_purchase(record["id"])
    assert len(alerts) == 1
    assert {key: alerts[0][key] for key in ("rule", "message", "blocked", "stage", "requestId", "userId")} == {
        "rule": "limit-test",
        "message": "한도 초과",
        "blocked": True,
        "stage": "before-payment",
        "requestId": "req-block",
        "userId": "user-b",
    }
    assert record["id"] in store.existing_purchase_ids([record["id"], "no-such-id"])


def test_요청_직후_규칙이_막으면_구매_기록_없이_차단_알림만_남는다():
    def check(ctx):
        raise audit.AuditBlockedError("replay-test", "처리 중인 요청")

    audit.ON_REQUEST_CHECKS.append(check)
    before = store.count_alerts()
    with pytest.raises(audit.AuditBlockedError):
        run_purchase({**INPUT, "requestId": "req-early"})
    alert = next(item for item in store.list_alerts() if item.get("requestId") == "req-early")
    assert (alert["rule"], alert["blocked"], alert["stage"]) == ("replay-test", True, "on-request")
    assert store.existing_purchase_ids([alert["purchaseId"]]) == set()
    after = store.count_alerts()
    assert after["blocked"] == before["blocked"] + 1
    assert after["warnings"] == before["warnings"]


def test_ctx_alert_로_남긴_알림은_막지_않는_경고로_센다():
    audit.BEFORE_PAYMENT_CHECKS.append(lambda ctx: ctx.alert("near-limit", "한도의 80% 이상"))
    before = store.count_alerts()
    record = run_purchase(INPUT)
    assert record["status"] == "SETTLED"
    alerts = store.list_alerts_for_purchase(record["id"])
    assert [(item["rule"], item["blocked"], item["stage"]) for item in alerts] == [("near-limit", False, "before-payment")]
    assert store.count_alerts()["warnings"] == before["warnings"] + 1
