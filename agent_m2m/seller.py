"""
판매 에이전트. 호가에서 시작해 구매 에이전트의 제안에 답한다.

판매 에이전트는 data/sellers.json 에 등록된 회사마다 하나다. 호가는 토큰 단가로 계산하고, 최저가는 호가 × floorRatio 다.
floorRatio 는 판매자가 스스로 정해 공개하지 않는 값으로 본다. 실제 판매 회사가 낸 값이 아니라 데모용 설정값이다.

최저가는 이 객체 안에만 있고 답에도 기록에도 나가지 않는다. 구매 쪽은 판매자가 부른 값만 본다.
"""

import math
from typing import Any

from agent_m2m.benchmark import load_sellers
from agent_m2m.format import aegis_text
from agent_m2m.strategy import price_step, seller_reply


class GuardrailError(Exception):
    """세이프가드가 막았다. 이 값으로는 답하거나 제안하지 않는다."""


def find_seller(provider_id: str) -> dict[str, Any]:
    """이 회사의 판매 에이전트 설정. 등록되지 않은 회사거나 비율이 틀리면 ValueError."""
    seller = load_sellers().get(provider_id)
    if seller is None:
        raise ValueError(f"판매 에이전트가 없는 회사입니다: {provider_id}")
    ratio = seller.get("floorRatio")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio <= 1:
        raise ValueError(f"{provider_id} 의 floorRatio 는 0 초과 1 이하여야 합니다: {ratio}")
    return seller


class SellerAgent:
    def __init__(self, ask_units: int, floor_ratio: float) -> None:
        self.ask_units = ask_units
        self._floor_units = math.ceil(ask_units * floor_ratio)
        self._last_counter = ask_units
        self._step = price_step(ask_units)

    def reply_to_offer(self, offer: int) -> tuple[str, int, str]:
        """구매자의 제안에 (행동, 값, 문장) 으로 답한다. 행동은 accept·counter 중 하나다."""
        action, price = seller_reply(self._floor_units, self._last_counter, offer, self._step)
        if price < self._floor_units:
            raise GuardrailError(f"판매 세이프가드: 최저가보다 낮은 값입니다: {aegis_text(price)}")
        if action == "accept":
            return action, price, f"좋아요, {aegis_text(price)}에 드릴게요."
        self._last_counter = price
        return action, price, f"{aegis_text(offer)}까지는 어렵고, {aegis_text(price)}까지는 해 드릴 수 있어요."

    def accept_counter(self, price: int) -> tuple[str, int, str]:
        """구매자가 판매자가 부른 값에 합의했을 때. 판매자가 부른 값이 아니면 받지 않는다."""
        if price != self._last_counter:
            raise GuardrailError(f"판매 세이프가드: 판매자가 부른 값이 아닙니다: {aegis_text(price)}")
        return "accept", price, f"좋아요, {aegis_text(price)}에 거래할게요."
