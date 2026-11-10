"""
흥정 한 번. 구매 에이전트가 판매 에이전트(seller.py) 하나와 값을 맞춘다. 누구와 흥정할지는 shopping.py 가 정한다.

합의가가 곧 결제 금액이다. 그래서 감사 규칙과 체인 규칙은 실제로 나갈 금액을 본다.
구매자는 요청의 예산과 호가 중 낮은 값을 넘겨 부르거나 합의할 수 없다.
합의하지 못하면 기록을 남기기 전에 NegotiationError 로 멈춘다. 돈은 나가지 않는다.

값은 양쪽이 낸 근거 카드(cards.py)와 구매자의 페르소나(persona.py)로 코드가 계산한다.
문장만 write_line 으로 바꿀 수 있고, 값은 문장에 영향을 받지 않는다.
구매자가 말할 때마다 reason 에 페르소나 기준의 이유를 남긴다. 판매자의 말에는 남기지 않는다(최저가가 드러나지 않게).
"""

from collections.abc import Callable
from typing import Any

from agent_m2m.cards import FRESHNESS_TEXT, SELLER_CONCEDE, CardHand
from agent_m2m.format import aegis_text
from agent_m2m.persona import load_persona, reason
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


def negotiate(
    ask_units: int,
    budget_units: int,
    floor_ratio: float,
    on_turn: Callable[[dict[str, Any]], None] = lambda turn: None,
    buyer_cards: tuple[str, ...] = (),
    seller_cards: tuple[str, ...] = (),
    write_line: Callable[[str, str, int], str | None] = lambda role, card, price: None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """호가에서 시작해 합의가를 찾는다. floor_ratio 는 판매 에이전트만, persona 는 구매 에이전트만 쓴다(없으면 기본 페르소나).
    합의하면 합의가와 대화 기록을 돌려주고, 못 하면 NegotiationError. 대화가 한 줄 늘 때마다 on_turn 을 부른다."""
    persona = persona or load_persona()
    max_units = min(budget_units, ask_units)
    step = price_step(ask_units)
    seller = SellerAgent(ask_units, floor_ratio)
    transcript: list[dict[str, Any]] = []
    buyer_hand, seller_hand = CardHand(buyer_cards), CardHand(seller_cards)

    def say(speaker: str, action: str, price: int, text: str, card: str | None = None, why: dict[str, Any] | None = None) -> None:
        turn = {"from": speaker, "action": action, "priceUnits": price, "text": text}
        if card is not None:
            turn["card"] = card
        if why is not None:
            turn["reason"] = why
        transcript.append(turn)
        on_turn(turn)

    def result(status: str) -> dict[str, Any]:
        return {"status": status, "askUnits": ask_units, "maxUnits": max_units, "transcript": transcript}

    # 판매자가 마지막으로 낸 카드. 구매자는 이 카드로 양보 비율을 고른다.
    seller_card = {"card": "", "freshness": "none"}

    def offer_to_seller(price: int, text: str, why: dict[str, Any]) -> tuple[str, int]:
        _check_buyer_price(price, max_units)
        card, freshness = buyer_hand.play()
        say("buyer", "offer", price, write_line("buyer", card, price) or text, card, why)
        action, answer, reply = seller.reply_to_offer(price, SELLER_CONCEDE[freshness])
        if action == "counter":
            card, freshness = seller_hand.play()
            seller_card.update(card=card, freshness=freshness)
            say("seller", action, answer, write_line("seller", card, answer) or reply, card)
        else:
            say("seller", action, answer, reply)
        return action, answer

    try:
        offer = buyer_opening(ask_units, max_units, step, persona["openingRatio"])
        capped = " 최대가를 넘지 않게 그 값으로 낮췄습니다." if offer == max_units < ask_units * persona["openingRatio"] else ""
        why = reason(
            persona, "opening", f"호가 {aegis_text(ask_units)}의 {persona['openingRatio']:.0%}에서 시작합니다.{capped}",
            askUnits=ask_units, openingRatio=persona["openingRatio"], maxUnits=max_units,
        )
        action, price = offer_to_seller(offer, f"{aegis_text(ask_units)}에 올리셨네요. {aegis_text(offer)}에 주실 수 있나요?", why)
        rounds = 1
        while action == "counter":
            counter = price
            # 마지막 제안까지 값이 맞지 않았으면 판매자의 마지막 값이 최대가 이하일 때만 받는다.
            if rounds == MAX_ROUNDS and counter > max_units:
                why = reason(
                    persona, "over-max",
                    f"제안을 {MAX_ROUNDS}번 다 했는데 판매자 값 {aegis_text(counter)}가 최대가 {aegis_text(max_units)}(예산·호가 중 낮은 값)를 넘어 거절합니다.",
                    counterUnits=counter, maxUnits=max_units,
                )
                say("buyer", "reject", counter, f"{aegis_text(counter)}는 제 최대가를 넘어요. 이번에는 어렵겠어요.", why=why)
                action = "reject"
                break
            ratio = persona["concede"][seller_card["freshness"]]
            if seller_card["freshness"] == "none":
                heard = "판매자가 근거 카드 없이 값을 불러"
            else:
                heard = f"판매자가 '{seller_card['card']}' 카드({FRESHNESS_TEXT[seller_card['freshness']]})를 내서"
            inputs = {"card": seller_card["card"], "freshness": seller_card["freshness"], "ratio": ratio, "lastOfferUnits": offer, "counterUnits": counter}
            if rounds == MAX_ROUNDS:
                reply, value = "accept", counter
                why = reason(
                    persona, "last-round",
                    f"제안을 {MAX_ROUNDS}번 다 했고 판매자 값 {aegis_text(counter)}가 최대가 {aegis_text(max_units)} 이하라 받습니다.",
                    counterUnits=counter, maxUnits=max_units,
                )
            else:
                reply, value = buyer_reply(max_units, offer, counter, step, ratio)
                if reply == "accept":
                    why = reason(persona, "accept", f"{heard} 차이의 {ratio:.0%}를 올리면 판매자 값 {aegis_text(counter)}에 닿아 그 값에 받습니다.", **inputs)
                else:
                    if value == offer:
                        moved = f"올릴 몫이 값 단위 {aegis_text(step)}보다 작아 {aegis_text(value)}를 그대로 부릅니다."
                    else:
                        moved = f"올려 {aegis_text(value)}를 부릅니다."
                    capped = f" 최대가 {aegis_text(max_units)}에서 멈춥니다." if value == max_units else ""
                    why = reason(persona, "concede", f"{heard} 차이 {aegis_text(counter - offer)}의 {ratio:.0%}만큼 {moved}{capped}", **inputs)
            if reply == "accept":
                _check_buyer_price(value, max_units)
                say("buyer", "accept", value, f"좋아요, {aegis_text(value)}에 살게요.", why=why)
                action, price, text = seller.accept_counter(value)
                say("seller", action, price, text)
                break
            offer, rounds = value, rounds + 1
            action, price = offer_to_seller(offer, f"{aegis_text(counter)}는 조금 부담돼요. {aegis_text(offer)}면 바로 살게요.", why)
    except GuardrailError as error:
        raise NegotiationError(str(error), result("blocked")) from error

    if action != "accept":
        raise NegotiationError(f"흥정이 결렬돼 결제하지 않았습니다. 호가 {aegis_text(ask_units)}, 예산 {aegis_text(budget_units)}", result("no-deal"))
    return {**result("agreed"), "agreedUnits": price}
