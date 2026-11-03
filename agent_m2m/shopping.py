"""
구매처 고르기. 어느 판매 에이전트와 흥정해 어디서 살지 정한다.

  1. 우선순위별 비교 모델을 data/sellers.json 의 priorityModels 에서 읽는다. 벤치마크 값을 보고 사람이 정해 둔 표다.
  2. 그 모델의 판매 에이전트와 각각 흥정한다.
  3. 합의가가 가장 낮은 곳에서 산다. 값이 같으면 표에서 앞에 있는 모델이다. 나머지 합의는 취소한다.
  4. 모두 결렬되면 판매자가 마지막에 부른 값이 가장 낮은 곳을 그 값에 산다. 예산을 넘는 구매라 경고 알림을 남긴다(rules/over_budget.py).

다른 판매자의 값은 상대에게 알리지 않는다.
"""

from typing import Any

from agent_m2m.benchmark import load_priority_models
from agent_m2m.format import aegis_text
from agent_m2m.negotiation import NegotiationError, negotiate
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


def _buy_over_budget(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """모두 결렬됐을 때 판매자가 마지막에 부른 값이 가장 낮은 곳을 그 값에 산다. 예산을 넘는 구매로 표시한다."""
    priced = [quote for quote in quotes if quote["status"] == "no-deal" and _last_seller_price(quote) is not None]
    if not priced:
        raise NegotiationError("흥정할 수 있는 판매자가 없어 결제하지 않았습니다", {"status": "no-deal", "quotes": quotes})
    quote = min(priced, key=_last_seller_price)
    price = _last_seller_price(quote)
    quote["transcript"].append(
        {"from": "buyer", "action": "accept", "priceUnits": price, "text": f"예산을 넘지만 {aegis_text(price)}에 살게요."}
    )
    quote["transcript"].append(
        {"from": "seller", "action": "accept", "priceUnits": price, "text": f"좋아요, {aegis_text(price)}에 거래할게요."}
    )
    quote.update({"status": "agreed", "agreedUnits": price, "overBudget": True})
    return quote


def shop(candidates: list[dict[str, Any]], priority: str, budget_units: int) -> dict[str, Any]:
    """비교 모델과 흥정해 산 곳을 고른다. {winner, negotiation, quotes}. 판매자 값을 하나도 못 받았을 때만 NegotiationError."""
    compared = compared_models(candidates, priority)
    quotes: list[dict[str, Any]] = []
    for candidate in compared:
        seller = find_seller(candidate["providerId"])
        quote = {"key": candidate["key"], "displayName": candidate["displayName"], "sellerName": seller["name"]}
        try:
            quote.update(negotiate(candidate["amountUnits"], budget_units, seller["floorRatio"]))
        except NegotiationError as error:
            quote.update(error.negotiation)
        quotes.append(quote)

    agreed = [quote for quote in quotes if quote["status"] == "agreed"]
    if not agreed:
        agreed = [_buy_over_budget(quotes)]

    chosen = min(agreed, key=lambda quote: quote["agreedUnits"])
    for quote in agreed:
        if quote is not chosen:
            quote["status"] = "cancelled"
            quote["transcript"].append(
                {"from": "buyer", "action": "reject", "priceUnits": quote["agreedUnits"], "text": "죄송해요, 이번에는 다른 곳에서 사기로 했어요."}
            )
    source = next(candidate for candidate in compared if candidate["key"] == chosen["key"])
    return {
        "winner": {**source, "amountUnits": chosen["agreedUnits"], "listAmountUnits": source["amountUnits"]},
        "negotiation": chosen,
        "quotes": quotes,
    }
