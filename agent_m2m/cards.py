"""
근거 카드. 에이전트가 값을 요구하는 이유다. 호가와 ECI 를 비교해 사실인 카드만 코드가 고른다.

상대가 양보하는 비율은 낸 카드로 정한다. 아직 안 쓴 카드 75%, 이미 쓴 카드 50%, 카드가 없으면 25% 다. 시연용 값이다.
"""

from typing import Any

BETTER = "성능 우위"
CHEAPER = "가격 우위"
RIVAL_CHEAPER = "경쟁 모델 가격 우위"
RIVAL_BETTER = "경쟁 모델 성능 우위"
NO_CARD = "근거 없음"

NEW_CARD_RATIO = 0.75
USED_CARD_RATIO = 0.5
NO_CARD_RATIO = 0.25


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

    def play(self) -> tuple[str, float]:
        """(카드, 상대의 양보 비율)."""
        if not self._cards:
            return NO_CARD, NO_CARD_RATIO
        if self._used < len(self._cards):
            self._used += 1
            return self._cards[self._used - 1], NEW_CARD_RATIO
        return self._cards[-1], USED_CARD_RATIO
