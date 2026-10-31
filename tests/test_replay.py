from concurrent.futures import ThreadPoolExecutor
from datetime import UTC

import pytest
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


def blocked_rule(request: dict) -> str | None:
    try:
        run_purchase(request)
        return None
    except audit.AuditBlockedError as error:
        return error.rule


def purchases_of(request_id: str) -> list[dict]:
    return [record for record in store.list_purchases(500) if record["requestId"] == request_id]


def alerts_of(request_id: str) -> list[dict]:
    return [alert for alert in store.list_alerts(500) if alert["requestId"] == request_id]


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


# 같은 요청 번호


def test_성공한_요청_번호를_다시_보내면_같은_기록을_돌려받고_결제는_1번이다():
    request = {**purchase_input("settled"), "requestId": "replay-settled", "userId": "replay-user-settled"}
    first = run_purchase(request)
    assert first["status"] == "SETTLED"
    balance = buyer_balance()["units"]

    again = run_purchase(request)

    assert again["id"] == first["id"]
    assert again["payment"]["txHash"] == first["payment"]["txHash"]
    assert len(purchases_of(request["requestId"])) == 1
    assert buyer_balance()["units"] == balance
    alerts = alerts_of(request["requestId"])
    assert [(alert["rule"], alert["blocked"], alert["stage"]) for alert in alerts] == [("replay", False, "on-request")]


def test_같은_요청_번호가_거의_동시에_두_번_오면_하나만_SETTLED_나머지는_409_다():
    body = api_body("race")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/purchase", json=body), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 409]
    settled = next(response for response in responses if response.status_code == 200)
    blocked = next(response for response in responses if response.status_code == 409)
    assert settled.json()["status"] == "SETTLED"
    assert blocked.json()["rule"] == "replay"
    assert len(purchases_of(body["requestId"])) == 1


def test_막히면_기록_없이_차단_알림만_남는다(monkeypatch):
    fail_after_send(monkeypatch)
    request = {**purchase_input("trace"), "requestId": "replay-trace", "userId": "replay-user-trace"}
    run_purchase(request)

    assert blocked_rule(request) == "replay"

    assert len(purchases_of(request["requestId"])) == 1
    blocks = [alert for alert in alerts_of(request["requestId"]) if alert["blocked"]]
    assert [(alert["rule"], alert["stage"], alert["userId"]) for alert in blocks] == [
        ("replay", "on-request", request["userId"])
    ]
    assert store.existing_purchase_ids([blocks[0]["purchaseId"]]) == set()


def test_송금_전에_실패한_요청_번호는_다시_처리한다():
    request = {**purchase_input("before-send"), "requestId": "replay-before-send", "userId": "replay-user-before-send"}
    failed = fail_before_send(request)
    assert (failed["status"], failed["failureStage"]) == ("FAILED", "before-send")

    again = run_purchase(request)

    assert again["status"] == "SETTLED"
    assert again["id"] != failed["id"]


def test_송금_전에_실패한_요청_번호를_동시에_다시_보내도_하나만_처리한다():
    request = {**purchase_input("retry-race"), "requestId": "replay-retry-race", "userId": "replay-user-retry-race"}
    fail_before_send(request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rules = list(pool.map(lambda _: blocked_rule(request), range(2)))

    assert rules.count("replay") == 1
    assert [record["status"] for record in purchases_of(request["requestId"])].count("SETTLED") == 1


def test_송금_후에_실패한_요청_번호는_409_로_멈춘다(monkeypatch):
    fail_after_send(monkeypatch)
    body = api_body("after-send")
    failed = client.post("/api/purchase", json=body).json()
    assert (failed["status"], failed["failureStage"]) == ("FAILED", "after-send")
    monkeypatch.undo()

    again = client.post("/api/purchase", json=body)

    assert again.status_code == 409
    assert again.json()["rule"] == "replay"
    assert len(purchases_of(body["requestId"])) == 1


def test_기록_없이_끝난_요청_번호는_잠시_처리_중으로_막고_그_뒤에는_다시_받는다(monkeypatch):
    request = {**purchase_input("no-record"), "requestId": "replay-no-record", "userId": "replay-user-no-record"}
    with pytest.raises(Exception):
        run_purchase({**request, "requiredCapabilities": ["없는 기능"]})

    assert blocked_rule(request) == "replay"

    advance_clock(monkeypatch, replay.REQUEST_ID_LEASE_SECONDS)
    assert run_purchase(request)["status"] == "SETTLED"


def test_요청_번호는_보관_기간_뒤_지워지도록_남긴다():
    request = {**purchase_input("ttl"), "requestId": "replay-ttl", "userId": "replay-user-ttl"}
    run_purchase(request)

    collection = store.database()[replay.REQUEST_IDS]
    claim = collection.find_one({"_id": request["requestId"]})
    expires_at = claim["expiresAt"].replace(tzinfo=UTC).timestamp()
    assert round(expires_at - claim["claimedAt"]) == replay.REQUEST_ID_TTL_SECONDS
    indexes = collection.index_information()
    assert any(index.get("expireAfterSeconds") == 0 and index["key"] == [("expiresAt", 1)] for index in indexes.values())


# 같은 문장 반복


def send_times(count: int, name: str, user_id: str) -> list[str | None]:
    return [
        blocked_rule({**purchase_input(name), "requestId": f"{name}-{user_id}-{index}", "userId": user_id})
        for index in range(count)
    ]


def test_요청_번호가_달라도_창_안에서_횟수에_닿으면_repeat_prompt_로_막힌다():
    rules = send_times(replay.REPEAT_COUNT, "repeat", "repeat-user")

    assert rules == [None] * (replay.REPEAT_COUNT - 1) + ["repeat-prompt"]
    blocks = [alert for alert in store.list_alerts(500) if alert["rule"] == "repeat-prompt" and alert["userId"] == "repeat-user"]
    assert [(alert["blocked"], alert["stage"]) for alert in blocks] == [(True, "on-request")]


def test_API_로_보내면_409_와_규칙_이름을_돌려준다():
    def send(index: int):
        body = {**api_body("repeat-api"), "requestId": f"repeat-api-{index}"}
        return client.post("/api/purchase", json=body)

    for index in range(replay.REPEAT_COUNT - 1):
        assert send(index).status_code == 200

    blocked = send(replay.REPEAT_COUNT)

    assert blocked.status_code == 409
    assert blocked.json()["rule"] == "repeat-prompt"


def test_막힌_요청_번호는_창이_지난_뒤_다시_쓸_수_있다(monkeypatch):
    send_times(replay.REPEAT_COUNT - 1, "repeat-again", "repeat-again-user")
    request = {**purchase_input("repeat-again"), "requestId": "repeat-again-blocked", "userId": "repeat-again-user"}
    assert blocked_rule(request) == "repeat-prompt"

    advance_clock(monkeypatch, replay.REPEAT_WINDOW_SECONDS)
    assert run_purchase(request)["status"] == "SETTLED"


def test_사용자와_문장은_따로_센다():
    rules = [
        *send_times(replay.REPEAT_COUNT - 1, "repeat-apart", "repeat-apart-a"),
        *send_times(1, "repeat-apart", "repeat-apart-b"),
        *send_times(1, "repeat-apart-other", "repeat-apart-a"),
    ]
    assert "repeat-prompt" not in rules


def test_같은_요청_번호의_재전송은_같은_문장으로_세지_않는다():
    request = {**purchase_input("repeat-retry"), "requestId": "repeat-retry", "userId": "repeat-retry-user"}
    first = run_purchase(request)
    for _ in range(replay.REPEAT_COUNT):
        assert run_purchase(request)["id"] == first["id"]


# 체인 규칙과 함께


def test_짧은_시간_결제_횟수는_체인이_막아_송금_전_실패로_남는다():
    records = [
        run_purchase({**purchase_input(f"rate-{index}"), "requestId": f"replay-rate-{index}", "userId": "replay-user-rate"})
        for index in range(6)
    ]
    assert records[-2]["status"] == "SETTLED"
    assert (records[-1]["status"], records[-1]["failureStage"]) == ("FAILED", "before-send")


def test_서버_기록이_사라져도_체인이_같은_요청_번호의_결제를_막는다():
    request = {**purchase_input("chain"), "requestId": "replay-chain", "userId": "replay-user-chain"}
    first = run_purchase(request)
    assert first["status"] == "SETTLED"
    balance = buyer_balance()["units"]
    store.database()[replay.REQUEST_IDS].delete_one({"_id": request["requestId"]})

    again = run_purchase(request)

    assert (again["status"], again["failureStage"]) == ("FAILED", "before-send")
    assert buyer_balance()["units"] == balance
