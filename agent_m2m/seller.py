"""
판매 에이전트. 호가에서 시작해 구매 에이전트의 제안에 답한다.

최저가는 이 객체 안에만 있고 답에도 기록에도 나가지 않는다. 구매 쪽은 판매자가 부른 값만 본다.
실제 판매 회사가 정한 값은 없으므로, 최저가는 판매 단가에 AEGIS_SELLER_FLOOR_RATIO 를 곱한 데모용 값이다.
"""

import math
import os

from agent_m2m.format import aegis_text
from agent_m2m.strategy import price_step, seller_reply


class GuardrailError(Exception):
    """세이프가드가 막았다. 이 값으로는 답하거나 제안하지 않는다."""


def floor_ratio() -> float:
    text = os.environ.get("AEGIS_SELLER_FLOOR_RATIO") or "0.8"
    try:
        ratio = float(text)
    except ValueError as error:
        raise ValueError(f"AEGIS_SELLER_FLOOR_RATIO 는 숫자여야 합니다: {text}") from error
    if not 0 < ratio <= 1:
        raise ValueError(f"AEGIS_SELLER_FLOOR_RATIO 는 0 초과 1 이하여야 합니다: {text}")
    return ratio


class SellerAgent:
    def __init__(self, ask_units: int) -> None:
        self.ask_units = ask_units
        self._floor_units = math.ceil(ask_units * floor_ratio())
        self._last_counter = ask_units
        self._last_offer: int | None = None
        self._rounds = 0
        self._step = price_step(ask_units)

    def reply_to_offer(self, offer: int) -> tuple[str, int, str]:
        """구매자의 제안에 (행동, 값, 문장) 으로 답한다. 행동은 accept·counter·reject 중 하나다."""
        self._rounds += 1
        action, price = seller_reply(self._floor_units, self._last_counter, offer, self._rounds, self._last_offer, self._step)
        self._last_offer = offer
        if action != "reject" and price < self._floor_units:
            raise GuardrailError(f"판매 세이프가드: 최저가보다 낮은 값입니다: {aegis_text(price)}")
        if action == "accept":
            return action, price, f"좋아요, {aegis_text(price)}에 드릴게요."
        if action == "reject":
            return action, price, f"죄송해요, {aegis_text(offer)}에는 팔 수 없어요."
        self._last_counter = price
        return action, price, f"{aegis_text(offer)}까지는 어렵고, {aegis_text(price)}까지는 해 드릴 수 있어요."

    def accept_counter(self, price: int) -> tuple[str, int, str]:
        """구매자가 판매자가 부른 값에 합의했을 때. 판매자가 부른 값이 아니면 받지 않는다."""
        if price != self._last_counter:
            raise GuardrailError(f"판매 세이프가드: 판매자가 부른 값이 아닙니다: {aegis_text(price)}")
        return "accept", price, f"좋아요, {aegis_text(price)}에 거래할게요."
