
from fastapi.testclient import TestClient

from agent_m2m import audit, purchase, store
from agent_m2m.api import app
from agent_m2m.payment import buyer_balance
from agent_m2m.provider import DeliveryError
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import replay

client = TestClient(app)


def purchase_input(name: str) -> dict:
    """테스트마다 다른 문장을 써서 같은 문장 규칙이 다른 테스트로 번지지 않게 한다."""
    return {"prompt": f"이 글 요약해 줘 {name}", "budgetUnits": 50_000, "priority": "price"}


def api_body(name: str) -> dict:
    return {
        "prompt": f"이 글 요약해 줘 {name}",
        "budget": "0.05",
        "priority": "price",
        "requestId": f"replay-{name}",
        "userId": f"replay-user-{name}",
    }


def advance_clock(monkeypatch, seconds: int) -> None:
    """시계를 앞으로 돌린다. 이 규칙이 보는 시각만 바꾼다."""
    now = replay._now()
    monkeypatch.setattr(replay, "_now", lambda: now + seconds)


def fail_before_send(request: dict) -> dict:
    """이번 한 번만 송금 전에 실패시킨다."""

    def block(ctx):
        raise audit.AuditBlockedError("test-block", "테스트용 차단")

    audit.BEFORE_PAYMENT_CHECKS.append(block)
    try:
        return run_purchase(request)
    finally:
        audit.BEFORE_PAYMENT_CHECKS.remove(block)


def fail_after_send(monkeypatch) -> None:
    def fail(*args):
        raise DeliveryError("판매창구 확인 실패")

    monkeypatch.setattr(purchase, "verify_payment", fail)


# 같은 결과 중복 구매 (에이전트 반복 루프)


def buy_times(count: int, name: str, user_id: str, priority: str = "price") -> list[str | None]:
    """요청 번호를 바꿔 가며 같은 문장으로 산다. 막힌 건은 규칙 이름, 아니면 None."""
    records = [
        run_purchase({**purchase_input(name), "priority": priority, "requestId": f"{name}-{user_id}-{priority}-{index}", "userId": user_id})
        for index in range(count)
    ]
    return [record.get("blockedRule") for record in records]


def test_같은_문장으로_같은_모델을_창_안에서_횟수만큼_사면_송금_전에_막힌다():
    balance = buyer_balance()["units"]
    rules = buy_times(replay.REPEAT_COUNT, "dup", "dup-user")

    assert rules == [None] * (replay.REPEAT_COUNT - 1) + ["duplicate-purchase"]
    blocks = [alert for alert in store.list_alerts(500) if alert["rule"] == "duplicate-purchase" and alert["userId"] == "dup-user"]
    assert [(alert["blocked"], alert["stage"]) for alert in blocks] == [(True, "before-payment")]
    paid = [record for record in store.list_purchases(500) if record["userId"] == "dup-user" and record["status"] == "SETTLED"]
    assert balance - buyer_balance()["units"] == sum(record["payment"]["amountUnits"] for record in paid)


def test_API_로_보내면_막힌_규칙_이름이_기록에_남는다():
    def send(index: int):
        body = {**api_body("dup-api"), "requestId": f"dup-api-{index}"}
        return client.post("/api/purchase", json=body)

    for index in range(replay.REPEAT_COUNT - 1):
        assert send(index).status_code == 200

    blocked = send(replay.REPEAT_COUNT)

    assert blocked.json()["blockedRule"] == "duplicate-purchase"


def test_막힌_요청_번호는_창이_지난_뒤_다시_쓸_수_있다(monkeypatch):
    buy_times(replay.REPEAT_COUNT - 1, "dup-again", "dup-again-user")
    request = {**purchase_input("dup-again"), "requestId": "dup-again-blocked", "userId": "dup-again-user"}
    assert run_purchase(request)["blockedRule"] == "duplicate-purchase"

    advance_clock(monkeypatch, replay.REPEAT_WINDOW_SECONDS)
    assert run_purchase(request)["status"] == "SETTLED"


def test_송금_전에_실패한_구매는_횟수에서_뺀다():
    for index in range(replay.REPEAT_COUNT):
        request = {**purchase_input("dup-failed"), "requestId": f"dup-failed-{index}", "userId": "dup-failed-user"}
        assert fail_before_send(request)["status"] == "FAILED"

    assert buy_times(replay.REPEAT_COUNT - 1, "dup-failed", "dup-failed-user") == [None] * (replay.REPEAT_COUNT - 1)


def test_사용자와_문장은_따로_센다():
    rules = [
        *buy_times(replay.REPEAT_COUNT - 1, "dup-apart", "dup-apart-a"),
        *buy_times(1, "dup-apart", "dup-apart-b"),
        *buy_times(1, "dup-apart-other", "dup-apart-a"),
    ]
    assert "duplicate-purchase" not in rules


# 체인 규칙과 함께


def test_짧은_시간_결제_횟수는_체인이_막아_송금_전_실패로_남는다():
    records = [
        run_purchase({**purchase_input(f"rate-{index}"), "requestId": f"replay-rate-{index}", "userId": "replay-user-rate"})
        for index in range(6)
    ]
    assert records[-2]["status"] == "SETTLED"
    assert (records[-1]["status"], records[-1]["failureStage"]) == ("FAILED", "before-send")


def test_같은_요청_번호로_다시_보내면_체인이_막아_돈은_한_번만_나간다():
    """서버는 요청 번호를 기억하지 않는다. 다시 보내면 새로 흥정하지만 체인이 같은 요청 번호의 합의를 한 번만 받는다."""
    request = {**purchase_input("chain"), "requestId": "replay-chain", "userId": "replay-user-chain"}
    first = run_purchase(request)
    assert first["status"] == "SETTLED"
    balance = buyer_balance()["units"]

    again = run_purchase(request)

    assert (again["status"], again["failureStage"]) == ("FAILED", "before-send")
    assert buyer_balance()["units"] == balance


def test_송금_후에_실패한_요청_번호를_다시_보내도_체인이_막는다(monkeypatch):
    request = {**purchase_input("chain-after"), "requestId": "replay-chain-after", "userId": "replay-user-chain-after"}
    fail_after_send(monkeypatch)
    first = run_purchase(request)
    assert (first["status"], first["failureStage"]) == ("FAILED", "after-send")
    balance = buyer_balance()["units"]
    monkeypatch.undo()

    again = run_purchase(request)

    assert (again["status"], again["failureStage"]) == ("FAILED", "before-send")
    assert buyer_balance()["units"] == balance
