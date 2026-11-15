"""
시나리오 ① 실험 · 판매자가 버티면 정말 이득인가 (판매자의 시간 비용).

11주차 교수님 의견: 판매자도 제때 팔아야 이익이다. 오래 버티면 못 팔고 기다리는 손해(시간 비용)가 생긴다.
그래서 판매자 이익을 이렇게 센다.

  팔았을 때   이익 = 받은 값 - 원가 - 기다린 비용
  못 팔았을 때 이익 = - 기다린 비용
  원가        호가 × COST_RATIO(0.7). 정상 판매자의 최저가(호가 × 0.8)보다 낮아, 정상 판매자도 팔면 남는다.
              골드바 예시(1억에 사서 1.1억에 팔아야 함)처럼 원가와 최저가 사이가 판매자의 정상 이익이다. 데모용 값이다.
  기다린 비용  호가 × 기다리는 비용 비율 × 판매자가 값을 부른 횟수(흥정을 주고받은 횟수)

판매자 전략은 둘이다. 정상은 최저가 비율 0.8, 버팀은 1.0(호가에서 한 푼도 안 내림)이다.
구매자는 기본 페르소나(최저가형)이고, 예산은 그 등급에서 가장 싼 호가의 60%~120%인 손님 7명이다.
감사 규칙 holdout 이 켜져 있으면, 모두 결렬된 뒤 예산을 넘겨 사려는 구매는 막혀서 아무도 못 판다.

값은 코드가 계산해 입력이 같으면 결과도 같다(Gemma·체인·DB 없음).

    uv run python scripts/holdout_time_cost.py
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from agent_m2m import dialogue, shopping  # noqa: E402
from agent_m2m.benchmark import load_snapshot  # noqa: E402
from agent_m2m.format import aegis_text  # noqa: E402
from agent_m2m.rules import holdout  # noqa: E402
from agent_m2m.selection import decide  # noqa: E402
from agent_m2m.seller import find_seller  # noqa: E402

COST_RATIO = 0.7
STRATEGY_FLOOR = {"정상": 0.8, "버팀": 1.0}
BUDGET_SHARES = (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)
WAIT_COST_RATIOS = (0.0, 0.01, 0.03)
PROMPT = "이 글 요약해 줘"


def _no_dialogue(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
    raise httpx.ConnectError("실험은 대사를 쓰지 않습니다")


def sellers_of(priority: str) -> list[dict[str, Any]]:
    """이 등급에서 비교하는 모델(판매자)들. 호가가 있다."""
    decision = decide({"prompt": PROMPT, "budgetUnits": 10**12, "priority": priority}, load_snapshot())
    return shopping.compared_models(decision["candidates"], priority)


def sell(priority: str, strategies: dict[str, str], budget: int, rule_on: bool) -> dict[str, Any]:
    """손님 한 명. strategies 는 {회사: 정상|버팀}. 누가 얼마에 팔았는지, 판매자마다 값을 몇 번 불렀는지."""
    original = shopping.find_seller
    shopping.find_seller = lambda provider_id: {**find_seller(provider_id), "floorRatio": STRATEGY_FLOOR[strategies[provider_id]]}
    try:
        decision = decide({"prompt": PROMPT, "budgetUnits": budget, "priority": priority}, load_snapshot())
        result = shopping.shop(decision["candidates"], priority, budget)
    finally:
        shopping.find_seller = original
    winner = result["winner"]
    blocked = rule_on and winner["amountUnits"] > budget * (1 + holdout.TOLERANCE_RATIO)
    rounds = {quote["key"]: sum(1 for turn in quote["transcript"] if turn["from"] == "seller" and turn["action"] == "counter") for quote in result["quotes"]}
    return {"winnerKey": None if blocked else winner["key"], "priceUnits": winner["amountUnits"], "blocked": blocked, "rounds": rounds}


def profits(priority: str, strategies: dict[str, str], wait_cost_ratio: float, rule_on: bool) -> dict[str, dict[str, int]]:
    """손님 전체에 대해 판매자(모델)마다 {이익, 판 건수}. "_blocked" 에는 감사 규칙이 막아 아무도 못 판 손님 수."""
    models = sellers_of(priority)
    low_ask = min(model["amountUnits"] for model in models)
    totals: dict[str, Any] = {model["key"]: {"profit": 0, "sales": 0} for model in models}
    totals["_blocked"] = 0
    for share in BUDGET_SHARES:
        sale = sell(priority, strategies, round(low_ask * share), rule_on)
        for model in models:
            ask, total = model["amountUnits"], totals[model["key"]]
            wait = round(ask * wait_cost_ratio * sale["rounds"].get(model["key"], 0))
            if sale["winnerKey"] == model["key"]:
                total["profit"] += sale["priceUnits"] - round(ask * COST_RATIO) - wait
                total["sales"] += 1
            else:
                total["profit"] -= wait
        totals["_blocked"] += 1 if sale["blocked"] else 0
    return totals


def scenarios(models: list[dict[str, Any]]) -> list[tuple[str, dict[str, str]]]:
    first, second = (model["providerId"] for model in models)
    return [
        ("둘 다 정상", {first: "정상", second: "정상"}),
        ("둘 다 버팀", {first: "버팀", second: "버팀"}),
        (f"{first}만 버팀", {first: "버팀", second: "정상"}),
        (f"{second}만 버팀", {first: "정상", second: "버팀"}),
    ]


def main() -> None:
    dialogue.http_post = _no_dialogue
    for priority in ("price", "default", "intelligence"):
        models = sellers_of(priority)
        names = {model["key"]: f"{model['providerId']}({model['displayName']})" for model in models}
        print(f"\n## 등급 {priority}: {', '.join(f'{names[m['key']]} 호가 {aegis_text(m['amountUnits'])}' for m in models)}")
        print("| 기다리는 비용 | 판매자 전략 | 감사 규칙 | " + " | ".join(names[m["key"]] for m in models) + " | 막힌 손님 |")
        print("| --- | --- | --- | " + " | ".join("---" for _ in models) + " | --- |")
        for ratio in WAIT_COST_RATIOS:
            for label, strategies in scenarios(models):
                for rule_on in (False, True):
                    totals = profits(priority, strategies, ratio, rule_on)
                    cells = [
                        f"{aegis_text(totals[m['key']]['profit'])} ({totals[m['key']]['sales']}건)"
                        for m in models
                    ]
                    print(f"| {ratio:.0%} | {label} | {'켜짐' if rule_on else '꺼짐'} | " + " | ".join(cells) + f" | {totals['_blocked']} |")


if __name__ == "__main__":
    main()
