import os
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from agent_m2m import store
from agent_m2m.audit import AFTER_PAYMENT_CHECKS, BEFORE_PAYMENT_CHECKS, AuditBlockedError
from agent_m2m.format import parse_aegis

RULE = "limit"


def _units(name: str, default: str) -> int:
    # 설정이 없거나 형식이 틀리면 기본값. 한도가 사라지면 안 되므로 None 을 그대로 쓰지 않는다.
    value = parse_aegis(os.environ.get(name, default))
    return value if value is not None else parse_aegis(default)


PER_PAYMENT_UNITS = _units("AUDIT_LIMIT_PER_PAYMENT", "0.5")
PER_DAY_UNITS = _units("AUDIT_LIMIT_PER_DAY", "3")
WARN_RATIO = float(os.environ.get("AUDIT_LIMIT_WARN_RATIO", "0.8"))


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_limit(ctx) -> None:
    amount = ctx.decision["winner"]["amountUnits"]
    user = ctx.request.get("userId") or "anonymous"
    db = store.database()

    if amount > PER_PAYMENT_UNITS:
        raise AuditBlockedError(RULE, f"1건 상한 초과: {amount} units")
    if amount > PER_DAY_UNITS:
        raise AuditBlockedError(RULE, f"하루 상한 초과: {amount} units")

    key = f"{user}:{_day()}"
    try:
        # 확인과 더하기를 한 명령으로: 조건에 맞을 때만 더한다.
        doc = db["limit_daily"].find_one_and_update(
            {"_id": key, "used": {"$lte": PER_DAY_UNITS - amount}},
            {"$inc": {"used": amount}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # 조건이 안 맞는데 upsert 가 같은 _id 로 새로 만들려다 실패 = 한도 초과
        raise AuditBlockedError(RULE, "하루 상한 초과") from None

    db["limit_reservations"].insert_one(
        {"_id": ctx.purchase_id, "key": key, "amount": amount, "released": False}
    )

    # 한도 임박 알림: 하루 한도의 WARN_RATIO 이상이면 결제마다 남긴다(결제는 진행)
    if doc["used"] / PER_DAY_UNITS >= WARN_RATIO:
        ctx.alert(RULE, f"한도 임박: 오늘 {doc['used']}/{PER_DAY_UNITS} units 사용")


def release_on_failure(ctx, record) -> None:
    # 돈이 나가기 전에 실패한 결제만 예약을 돌려준다. 같은 결제를 두 번 돌려주지 않는다.
    if record.get("status") != "FAILED" or record.get("failureStage") != "before-send":
        return
    db = store.database()
    res = db["limit_reservations"].find_one_and_update(
        {"_id": ctx.purchase_id, "released": False}, {"$set": {"released": True}}
    )
    if res:
        db["limit_daily"].update_one({"_id": res["key"]}, {"$inc": {"used": -res["amount"]}})


BEFORE_PAYMENT_CHECKS.append(check_limit)
AFTER_PAYMENT_CHECKS.append(release_on_failure)