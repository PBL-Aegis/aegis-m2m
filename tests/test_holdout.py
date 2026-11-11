"""
시나리오 ① · 일부러 결렬시켜 예산 초과 구매 유도.

판매 에이전트가 예산보다 높은 값에서 버티면 흥정이 모두 결렬되고, 구매 에이전트는 판매자가 마지막에 부른 값에 산다.
규칙이 없으면 그 값이 그대로 결제되고(SETTLED), holdout 규칙이 있으면 송금 직전에 막혀 돈이 나가지 않는 것을 확인한다.
금액은 모두 기록과 픽스처에서 읽는다.
"""

import pytest

from agent_m2m import audit, shopping, store
from agent_m2m.benchmark import load_snapshot
from agent_m2m.payment import buyer_balance
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import holdout
from agent_m2m.selection import decide
from agent_m2m.seller import find_seller
from agent_m2m.shopping import compared_models

LARGE_BUDGET = 10_000_000
HOLDOUT_RULES = {holdout.RULE, holdout.STALL_RULE, holdout.SELLER_RULE}
# purchase.py 를 불러오며 등록된 실제 규칙 목록. holdout_only 가 비우기 전에 저장해 둔다.
REGISTERED = {"before": audit.BEFORE_PAYMENT_CHECKS.copy(), "after": audit.AFTER_PAYMENT_CHECKS.copy()}


@pytest.fixture(autouse=True)
def holdout_only():
    """다른 규칙은 비우고 holdout 규칙만 등록한다(한도·중복 구매 규칙과 부딪히지 않게)."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    audit.BEFORE_PAYMENT_CHECKS.append(holdout.check_holdout)
    # 판매자 집계는 같은 파일의 테스트끼리 이어지므로 테스트마다 비운다.
    store.database()[holdout.COLLECTION].delete_many({})
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


@pytest.fixture
def no_rules():
    audit.BEFORE_PAYMENT_CHECKS.clear()


@pytest.fixture
def sellers_hold_at_ask(monkeypatch):
    """판매 에이전트가 호가에서 한 푼도 내리지 않는다(최저가 비율 1.0). 공격하는 판매자다."""
    monkeypatch.setattr(shopping, "find_seller", lambda provider_id: {**find_seller(provider_id), "floorRatio": 1.0})


def asks(priority: str) -> list[int]:
    """이 우선순위에서 비교하는 모델들의 호가(units)."""
    request = {"prompt": "호가 확인", "budgetUnits": LARGE_BUDGET, "priority": priority}
    return [model["amountUnits"] for model in compared_models(decide(request, load_snapshot())["candidates"], priority)]


def buy(prompt: str, user: str, budget: int, priority: str = "default", **extra) -> dict:
    return run_purchase({"prompt": prompt, "userId": user, "budgetUnits": budget, "priority": priority, **extra})


def alerts_of(record: dict) -> list[dict]:
    return [alert for alert in store.list_alerts_for_purchase(record["id"]) if alert["rule"] in HOLDOUT_RULES]


def test_규칙이_없으면_모두_결렬된_뒤_예산을_넘는_값이_그대로_결제된다(no_rules):
    before = buyer_balance()["units"]
    record = buy("예산 0 으로 요약해 줘", "user-no-rule", 0)
    amount = record["decision"]["winner"]["amountUnits"]
    assert record["status"] == "SETTLED"
    assert record["decision"]["negotiation"]["overBudget"] is True
    assert {quote["status"] for quote in record["decision"]["quotes"]} >= {"no-deal"}
    assert amount > record["decision"]["budgetUnits"]
    assert buyer_balance()["units"] == before - amount


def test_규칙이_있으면_예산_초과_구매를_holdout_으로_막고_돈이_나가지_않는다():
    before = buyer_balance()["units"]
    record = buy("예산 0 으로 번역해 줘", "user-blocked", 0)
    assert record["status"] == "FAILED"
    assert record["failureStage"] == "before-send"
    assert record["blockedRule"] == holdout.RULE
    assert record["payment"] is None
    assert buyer_balance()["units"] == before
    assert "예산" in record["failureReason"] and "허용 폭" in record["failureReason"]
    blocked = [alert for alert in alerts_of(record) if alert["blocked"]]
    assert [alert["rule"] for alert in blocked] == [holdout.RULE]


def test_판매자가_호가에서_버티면_규칙이_없을_때는_호가_전액이_결제된다(no_rules, sellers_hold_at_ask):
    budget = min(asks("default")) * 9 // 10
    record = buy("버티는 판매자, 규칙 없음", "user-hold-no-rule", budget)
    winner = record["decision"]["winner"]
    assert record["status"] == "SETTLED"
    assert winner["amountUnits"] == winner["listAmountUnits"] > budget


def test_판매자가_호가에서_버티면_막히고_버틴_판매자마다_알림이_남는다(sellers_hold_at_ask):
    budget = min(asks("default")) * 9 // 10
    before = buyer_balance()["units"]
    record = buy("버티는 판매자, 규칙 있음", "user-hold", budget)
    assert record["status"] == "FAILED" and record["blockedRule"] == holdout.RULE
    assert buyer_balance()["units"] == before

    stalls = [alert for alert in alerts_of(record) if alert["rule"] == holdout.STALL_RULE]
    assert len(stalls) == len(record["decision"]["quotes"])
    assert all(not alert["blocked"] and "호가에서 한 번도 내리지 않았습니다" in alert["message"] for alert in stalls)
    assert "버틴 판매자" in record["failureReason"]


def test_정상_흥정은_막지도_알리지도_않는다():
    record = buy("넉넉한 예산으로 요약해 줘", "user-normal", LARGE_BUDGET)
    assert record["status"] == "SETTLED"
    assert record["decision"]["negotiation"].get("overBudget") is not True
    assert alerts_of(record) == []


def test_판매자가_최저가에서_머물러도_합의하면_알리지_않는다():
    """정상 흥정에서도 판매자는 최저가에 닿으면 같은 값을 여러 번 부른다. 결렬되지 않았으면 버티기로 보지 않는다."""
    budget = max(asks("default"))
    record = buy("예산이 호가와 같을 때", "user-floor", budget)
    assert record["status"] == "SETTLED"
    assert [alert for alert in alerts_of(record) if alert["rule"] == holdout.STALL_RULE] == []


def test_허용_폭_안의_예산_초과는_막지_않고_알림만_남긴다(monkeypatch, sellers_hold_at_ask):
    ask = min(asks("default"))
    budget = ask * 9 // 10
    monkeypatch.setattr(holdout, "TOLERANCE_RATIO", (ask - budget) / budget)
    record = buy("허용 폭 안", "user-tolerance", budget)
    assert record["status"] == "SETTLED"
    assert record["decision"]["negotiation"]["overBudget"] is True
    assert {alert["rule"] for alert in alerts_of(record)} == {holdout.STALL_RULE}


def test_허용_폭을_조금이라도_넘으면_막는다(monkeypatch, sellers_hold_at_ask):
    ask = min(asks("default"))
    budget = ask * 9 // 10
    monkeypatch.setattr(holdout, "TOLERANCE_RATIO", (ask - budget - 1) / budget)
    record = buy("허용 폭 바로 밖", "user-tolerance-edge", budget)
    assert record["status"] == "FAILED" and record["blockedRule"] == holdout.RULE


def test_같은_판매자에서_예산_초과_비율이_높으면_알린다(monkeypatch):
    monkeypatch.setattr(holdout, "SELLER_MIN_DEALS", 3)
    monkeypatch.setattr(holdout, "SELLER_RATIO", 0.5)
    ok = buy("판매자 집계 1", "user-rate", LARGE_BUDGET, "price")
    first = buy("판매자 집계 2", "user-rate", 0, "price")
    second = buy("판매자 집계 3", "user-rate", 0, "price")
    assert ok["status"] == "SETTLED"
    assert ok["decision"]["winner"]["providerId"] == second["decision"]["winner"]["providerId"]

    def rate_alerts(record):
        return [alert for alert in alerts_of(record) if alert["rule"] == holdout.SELLER_RULE]

    assert rate_alerts(ok) == [] and rate_alerts(first) == []  # 아직 3건이 안 쌓임
    [alert] = rate_alerts(second)
    assert not alert["blocked"] and "3건 중 2건" in alert["message"]
    assert second["blockedRule"] == holdout.RULE  # 알림과 별개로 이 건은 막힌다


def test_판매자_집계는_최근_N건만_본다(monkeypatch):
    monkeypatch.setattr(holdout, "SELLER_WINDOW", 2)
    monkeypatch.setattr(holdout, "SELLER_MIN_DEALS", 2)
    monkeypatch.setattr(holdout, "SELLER_RATIO", 1.0)
    buy("창 1", "user-window", 0, "price")
    buy("창 2", "user-window", LARGE_BUDGET, "price")
    last = buy("창 3", "user-window", 0, "price")
    # 최근 2건은 [정상, 초과] 라 50% < 100%
    assert [alert for alert in alerts_of(last) if alert["rule"] == holdout.SELLER_RULE] == []
    provider = last["decision"]["winner"]["providerId"]
    assert len(store.database()[holdout.COLLECTION].find_one({"_id": provider})["recent"]) == 2


def test_등록된_모든_규칙과_함께_돌아도_holdout_이름으로_막힌다():
    audit.BEFORE_PAYMENT_CHECKS[:] = REGISTERED["before"]
    audit.AFTER_PAYMENT_CHECKS[:] = REGISTERED["after"]
    assert holdout.check_holdout in audit.BEFORE_PAYMENT_CHECKS
    record = buy("전체 규칙과 함께 예산 0", "user-all-rules", 0)
    assert record["status"] == "FAILED" and record["blockedRule"] == holdout.RULE
