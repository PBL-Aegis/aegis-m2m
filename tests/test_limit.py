from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_m2m import audit, store
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import limit
from tests.helpers import increase_chain_time

INPUT = {"prompt": "이 글 요약해 줘", "budgetUnits": 50_000, "priority": "price"}


@pytest.fixture(autouse=True)
def limit_only():
    """다른 규칙은 비우고 limit 규칙만 등록한다(다른 팀원 규칙이 합쳐져도 이 시험은 흔들리지 않게)."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    audit.BEFORE_PAYMENT_CHECKS.append(limit.check_limit)
    audit.AFTER_PAYMENT_CHECKS.append(limit.release_on_failure)
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


@pytest.fixture
def unit():
    """이 요청 1건의 결제 금액(units). 한 번 보내 보고 알아낸다."""
    seen = []
    audit.BEFORE_PAYMENT_CHECKS.append(lambda ctx: seen.append(ctx.decision["winner"]["amountUnits"]))
    run_purchase({**INPUT, "userId": "probe"})
    audit.BEFORE_PAYMENT_CHECKS.pop()
    return seen[0]


def used(user):
    doc = store.database()["limit_daily"].find_one({"_id": f"{user}:{limit._day()}"})
    return doc["used"] if doc else 0


def limit_alerts(user):
    return [a for a in store.list_alerts() if a["rule"] == "limit" and a["userId"] == user]


def alerts_with(user, text):
    return [a for a in limit_alerts(user) if text in a["message"]]


def test_동시에_보내도_하루_상한을_넘는_결제는_막힌다(monkeypatch, unit):
    monkeypatch.setattr(limit, "PER_DAY_UNITS", unit * 3)
    user = "user-concurrent"
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(lambda _: run_purchase({**INPUT, "userId": user}), range(6)))

    assert sum(r["status"] == "SETTLED" for r in records) == 3
    assert sum(r["status"] == "FAILED" and r["failureStage"] == "before-send" for r in records) == 3
    assert used(user) == unit * 3
    assert len(alerts_with(user, "하루 상한 초과")) == 3


def test_1건_상한을_넘으면_바로_막고_합계에_더하지_않는다(monkeypatch, unit):
    monkeypatch.setattr(limit, "PER_PAYMENT_UNITS", unit - 1)
    record = run_purchase({**INPUT, "userId": "user-per-payment"})
    assert record["status"] == "FAILED" and record["failureStage"] == "before-send"
    assert used("user-per-payment") == 0
    assert len(alerts_with("user-per-payment", "1건 상한 초과")) == 1


def test_상한_딱_맞는_금액은_통과한다(monkeypatch, unit):
    monkeypatch.setattr(limit, "PER_PAYMENT_UNITS", unit)
    monkeypatch.setattr(limit, "PER_DAY_UNITS", unit)
    record = run_purchase({**INPUT, "userId": "user-boundary"})
    assert record["status"] == "SETTLED"
    assert used("user-boundary") == unit


def test_사용자마다_따로_센다(monkeypatch, unit):
    monkeypatch.setattr(limit, "PER_DAY_UNITS", unit)
    assert run_purchase({**INPUT, "userId": "user-x"})["status"] == "SETTLED"
    assert run_purchase({**INPUT, "userId": "user-y"})["status"] == "SETTLED"
    assert run_purchase({**INPUT, "userId": "user-x"})["status"] == "FAILED"


def test_다른_규칙이_송금_전에_막으면_예약을_돌려준다(unit):
    def other(ctx):
        raise audit.AuditBlockedError("other-rule", "다른 규칙이 막음")

    audit.BEFORE_PAYMENT_CHECKS.append(other)  # limit 뒤에 실행된다
    record = run_purchase({**INPUT, "userId": "user-refund"})
    assert record["status"] == "FAILED" and record["failureStage"] == "before-send"
    assert used("user-refund") == 0
    reservation = store.database()["limit_reservations"].find_one({"_id": record["id"]})
    assert reservation["released"] is True


def test_성공한_결제는_예약을_돌려주지_않는다(unit):
    record = run_purchase({**INPUT, "userId": "user-ok"})
    assert record["status"] == "SETTLED"
    assert used("user-ok") == unit
    assert store.database()["limit_reservations"].find_one({"_id": record["id"]})["released"] is False


def test_하루_한도의_80퍼센트부터는_결제마다_임박_알림이_남고_결제는_진행된다(monkeypatch, unit):
    monkeypatch.setattr(limit, "PER_DAY_UNITS", unit * 5)  # 4건째부터 80% 이상
    increase_chain_time(60)  # unit 을 재며 한 건 샀다. 체인의 결제 횟수 창(60초에 5건)을 새로 연다
    user = "user-warn"
    records = [run_purchase({**INPUT, "userId": user}) for _ in range(5)]
    assert all(r["status"] == "SETTLED" for r in records)
    assert len(alerts_with(user, "한도 임박")) == 2  # 4건째, 5건째
