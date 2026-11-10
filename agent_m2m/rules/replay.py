"""
반복 구매 막기. 같은 요청 번호의 재결제는 체인이 막는다. settleDeal 은 같은 요청 번호의 합의를 한 번만 받고
(DealAlreadySettled), 서명 nonce 도 한 번만 쓰인다. 짧은 시간 결제 횟수는 contracts/src/rules/ReplayRule.sol 이 막는다.
서버는 요청 번호를 따로 기억하지 않는다. 같은 번호를 다시 보내면 새로 흥정하고, 체인에서 막혀 송금 전 실패로 남는다.

  duplicate-purchase  에이전트 반복 루프. 한 사용자가 같은 문장으로 같은 모델을 창(기본 60초) 안에 기본 3번째 사려 하면,
                      요청 번호가 달라도 송금 직전에 멈춘다. 같은 결과를 또 사는 것이라서다.
                      송금 전에 실패한 건은 돈이 나가지 않았으니 횟수에서 뺀다. 사용자가 없는 요청은 한 사용자로 묶어 센다.
                      같은 문장만 반복하는 것은 막지 않는다. 에이전트는 일괄 작업에서 같은 문장을 정상적으로 다시 보낸다.

"확인"과 "기록"은 MongoDB 명령 하나로 같이 한다.

  replay_purchases    사용자·문장·모델별 구매 횟수 창. 창 시작 시각과 그 안의 횟수를 문서 하나에서 함께 바꾼다.
  replay_holds        구매 한 건이 어느 창에 횟수를 더했는지. 송금 전에 실패하면 이것을 보고 한 번만 뺀다.

두 컬렉션 모두 expiresAt 이 지나면 MongoDB 의 TTL index 가 문서를 지운다(약 1분 간격으로 돈다).
"""

import hashlib
import os
import time
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection

from agent_m2m import store
from agent_m2m.audit import AFTER_PAYMENT_CHECKS, BEFORE_PAYMENT_CHECKS, AuditBlockedError, AuditContext
from agent_m2m.domain import PurchaseRecord


def _positive_integer(name: str, fallback: str) -> int:
    text = os.environ.get(name, fallback)
    if not text.isdecimal() or int(text) < 1:
        raise ValueError(f"{name} 는 1 이상의 정수여야 합니다 (예: {fallback})")
    return int(text)


# 숫자는 코드에 박지 않고 설정값으로 둔다.
REPEAT_COUNT = _positive_integer("AUDIT_REPEAT_COUNT", "3")
REPEAT_WINDOW_SECONDS = _positive_integer("AUDIT_REPEAT_WINDOW_SECONDS", "60")

PURCHASES = "replay_purchases"
HOLDS = "replay_holds"
# 사용자가 없는 요청을 묶어 셀 때 쓰는 이름.
ANONYMOUS = "(사용자 없음)"


def _now() -> float:
    """지금 시각(초). 테스트가 시계를 돌릴 수 있게 함수로 둔다."""
    return time.time()


def _expires_at(now: float, seconds: int) -> datetime:
    return datetime.fromtimestamp(now + seconds, UTC)


def _collection(name: str) -> Collection:
    collection = store.database()[name]
    collection.create_index("expiresAt", expireAfterSeconds=0)
    return collection


def _count_purchase(key: str, now: float) -> dict[str, Any]:
    """
    같은 구매 한 번을 창에 더하고, 더한 뒤의 창 문서(windowStart·count)를 돌려준다.
    창이 없거나 시작한 지 창 길이가 지났으면 지금부터 새 창을 연다.
    """
    fresh = {
        "$or": [
            {"$eq": [{"$type": "$windowStart"}, "missing"]},
            {"$lte": ["$windowStart", now - REPEAT_WINDOW_SECONDS]},
        ]
    }
    return _collection(PURCHASES).find_one_and_update(
        {"_id": key},
        [
            {
                "$set": {
                    "windowStart": {"$cond": [fresh, now, "$windowStart"]},
                    "count": {"$cond": [fresh, 1, {"$add": ["$count", 1]}]},
                    "expiresAt": _expires_at(now, REPEAT_WINDOW_SECONDS),
                }
            }
        ],
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def _check_duplicate_purchase(ctx: AuditContext) -> None:
    user = ctx.request["userId"] or ANONYMOUS
    prompt_hash = hashlib.sha256(ctx.request["prompt"].strip().encode()).hexdigest()
    model = ctx.decision["winner"]["key"]
    key = f"{user}:{prompt_hash}:{model}"
    now = _now()
    window = _count_purchase(key, now)
    _collection(HOLDS).insert_one(
        {"_id": ctx.purchase_id, "key": key, "windowStart": window["windowStart"], "expiresAt": _expires_at(now, REPEAT_WINDOW_SECONDS)}
    )
    if window["count"] < REPEAT_COUNT:
        return
    raise AuditBlockedError(
        "duplicate-purchase",
        f"같은 문장으로 같은 모델({ctx.decision['winner']['displayName']})을 {REPEAT_WINDOW_SECONDS}초 안에 "
        f"{window['count']}번째 사려 해서 멈췄습니다. 에이전트 반복 루프일 수 있습니다: {user}",
    )


def _release_on_failure(ctx: AuditContext, record: PurchaseRecord) -> None:
    """송금 전에 실패한 구매는 더한 횟수를 한 번만 뺀다. 그사이 새 창이 열렸으면 빼지 않는다."""
    if record.get("status") != "FAILED" or record.get("failureStage") != "before-send":
        return
    hold = _collection(HOLDS).find_one_and_delete({"_id": ctx.purchase_id})
    if hold:
        _collection(PURCHASES).update_one(
            {"_id": hold["key"], "windowStart": hold["windowStart"], "count": {"$gt": 0}}, {"$inc": {"count": -1}}
        )


BEFORE_PAYMENT_CHECKS.append(_check_duplicate_purchase)
AFTER_PAYMENT_CHECKS.append(_release_on_failure)
