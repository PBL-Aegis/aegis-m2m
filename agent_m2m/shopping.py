"""
구매처 고르기. 어느 판매 에이전트와 흥정해 어디서 살지 정한다.

  1. 우선순위별 비교 모델을 data/sellers.json 의 priorityModels 에서 읽는다. 벤치마크 값을 보고 사람이 정해 둔 표다.
  2. 그 모델의 판매 에이전트와 각각 흥정한다. 구매 에이전트는 페르소나(persona.py)대로 흥정한다.
  3. 페르소나 기준으로 한 곳을 고른다. 가장 싼 합의가보다 premium_limit 비율까지 비싼 곳 중 성능(ECI)이 가장 높은 곳이다.
     최저가형은 한도가 0 이라 합의가가 가장 낮은 곳(값이 같으면 ECI 가 높은 곳)이다. 나머지 합의는 이유를 남기고 취소한다.
  4. 모두 결렬되면 판매자가 마지막에 부른 값이 가장 낮은 곳을 그 값에 산다. 값이 같으면 역시 성능이 높은 모델이다. 예산을 넘는 구매라 경고 알림을 남긴다(rules/over_budget.py).

흥정 중인 다른 판매자의 값은 상대에게 알리지 않는다. 근거 카드는 공개된 호가와 ECI 만 비교한다(cards.py).

끝나면 페르소나 관점의 평가(evaluation.py)를 함께 돌려준다.

on_event 로 진행을 바로 알린다. 비교 모델이 정해지면 plan, 대화가 한 줄 늘면 turn 이다.
"""

from collections.abc import Callable
from typing import Any

from agent_m2m.benchmark import load_priority_models
from agent_m2m.cards import buyer_cards, seller_cards
from agent_m2m.dialogue import LineWriter
from agent_m2m.evaluation import evaluate
from agent_m2m.format import aegis_text
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.persona import load_persona, reason
from agent_m2m.persona_llm import DEFAULT_MODE
from agent_m2m.selection import SelectionError
from agent_m2m.seller import find_seller


def compared_models(candidates: list[dict[str, Any]], priority: str) -> list[dict[str, Any]]:
    """표에 적힌 순서대로, 필요 기능을 통과한 비교 모델. 하나도 없으면 SelectionError."""
    by_key = {candidate["key"]: candidate for candidate in candidates}
    compared = [by_key[key] for key in load_priority_models()[priority] if key in by_key]
    if not compared:
        raise SelectionError("조건을 통과한 비교 모델이 없습니다")
    return compared


def _last_seller_price(quote: dict[str, Any]) -> int | None:
    prices = [turn["priceUnits"] for turn in quote["transcript"] if turn["from"] == "seller"]
    return prices[-1] if prices else None


def _buy_over_budget(
    quotes: list[dict[str, Any]], add_turn: Callable[[dict[str, Any], dict[str, Any]], None], persona: dict[str, Any]
) -> dict[str, Any]:
    """모두 결렬됐을 때 판매자가 마지막에 부른 값이 가장 낮은 곳을 그 값에 산다. 예산을 넘는 구매로 표시한다."""
    priced = [quote for quote in quotes if quote["status"] == "no-deal" and _last_seller_price(quote) is not None]
    if not priced:
        raise NegotiationError("흥정할 수 있는 판매자가 없어 결제하지 않았습니다", {"status": "no-deal", "quotes": quotes})
    quote = min(priced, key=lambda item: (_last_seller_price(item), -item["eci"]))
    price = _last_seller_price(quote)
    why = reason(persona, "over-budget", f"모든 흥정이 결렬돼, 판매자가 마지막에 부른 값이 가장 낮은 이곳에서 예산을 넘겨 {aegis_text(price)}에 삽니다.", priceUnits=price)
    add_turn(quote, {"from": "buyer", "action": "accept", "priceUnits": price, "text": f"예산을 넘지만 {aegis_text(price)}에 살게요.", "reason": why})
    add_turn(quote, {"from": "seller", "action": "accept", "priceUnits": price, "text": f"좋아요, {aegis_text(price)}에 거래할게요."})
    quote.update({"status": "agreed", "agreedUnits": price, "overBudget": True})
    return quote


def choose(agreed: list[dict[str, Any]], persona: dict[str, Any]) -> dict[str, Any]:
    """가장 싼 합의가의 (1 + premium_limit) 배 안에서 ECI 가 가장 높은 곳. ECI 가 같으면 싼 곳이다."""
    cheapest = min(quote["agreedUnits"] for quote in agreed)
    within = [quote for quote in agreed if quote["agreedUnits"] <= cheapest * (1 + persona["premiumLimit"])]
    return max(within, key=lambda quote: (quote["eci"], -quote["agreedUnits"]))


def _cancel_reason(quote: dict[str, Any], chosen: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    gap, eci_gap = quote["agreedUnits"] - chosen["agreedUnits"], chosen["eci"] - quote["eci"]
    name = chosen["displayName"]
    if gap > 0 and persona["premiumLimit"] == 0:
        text = f"{name} 쪽이 {aegis_text(gap)} 더 싸서 이곳은 취소합니다."
    elif gap > 0 and eci_gap >= 0:
        text = f"{name} 쪽이 {aegis_text(gap)} 더 싸고 ECI도 낮지 않아 이곳은 취소합니다."
    elif gap > 0:
        text = (
            f"이곳의 ECI가 {-eci_gap:.2f} 높지만 {name}보다 {gap / chosen['agreedUnits']:.0%} 비싸 "
            f"더 낼 수 있는 한도 {persona['premiumLimit']:.0%}를 넘어 취소합니다."
        )
    elif gap == 0:
        text = f"값이 같아 ECI가 {eci_gap:.2f} 높은 {name}에서 사고 이곳은 취소합니다."
    else:
        text = (
            f"이곳이 {aegis_text(-gap)}({-gap / quote['agreedUnits']:.0%}) 싸지만, {name}의 ECI가 {eci_gap:.2f} 높고 "
            f"더 낼 수 있는 한도 {persona['premiumLimit']:.0%} 안이라 이곳은 취소합니다."
        )
    return reason(persona, "cancel", text, chosenKey=chosen["key"], gapUnits=gap, eciGap=round(eci_gap, 2), premiumLimit=persona["premiumLimit"])


def shop(
    candidates: list[dict[str, Any]],
    priority: str,
    budget_units: int,
    on_event: Callable[[dict[str, Any]], None] = lambda event: None,
    persona: dict[str, Any] | None = None,
    mode: str = DEFAULT_MODE,
) -> dict[str, Any]:
    """비교 모델과 흥정해 산 곳을 고른다. {winner, negotiation, quotes, persona, evaluation}.
    persona 가 없으면 기본 페르소나, mode 는 구매자가 값을 정하는 방식(persona_llm.py)이다. 어디서 살지는 방식과 상관없이 코드가 정한다. 판매자 값을 하나도 못 받았을 때만 NegotiationError."""
    persona = persona or load_persona()
    compared = compared_models(candidates, priority)
    sellers = {candidate["key"]: find_seller(candidate["providerId"]) for candidate in compared}
    on_event(
        {
            "type": "plan",
            "priority": priority,
            "persona": {"id": persona["id"], "name": persona["name"]},
            "negotiationMode": mode,
            "models": [
                {
                    "key": candidate["key"],
                    "displayName": candidate["displayName"],
                    "sellerName": sellers[candidate["key"]]["name"],
                    "askUnits": candidate["amountUnits"],
                }
                for candidate in compared
            ],
        }
    )

    def add_turn(quote: dict[str, Any], turn: dict[str, Any]) -> None:
        quote["transcript"].append(turn)
        on_event({"type": "turn", "key": quote["key"], "turn": turn})

    writer = LineWriter()
    quotes: list[dict[str, Any]] = []
    for candidate in compared:
        rival = next((other for other in compared if other is not candidate), None)
        key = candidate["key"]
        seller = sellers[key]
        quote = {"key": key, "displayName": candidate["displayName"], "sellerName": seller["name"], "eci": candidate["eci"]}
        try:
            quote.update(
                negotiate(
                    candidate["amountUnits"],
                    budget_units,
                    seller["floorRatio"],
                    lambda turn, key=key: on_event({"type": "turn", "key": key, "turn": turn}),
                    buyer_cards(candidate, rival),
                    seller_cards(candidate, rival),
                    lambda role, card, price, candidate=candidate, rival=rival: writer.write(role, card, price, candidate, rival),
                    persona,
                    mode,
                )
            )
        except NegotiationError as error:
            quote.update(error.negotiation)
        quotes.append(quote)

    agreed = [quote for quote in quotes if quote["status"] == "agreed"]
    if not agreed:
        agreed = [_buy_over_budget(quotes, add_turn, persona)]

    chosen = choose(agreed, persona)
    for quote in agreed:
        if quote is not chosen:
            quote["status"] = "cancelled"
            add_turn(
                quote,
                {
                    "from": "buyer",
                    "action": "reject",
                    "priceUnits": quote["agreedUnits"],
                    "text": "죄송해요, 이번에는 다른 곳에서 사기로 했어요.",
                    "reason": _cancel_reason(quote, chosen, persona),
                },
            )
    source = next(candidate for candidate in compared if candidate["key"] == chosen["key"])
    return {
        "winner": {**source, "amountUnits": chosen["agreedUnits"], "listAmountUnits": source["amountUnits"]},
        "negotiation": chosen,
        "quotes": quotes,
        "persona": {key: persona[key] for key in ("id", "name", "goal", "hash")},
        "negotiationMode": mode,
        "evaluation": evaluate(persona, chosen, quotes, budget_units),
    }
