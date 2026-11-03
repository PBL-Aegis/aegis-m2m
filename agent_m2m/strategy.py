"""
양보 규칙. 다음에 부를 값을 정하는 고정 계산이다(LLM 없음). 입력이 같으면 결과도 항상 같다.

구매자: 호가의 OPENING_RATIO 에서 시작해, 판매자 값과의 차이의 절반만큼 올린다. 최대가를 넘지 않는다.
판매자: 호가에서 시작해, 구매자 제안과의 차이의 절반만큼 내린다. 최저가 아래로 내리지 않는다.
구매자는 최대 MAX_ROUNDS 번 제안한다. 그때까지 값이 맞지 않으면 판매자의 마지막 값이 최대가 이하일 때 구매자가 받고,
넘으면 결렬이다.
값은 호가 크기에 맞춘 단위(price_step)로 맞추고, 각자 자기에게 유리한 쪽으로 반올림한다.
"""

import math

MAX_ROUNDS = 5
OPENING_RATIO = 0.75
# 값을 맞출 때 남기는 유효숫자 수. 모델 가격은 건마다 자릿수가 달라 고정 단위를 쓰면 작은 금액이 0 으로 내려간다.
PRICE_DIGITS = 3


def price_step(ask_units: int) -> int:
    """호가에 맞는 값 단위. 12,960 units 면 100, 400,000 units 면 1,000 이다."""
    return max(1, 10 ** (len(str(ask_units)) - PRICE_DIGITS))


def round_up(units: float, step: int) -> int:
    return math.ceil(units / step) * step


def round_down(units: float, step: int) -> int:
    return math.floor(units / step) * step


def seller_reply(floor_units: int, last_counter: int, offer: int, step: int) -> tuple[str, int]:
    """구매자의 제안(offer)에 답한다. last_counter 는 판매자가 마지막으로 부른 값(처음엔 호가)."""
    if offer >= last_counter:
        return "accept", offer
    counter = max(floor_units, round_up(last_counter - (last_counter - offer) / 2, step))
    if counter <= offer:
        return "accept", offer
    return "counter", counter


def buyer_opening(ask_units: int, max_units: int, step: int) -> int:
    return min(max_units, round_down(ask_units * OPENING_RATIO, step))


def buyer_reply(max_units: int, last_offer: int, counter: int, step: int) -> tuple[str, int]:
    """판매자가 부른 값(counter)에 답한다. 다음 제안이 판매자 값에 닿으면 그 값을 받는다."""
    if counter <= last_offer:
        return "accept", counter
    offer = min(max_units, round_down(last_offer + (counter - last_offer) / 2, step))
    if offer >= counter:
        return "accept", counter
    return "offer", offer
