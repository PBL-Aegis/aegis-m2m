"""
근거 카드. 에이전트가 값을 요구하는 이유다. 호가와 ECI 를 비교해 사실인 카드만 코드가 고른다.

상대가 양보하는 비율은 낸 카드가 처음 낸 것인지(new), 이미 낸 것인지(used), 카드가 없는지(none)로 정한다.
구매 에이전트의 비율은 페르소나 파일(persona.py)에 있다. 판매 에이전트의 비율은 아래 SELLER_CONCEDE 이고 시연용 값이다.
"""

from typing import Any

BETTER = "성능 우위"
CHEAPER = "가격 우위"
RIVAL_CHEAPER = "경쟁 모델 가격 우위"
RIVAL_BETTER = "경쟁 모델 성능 우위"
NO_CARD = "근거 없음"

FRESHNESS_TEXT = {"new": "처음 낸 카드", "used": "이미 낸 카드", "none": "카드 없음"}
# 구매자가 낸 카드에 판매자가 값 차이 중 내려 주는 비율.
SELLER_CONCEDE = {"new": 0.75, "used": 0.5, "none": 0.25}


def seller_cards(model: dict[str, Any], rival: dict[str, Any] | None) -> tuple[str, ...]:
    """판매 에이전트가 낼 수 있는 카드. 비교할 모델이 없으면 카드도 없다."""
    if rival is None:
        return ()
    cards = []
    if model["eci"] > rival["eci"]:
        cards.append(BETTER)
    if model["amountUnits"] < rival["amountUnits"]:
        cards.append(CHEAPER)
    return tuple(cards)


def buyer_cards(model: dict[str, Any], rival: dict[str, Any] | None) -> tuple[str, ...]:
    """이 모델과 흥정할 때 구매 에이전트가 낼 수 있는 카드."""
    if rival is None:
        return ()
    cards = []
    if rival["amountUnits"] < model["amountUnits"]:
        cards.append(RIVAL_CHEAPER)
    if rival["eci"] > model["eci"]:
        cards.append(RIVAL_BETTER)
    return tuple(cards)


class CardHand:
    """한 흥정에서 한쪽이 든 카드. 안 쓴 카드부터 낸다."""

    def __init__(self, cards: tuple[str, ...]) -> None:
        self._cards = cards
        self._used = 0

    def play(self) -> tuple[str, str]:
        """(카드, new·used·none). 상대는 뒤의 값으로 양보 비율을 고른다."""
        if not self._cards:
            return NO_CARD, "none"
        if self._used < len(self._cards):
            self._used += 1
            return self._cards[self._used - 1], "new"
        return self._cards[-1], "used"
