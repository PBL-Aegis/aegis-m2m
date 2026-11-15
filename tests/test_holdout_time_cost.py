"""시나리오 ① 시간 비용 실험(scripts/holdout_time_cost.py)이 보여 주는 결론이 코드가 바뀌어도 유지되는지 확인한다."""

import pytest

from agent_m2m import benchmark, shopping
from agent_m2m.benchmark import load_snapshot
from agent_m2m.selection import decide
from scripts import holdout_time_cost as experiment

WAIT = 0.01


@pytest.fixture(autouse=True)
def two_sellers(monkeypatch):
    """'기본' 등급에서 가장 싼 두 모델(서로 다른 판매자)을 비교하게 한다. 픽스처의 표는 등급마다 판매자가 하나뿐일 수 있다."""
    candidates = decide({"prompt": experiment.PROMPT, "budgetUnits": 10**12, "priority": "default"}, load_snapshot())["candidates"]
    keys, providers = [], set()
    for candidate in sorted(candidates, key=lambda item: item["amountUnits"]):
        if candidate["providerId"] not in providers:
            keys.append(candidate["key"])
            providers.add(candidate["providerId"])
    monkeypatch.setattr(shopping, "load_priority_models", lambda: {**benchmark.load_priority_models(), "default": keys[:2]})


def strategies(first: str, second: str) -> dict[str, str]:
    models = experiment.sellers_of("default")
    return {models[0]["providerId"]: first, models[1]["providerId"]: second}


def total_profit(totals: dict) -> int:
    return sum(value["profit"] for key, value in totals.items() if key != "_blocked")


def total_sales(totals: dict) -> int:
    return sum(value["sales"] for key, value in totals.items() if key != "_blocked")


@pytest.fixture
def equal_asks(monkeypatch):
    """두 판매자의 호가를 같게 맞춘다(실제 '싸게' 등급의 Haiku·Luna 처럼 둘 다 0.004001)."""
    original = shopping.compared_models

    def same_price(candidates, priority):
        models = original(candidates, priority)
        low = min(model["amountUnits"] for model in models)
        return [{**model, "amountUnits": low} for model in models]

    monkeypatch.setattr(shopping, "compared_models", same_price)


@pytest.mark.parametrize("rule_on", [False, True])
def test_값이_비슷한_경쟁자가_있으면_혼자_버틴_판매자는_손님을_모두_뺏기고_기다린_비용만_낸다(equal_asks, rule_on):
    holdout_key = experiment.sellers_of("default")[0]["key"]
    totals = experiment.profits("default", strategies("버팀", "정상"), WAIT, rule_on)

    assert totals[holdout_key]["sales"] == 0
    assert totals[holdout_key]["profit"] < 0


def test_경쟁자가_훨씬_비싸면_싼_판매자는_혼자_버텨도_손님을_모두_가져간다():
    # 픽스처: 싼 모델 호가가 비싼 모델 최저가(호가 × 0.8)보다 낮다. 사실상 독점이라 버텨도 안 뺏긴다.
    cheap, pricey = experiment.sellers_of("default")
    assert cheap["amountUnits"] < pricey["amountUnits"] * experiment.STRATEGY_FLOOR["정상"]
    alone = experiment.profits("default", strategies("버팀", "정상"), WAIT, rule_on=False)
    honest = experiment.profits("default", strategies("정상", "정상"), WAIT, rule_on=False)

    assert alone[cheap["key"]]["sales"] == len(experiment.BUDGET_SHARES)
    assert alone[cheap["key"]]["profit"] > honest[cheap["key"]]["profit"]


def test_같이_버티면_규칙이_없을_때_예산을_넘겨_받아_간다():
    honest = experiment.profits("default", strategies("정상", "정상"), WAIT, rule_on=False)
    holdout = experiment.profits("default", strategies("버팀", "버팀"), WAIT, rule_on=False)

    assert total_profit(holdout) > total_profit(honest)


def test_감사_규칙은_같이_버틴_예산_초과_구매를_막아_이익을_줄인다():
    off = experiment.profits("default", strategies("버팀", "버팀"), WAIT, rule_on=False)
    on = experiment.profits("default", strategies("버팀", "버팀"), WAIT, rule_on=True)

    assert on["_blocked"] > 0
    assert total_sales(on) < total_sales(off)
    assert total_profit(on) < total_profit(off)
