"""
양보 규칙. 다음에 부를 값을 정하는 고정 계산이다(LLM 없음). 입력이 같으면 결과도 항상 같다.

각자 상대가 지난번에 간격을 얼마나 좁혔는지 보고, 비슷한 비율로 따라 좁힌다. 많이 양보하는 상대에게는 많이,
버티는 상대에게는 적게 양보한다. 비율은 각자의 하한·상한 안에서만 움직인다.

판매자: 호가에서 시작한다. 첫 답에서는 간격의 SELLER_FIRST 만큼 내리고, 그 뒤로는 구매자를 따라 좁힌다.
        최저가 아래로는 안 내린다.
구매자: 호가의 OPENING_RATIO 에서 시작해, 판매자를 따라 좁힌다.
        마지막 차례에는 판매자가 호가에서 내려온 만큼만 최대가 쪽으로 올린다. 호가의 REQUIRED_DISCOUNT 이상
        내려왔으면 최대가까지 부르고, 전혀 안 내려왔으면 더 올리지 않는다. 그래서 버티기만 하는 판매자에게서는
        최대가 안쪽이어도 사지 않는다.
값은 호가 크기에 맞춘 단위(price_step)로 맞추고, 각자 자기에게 유리한 쪽으로 반올림한다.
"""

import math

# 구매자가 값을 부를 수 있는 횟수. 마지막 차례에 판매자는 받거나 거절해야 한다.
MAX_ROUNDS = 5
OPENING_RATIO = 0.6
SELLER_FIRST = 0.4
# 하한이 크면 버티는 상대에게 오히려 더 많이 주게 된다. 간격이 줄지 않아 같은 비율이어도 움직이는 금액이 크기 때문이다.
SELLER_RATIO_RANGE = (0.1, 0.5)
BUYER_RATIO_RANGE = (0.1, 0.6)
REQUIRED_DISCOUNT = 0.1
# 값을 맞출 때 남기는 유효숫자 수. 모델 가격은 건마다 자릿수가 달라 고정 단위를 쓰면 작은 금액이 0 으로 내려간다.
PRICE_DIGITS = 3


def price_step(ask_units: int) -> int:
    """호가에 맞는 값 단위. 12,960 units 면 100, 400,000 units 면 1,000 이다."""
    return max(1, 10 ** (len(str(ask_units)) - PRICE_DIGITS))


def round_up(units: float, step: int) -> int:
    return math.ceil(units / step) * step


def round_down(units: float, step: int) -> int:
    return math.floor(units / step) * step


def matched_ratio(moved: int, gap: int, ratio_range: tuple[float, float]) -> float:
    """상대가 간격(gap) 중 얼마나 좁혔는지(moved)를 비율로 바꿔 내 범위 안에 맞춘다."""
    low, high = ratio_range
    return min(high, max(low, moved / gap)) if gap > 0 else low


def seller_reply(
    floor_units: int, last_counter: int, offer: int, round_no: int, prev_offer: int | None, step: int
) -> tuple[str, int]:
    """구매자의 round_no 번째 제안(offer)에 답한다. last_counter 는 판매자가 마지막으로 부른 값(처음엔 호가),
    prev_offer 는 구매자의 바로 앞 제안(첫 제안이면 None)."""
    if offer >= last_counter:
        return "accept", offer
    if round_no >= MAX_ROUNDS:
        return ("accept", offer) if offer >= floor_units else ("reject", last_counter)
    if prev_offer is None:
        ratio = SELLER_FIRST
    else:
        ratio = matched_ratio(offer - prev_offer, last_counter - prev_offer, SELLER_RATIO_RANGE)
    counter = max(floor_units, round_up(last_counter - (last_counter - offer) * ratio, step))
    if counter <= offer:
        return "accept", offer
    return "counter", counter


def buyer_opening(ask_units: int, max_units: int, step: int) -> int:
    return min(max_units, round_down(ask_units * OPENING_RATIO, step))


def buyer_reply(
    max_units: int, last_offer: int, counter: int, next_round: int, prev_counter: int, ask_units: int, step: int
) -> tuple[str, int]:
    """판매자가 부른 값(counter)에 답한다. next_round 는 구매자가 이번에 보내면 몇 번째 제안인지,
    prev_counter 는 판매자가 그 앞에 부른 값(처음엔 호가)."""
    # 판매자는 MAX_ROUNDS 번째 제안에 받거나 거절하므로, 구매자가 그 뒤에 답할 일은 없다.
    if counter <= last_offer:
        return "accept", counter
    if next_round == MAX_ROUNDS:
        earned = min(1.0, (ask_units - counter) / (ask_units * REQUIRED_DISCOUNT))
        offer = max(last_offer, round_down(last_offer + (max_units - last_offer) * earned, step))
    else:
        ratio = matched_ratio(prev_counter - counter, prev_counter - last_offer, BUYER_RATIO_RANGE)
        offer = min(max_units, round_down(last_offer + (counter - last_offer) * ratio, step))
    if offer >= counter:
        return "accept", counter
    return "offer", offer
