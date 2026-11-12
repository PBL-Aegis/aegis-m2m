"""
시나리오 ③ · 판매자 담합. 판매 에이전트들이 서로 깎지 않아 구매자가 비싸게 사는 것을 여러 건의 기록으로 드러낸다.

등급마다 비교하는 판매자가 몇 곳뿐이라, 모두가 최저가 비율(floorRatio)을 올리거나 양보를 멈추면 경쟁이 사라진다.
한 건만 보면 "각자 세게 흥정한 것"과 구분할 수 없어서 막지 않고 알림만 남긴다. 결제가 끝난 뒤(SETTLED) 돈다.

기준선은 재계산이다. 흥정 값은 코드가 계산해서 입력이 같으면 결과도 같다(strategy.py). 그래서 같은 흥정을
판매자가 기준 최저가 비율(AUDIT_COLLUSION_REFERENCE_FLOOR)로 응했다면 얼마였을지 다시 돌려 본다.
같은 호가·예산·근거 카드·페르소나로 돌리므로 페르소나나 모델 차이는 빠지고, 판매자가 기준보다 덜 깎은 만큼만 남는다.
판매자의 실제 최저가 비율은 판매자만 아는 값이라 읽지 않는다.

  gap = (판매자가 마지막에 부른 값 - 기준으로 다시 돌린 값) / 호가

낙찰되지 않은 판매자의 값도 기록에 있어서(decision["quotes"]) 비교한 판매자 모두를 매 건 본다.
"최근 N건"은 그 등급의 최근 구매 N건이다. 알림 세 가지(규칙 이름은 모두 seller-collusion):

  가격 맞추기   등급의 판매자 모두 최근 N건 평균 gap 이 AUDIT_COLLUSION_GAP 이상.
               한 곳만 올리면 구매자가 다른 곳에서 사므로 손해가 아니다. 모두 올려야 담합이다.
  같이 오름     판매자 모두 최근 N건 평균 gap 이 그 앞 N건보다 AUDIT_COLLUSION_RISE 이상 올랐다.
  시장 나누기   가격 맞추기가 걸린 두 등급에서 최근 N건 중 AUDIT_COLLUSION_SHARE 이상을 이긴 판매자가 서로 다르다.
               싸서 늘 이기는 것만으로는 걸리지 않는다. 그 등급에서 아무도 깎지 않아야 한다.

"두 판매자의 양보 패턴이 비슷함"은 보지 않는다. 판매자의 양보 폭은 구매자가 낸 근거 카드가 정해서(cards.py) 늘 같다.

  collusion_quotes  구매 한 건의 판매자 한 곳마다 한 문서(_id = 구매 번호:모델). 알림만 내므로 확인과 기록을 한 명령으로
                    묶지 않는다. 동시에 들어온 구매끼리는 서로의 기록을 못 볼 수 있지만, 다음 구매가 다시 센다.
"""

import os
import time
from statistics import fmean
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from agent_m2m import store
from agent_m2m.audit import AFTER_PAYMENT_CHECKS, AuditContext
from agent_m2m.cards import buyer_cards, seller_cards
from agent_m2m.domain import PurchaseRecord, now_iso
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.persona import load_persona

RULE = "seller-collusion"
QUOTES = "collusion_quotes"
PRIORITY_LABEL = {"price": "싸게", "default": "기본", "intelligence": "똑똑하게"}
GAP_DIGITS = 3


def _ratio(name: str, fallback: str) -> float:
    text = os.environ.get(name, fallback).strip()
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 < value <= 1:
        raise ValueError(f"{name} 는 0 초과 1 이하의 비율이어야 합니다 (예: {fallback})")
    return value


def _positive_integer(name: str, fallback: str) -> int:
    text = os.environ.get(name, fallback).strip()
    if not text.isdecimal() or int(text) < 1:
        raise ValueError(f"{name} 는 1 이상의 정수여야 합니다 (예: {fallback})")
    return int(text)


# 숫자는 코드에 박지 않고 설정값으로 둔다. 테스트는 monkeypatch.setattr(collusion, "상수이름", ...) 로 바꾼다.
REFERENCE_FLOOR_RATIO = _ratio("AUDIT_COLLUSION_REFERENCE_FLOOR", "0.8")
WINDOW = _positive_integer("AUDIT_COLLUSION_WINDOW", "5")
GAP = _ratio("AUDIT_COLLUSION_GAP", "0.1")
RISE = _ratio("AUDIT_COLLUSION_RISE", "0.05")
SHARE = _ratio("AUDIT_COLLUSION_SHARE", "0.8")


def _now() -> float:
    """기록 순서를 정하는 시각(초). createdAt 은 밀리초라 같은 값이 나올 수 있다."""
    return time.time()


def _collection() -> Collection:
    collection = store.database()[QUOTES]
    collection.create_index([("priority", ASCENDING), ("seller", ASCENDING), ("at", DESCENDING)])
    return collection


def _last_seller_price(transcript: list[dict[str, Any]]) -> int | None:
    prices = [turn["priceUnits"] for turn in transcript if turn["from"] == "seller"]
    return prices[-1] if prices else None


def _reference_price(quote: dict[str, Any], model: dict[str, Any], rival: dict[str, Any] | None, budget_units: int, persona: dict[str, Any]) -> int | None:
    """판매자가 기준 최저가 비율로 응했다면 마지막에 부른 값. 대사는 만들지 않는다(값만 계산)."""
    try:
        result = negotiate(
            quote["askUnits"],
            budget_units,
            REFERENCE_FLOOR_RATIO,
            buyer_cards=buyer_cards(model, rival),
            seller_cards=seller_cards(model, rival),
            persona=persona,
        )
    except NegotiationError as error:
        result = error.negotiation
    return _last_seller_price(result["transcript"])


def _quote_documents(ctx: AuditContext) -> list[dict[str, Any]]:
    """비교한 판매자마다 실제 값과 기준 값. shop() 이 흥정한 순서·상대를 그대로 다시 짝짓는다."""
    decision = ctx.decision
    quotes = decision.get("quotes") or []
    by_key = {candidate["key"]: candidate for candidate in decision["candidates"]}
    models = [by_key[quote["key"]] for quote in quotes]
    persona = load_persona(decision["persona"]["id"])
    at, created_at = _now(), now_iso()
    documents = []
    for quote, model in zip(quotes, models):
        rival = next((other for other in models if other is not model), None)
        actual = _last_seller_price(quote.get("transcript") or [])
        reference = _reference_price(quote, model, rival, decision["budgetUnits"], persona)
        if actual is None or reference is None:
            continue
        ask = quote["askUnits"]
        documents.append(
            {
                "_id": f"{ctx.purchase_id}:{quote['key']}",
                "purchaseId": ctx.purchase_id,
                "priority": ctx.request["priority"],
                "seller": model["providerId"],
                "sellerName": quote["sellerName"],
                "model": quote["key"],
                "personaId": persona["id"],
                "won": quote["key"] == decision["winner"]["key"],
                "askUnits": ask,
                "priceUnits": actual,
                "referenceUnits": reference,
                "ratio": actual / ask,
                "referenceRatio": reference / ask,
                # 최저가를 값 단위로 올려 맞추느라 0.9 - 0.8 이 0.09997 처럼 나온다. 0.1%p 단위로 맞춰 기준값과 비교한다.
                "gap": round((actual - reference) / ask, GAP_DIGITS),
                "at": at,
                "createdAt": created_at,
            }
        )
    return documents


def _gaps(priority: str, seller: str, skip: int = 0) -> list[float]:
    cursor = _collection().find({"priority": priority, "seller": seller}, sort=[("at", DESCENDING)], skip=skip, limit=WINDOW)
    return [document["gap"] for document in cursor]


def _fixed_prices(priority: str, sellers: dict[str, str]) -> dict[str, float] | None:
    """판매자 모두 최근 N건 평균 gap 이 GAP 이상이면 {판매자 이름: 평균}. 한 곳이라도 아니거나 N건이 안 되면 None."""
    if len(sellers) < 2:
        return None
    means = {}
    for seller, name in sellers.items():
        gaps = _gaps(priority, seller)
        if len(gaps) < WINDOW or fmean(gaps) < GAP:
            return None
        means[name] = fmean(gaps)
    return means


def _rising(priority: str, sellers: dict[str, str]) -> dict[str, float] | None:
    """판매자 모두 최근 N건 평균 gap 이 그 앞 N건보다 RISE 이상 올랐으면 {판매자 이름: 오른 폭}."""
    if len(sellers) < 2:
        return None
    rises = {}
    for seller, name in sellers.items():
        recent, earlier = _gaps(priority, seller), _gaps(priority, seller, skip=WINDOW)
        if len(recent) < WINDOW or len(earlier) < WINDOW or fmean(recent) - fmean(earlier) < RISE:
            return None
        rises[name] = fmean(recent) - fmean(earlier)
    return rises


def _sellers_in(priority: str) -> dict[str, str]:
    """이 등급의 가장 최근 구매에서 비교한 판매자 {회사: 이름}."""
    latest = _collection().find_one({"priority": priority}, sort=[("at", DESCENDING)])
    if latest is None:
        return {}
    documents = _collection().find({"purchaseId": latest["purchaseId"]})
    return {document["seller"]: document["sellerName"] for document in documents}


def _dominant_winner(priority: str) -> tuple[str, float] | None:
    """최근 N건 중 SHARE 이상을 이긴 판매자 이름과 그 비율."""
    wins = [document["sellerName"] for document in _collection().find({"priority": priority, "won": True}, sort=[("at", DESCENDING)], limit=WINDOW)]
    if len(wins) < WINDOW:
        return None
    name = max(set(wins), key=wins.count)
    share = wins.count(name) / len(wins)
    return (name, share) if share >= SHARE else None


def _points(value: float) -> str:
    return f"{value * 100:+.0f}%p"


def _list(values: dict[str, float]) -> str:
    return ", ".join(f"{name} {_points(value)}" for name, value in values.items())


def check_collusion(ctx: AuditContext, record: PurchaseRecord) -> None:
    if record.get("status") != "SETTLED":
        return
    documents = _quote_documents(ctx)
    if not documents:
        return
    _collection().insert_many(documents)

    priority = ctx.request["priority"]
    label = PRIORITY_LABEL.get(priority, priority)
    sellers = {document["seller"]: document["sellerName"] for document in documents}
    reference = f"최저가 비율 {REFERENCE_FLOOR_RATIO:g}로 응했다면 받았을 값"

    fixed = _fixed_prices(priority, sellers)
    if fixed:
        ctx.alert(
            RULE,
            f"담합 의심(가격 맞추기): '{label}' 등급 최근 {WINDOW}건에서 비교한 판매자 모두 {reference}보다 "
            f"호가 대비 평균 {_points(GAP)} 이상 더 받았습니다: {_list(fixed)}. 한 곳만 비싸면 다른 곳에서 사므로, 모두 덜 깎은 것이 손해의 원인입니다.",
        )

    rising = _rising(priority, sellers)
    if rising:
        ctx.alert(
            RULE,
            f"담합 의심(같이 오름): '{label}' 등급에서 비교한 판매자 모두 최근 {WINDOW}건이 그 앞 {WINDOW}건보다 "
            f"{reference}과의 차이가 {_points(RISE)} 이상 커졌습니다: {_list(rising)}",
        )

    if not fixed:
        return
    here = _dominant_winner(priority)
    if here is None:
        return
    for other in PRIORITY_LABEL:
        if other == priority or not _fixed_prices(other, _sellers_in(other)):
            continue
        there = _dominant_winner(other)
        if there is not None and there[0] != here[0]:
            ctx.alert(
                RULE,
                f"담합 의심(시장 나누기): 아무도 깎지 않는 두 등급에서 이기는 판매자가 갈립니다. "
                f"'{label}'은 {here[0]}({here[1]:.0%}), '{PRIORITY_LABEL[other]}'은 {there[0]}({there[1]:.0%})가 최근 {WINDOW}건을 가져갔습니다.",
            )


AFTER_PAYMENT_CHECKS.append(check_collusion)
