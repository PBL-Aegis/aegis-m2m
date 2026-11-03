"""
흥정 한 번. 구매 에이전트가 판매 에이전트(seller.py) 하나와 값을 맞춘다. 누구와 흥정할지는 shopping.py 가 정한다.

합의가가 곧 결제 금액이다. 그래서 감사 규칙과 체인 규칙은 실제로 나갈 금액을 본다.
구매자는 요청의 예산과 호가 중 낮은 값을 넘겨 부르거나 합의할 수 없다.
합의하지 못하면 기록을 남기기 전에 NegotiationError 로 멈춘다. 돈은 나가지 않는다.
"""

from typing import Any

from agent_m2m.format import aegis_text
from agent_m2m.seller import GuardrailError, SellerAgent
from agent_m2m.strategy import MAX_ROUNDS, buyer_opening, buyer_reply, price_step


class NegotiationError(Exception):
    """합의하지 못했다. 결제는 시작하지 않았다. negotiation 에 대화 기록이 있다."""

    def __init__(self, message: str, negotiation: dict[str, Any]) -> None:
        super().__init__(message)
        self.negotiation = negotiation


def _check_buyer_price(price: int, max_units: int) -> None:
    if price > max_units:
        raise GuardrailError(f"구매 세이프가드: 최대가보다 높은 값입니다: {aegis_text(price)}")


def negotiate(ask_units: int, budget_units: int, floor_ratio: float) -> dict[str, Any]:
    """호가에서 시작해 합의가를 찾는다. floor_ratio 는 판매 에이전트만 쓴다.
    합의하면 합의가와 대화 기록을 돌려주고, 못 하면 NegotiationError."""
    max_units = min(budget_units, ask_units)
    step = price_step(ask_units)
    seller = SellerAgent(ask_units, floor_ratio)
    transcript: list[dict[str, Any]] = []

    def say(speaker: str, action: str, price: int, text: str) -> None:
        transcript.append({"from": speaker, "action": action, "priceUnits": price, "text": text})

    def result(status: str) -> dict[str, Any]:
        return {"status": status, "askUnits": ask_units, "maxUnits": max_units, "transcript": transcript}

    def offer_to_seller(price: int, text: str) -> tuple[str, int]:
        _check_buyer_price(price, max_units)
        say("buyer", "offer", price, text)
        action, answer, reply = seller.reply_to_offer(price)
        say("seller", action, answer, reply)
        return action, answer

    try:
        offer = buyer_opening(ask_units, max_units, step)
        action, price = offer_to_seller(offer, f"{aegis_text(ask_units)}에 올리셨네요. {aegis_text(offer)}에 주실 수 있나요?")
        rounds = 1
        while action == "counter":
            counter = price
            # 마지막 제안까지 값이 맞지 않았으면 판매자의 마지막 값이 최대가 이하일 때만 받는다.
            if rounds == MAX_ROUNDS and counter > max_units:
                say("buyer", "reject", counter, f"{aegis_text(counter)}는 제 최대가를 넘어요. 이번에는 어렵겠어요.")
                action = "reject"
                break
            reply, value = ("accept", counter) if rounds == MAX_ROUNDS else buyer_reply(max_units, offer, counter, step)
            if reply == "accept":
                _check_buyer_price(value, max_units)
                say("buyer", "accept", value, f"좋아요, {aegis_text(value)}에 살게요.")
                action, price, text = seller.accept_counter(value)
                say("seller", action, price, text)
                break
            offer, rounds = value, rounds + 1
            action, price = offer_to_seller(offer, f"{aegis_text(counter)}는 조금 부담돼요. {aegis_text(offer)}면 바로 살게요.")
    except GuardrailError as error:
        raise NegotiationError(str(error), result("blocked")) from error

    if action != "accept":
        raise NegotiationError(f"흥정이 결렬돼 결제하지 않았습니다. 호가 {aegis_text(ask_units)}, 예산 {aegis_text(budget_units)}", result("no-deal"))
    return {**result("agreed"), "agreedUnits": price}
