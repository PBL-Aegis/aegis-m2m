"""
구매처 고르기. 모델 선택 점수(selection.py)가 나온 뒤, 어느 판매 에이전트와 흥정해 어디서 살지 정한다.

  1. 우선순위가 보는 지표로 회사마다 대표 모델을 하나씩 뽑는다.
       price 호가 · speed 출력 속도 · intelligence 성능(ECI) · default 총점
  2. 그 지표에서 전체 1등과 차이가 작은 회사만 후보로 남긴다. 성능이나 속도가 크게 떨어지는 모델을 값만 보고 사지 않기 위해서다.
  3. 후보와 각각 흥정하고, 합의가가 가장 낮은 곳에서 산다. 값이 같으면 총점이 높은 쪽이다. 나머지 합의는 취소한다.

다른 판매자의 값은 상대에게 알리지 않는다. 차이 기준은 지표마다 정한 가정값이다.
"""

from typing import Any

from agent_m2m.format import aegis_text
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.seller import find_seller

# 호가는 1등의 이 배수까지, 출력 속도는 1등의 이 비율까지 후보로 둔다.
ASK_MARGIN_RATIO = 1.1
SPEED_MARGIN_RATIO = 0.9
# ECI 와 총점은 1등과의 차이가 이 값까지면 후보로 둔다.
ECI_MARGIN = 1.0
SCORE_MARGIN = 15.0


def _better(priority: str, left: dict[str, Any], right: dict[str, Any]) -> bool:
    """우선순위가 보는 지표에서 left 가 right 보다 앞서는지."""
    if priority == "price":
        return left["amountUnits"] < right["amountUnits"]
    if priority == "speed":
        return left["outputTokensPerSecond"] > right["outputTokensPerSecond"]
    if priority == "intelligence":
        return left["eci"] > right["eci"]
    return left["totalScore"] > right["totalScore"]


def _close_to(priority: str, candidate: dict[str, Any], best: dict[str, Any]) -> bool:
    if priority == "price":
        return candidate["amountUnits"] <= best["amountUnits"] * ASK_MARGIN_RATIO
    if priority == "speed":
        return candidate["outputTokensPerSecond"] >= best["outputTokensPerSecond"] * SPEED_MARGIN_RATIO
    if priority == "intelligence":
        return candidate["eci"] >= best["eci"] - ECI_MARGIN
    return candidate["totalScore"] >= best["totalScore"] - SCORE_MARGIN


def shortlist(candidates: list[dict[str, Any]], priority: str) -> list[dict[str, Any]]:
    """회사별 대표 모델 중 전체 1등과 차이가 작은 것들. 후보는 총점 순서로 온다."""
    representatives: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        current = representatives.get(candidate["providerId"])
        if current is None or _better(priority, candidate, current):
            representatives[candidate["providerId"]] = candidate
    best = candidates[0]
    for candidate in representatives.values():
        if _better(priority, candidate, best):
            best = candidate
    return [candidate for candidate in representatives.values() if _close_to(priority, candidate, best)]


def shop(candidates: list[dict[str, Any]], priority: str, budget_units: int) -> dict[str, Any]:
    """후보와 흥정해 산 곳을 고른다. {winner, negotiation, quotes}. 모두 결렬되면 NegotiationError."""
    quotes: list[dict[str, Any]] = []
    for candidate in shortlist(candidates, priority):
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
    source = next(candidate for candidate in candidates if candidate["key"] == chosen["key"])
    return {
        "winner": {**source, "amountUnits": chosen["agreedUnits"], "listAmountUnits": source["amountUnits"]},
        "negotiation": chosen,
        "quotes": quotes,
    }
