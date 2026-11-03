"""
구매처 고르기. 어느 판매 에이전트와 흥정해 어디서 살지 정한다.

  1. 우선순위별 비교 모델을 data/sellers.json 의 priorityModels 에서 읽는다. 벤치마크 값을 보고 사람이 정해 둔 표다.
  2. 그 모델의 판매 에이전트와 각각 흥정한다.
  3. 합의가가 가장 낮은 곳에서 산다. 값이 같으면 표에서 앞에 있는 모델이다. 나머지 합의는 취소한다.

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


def shop(candidates: list[dict[str, Any]], priority: str, budget_units: int) -> dict[str, Any]:
    """비교 모델과 흥정해 산 곳을 고른다. {winner, negotiation, quotes}. 모두 결렬되면 NegotiationError."""
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
        raise NegotiationError(
            f"흥정이 모두 결렬돼 결제하지 않았습니다. 예산 {aegis_text(budget_units)}", {"status": "no-deal", "quotes": quotes}
        )

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
