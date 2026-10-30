"""
기록. 구매 한 건에 대해 요청·후보·점수·탈락 사유·금액·거래번호·결과를 남긴다.

MongoDB 컬렉션 하나(purchases)에 저장한다. API 는 DB에 직접 붙지 않고 이 모듈의 함수만 쓴다.
구매 기록은 결제 직전에 PROCESSING 으로 저장하고, 끝나면 그 문서의 상태와 결과만 고친다.
결정 근거(decision)는 처음 저장한 뒤로 고치지 않는다.

문서를 JSON 문자열로 뭉쳐 넣지 않고 그대로 넣는 이유는, 나중에 "같은 수신자에게 반복 결제",
"시간대별 묶기" 같은 질의를 DB에서 바로 돌리기 위해서다. 구매 번호를 `_id` 로 쓰므로
같은 번호를 두 번 저장하려 하면 DB가 거부한다.

구매 때 새로 받아 온 벤치마크 스냅샷은 snapshots 컬렉션에 해시를 `_id` 로 쌓는다.
결정 기록에는 해시만 남으므로, 그 해시로 "그때 본 숫자"를 다시 찾을 수 있다.

감사 규칙이 남긴 알림은 alerts 컬렉션에 덧붙인다.
감사 규칙이 자기 컬렉션이 필요하면 database() 로 같은 DB 를 받아 쓴다.
"""

import os
import threading
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

from agent_m2m.domain import AuditAlert, PurchaseRecord, now_iso

PURCHASES = "purchases"
SNAPSHOTS = "snapshots"
ALERTS = "alerts"

_client: MongoClient | None = None
_db: Database | None = None
_lock = threading.Lock()


def _db_name() -> str:
    return os.environ.get("MONGODB_DB", "agent_m2m")


def database() -> Database:
    """접속은 처음 부를 때 한 번 만든다. 최근 순 조회가 기본이라 정렬 기준에 색인을 둔다."""
    global _client, _db
    with _lock:
        if _db is None:
            _client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"))
            db = _client[_db_name()]
            db[PURCHASES].create_index([("createdAt", DESCENDING)])
            db[SNAPSHOTS].create_index([("capturedAt", DESCENDING)])
            db[ALERTS].create_index([("createdAt", DESCENDING)])
            _db = db
        return _db


def _to_record(document: dict[str, Any]) -> dict[str, Any]:
    """`_id` 에 들어간 번호를 id 로 돌려 놓는다."""
    record = dict(document)
    return {"id": record.pop("_id"), **record}


def _to_document(record: dict[str, Any]) -> dict[str, Any]:
    document = dict(record)
    return {"_id": document.pop("id"), **document}


def save_purchase(record: PurchaseRecord) -> None:
    database()[PURCHASES].insert_one(_to_document(record))


def update_purchase(purchase_id: str, outcome: dict[str, Any]) -> str:
    """결제 결과를 기록에 적고 바꾼 시각을 돌려준다. 결정 근거는 건드리지 않는다."""
    updated_at = now_iso()
    result = database()[PURCHASES].update_one({"_id": purchase_id}, {"$set": {**outcome, "updatedAt": updated_at}})
    if result.matched_count == 0:
        raise RuntimeError(f"구매 기록이 없습니다: {purchase_id}")
    return updated_at


def save_alert(alert: AuditAlert) -> None:
    database()[ALERTS].insert_one(_to_document(alert))


def list_alerts(limit: int = 50) -> list[AuditAlert]:
    cursor = database()[ALERTS].find({}, sort=[("createdAt", DESCENDING), ("_id", DESCENDING)], limit=limit)
    return [_to_record(document) for document in cursor]


def list_alerts_for_purchase(purchase_id: str) -> list[AuditAlert]:
    """구매 한 건에 달린 알림. 오래된 것부터."""
    cursor = database()[ALERTS].find({"purchaseId": purchase_id}, sort=[("createdAt", ASCENDING), ("_id", ASCENDING)])
    return [_to_record(document) for document in cursor]


def count_alerts() -> dict[str, int]:
    """전체 알림을 차단과 경고로 나눠 센다. blocked 칸이 없는 옛 알림은 경고로 센다."""
    collection = database()[ALERTS]
    blocked = collection.count_documents({"blocked": True})
    total = collection.count_documents({})
    return {"blocked": blocked, "warnings": total - blocked}


def existing_purchase_ids(ids: list[str]) -> set[str]:
    """주어진 구매 번호 중 실제 기록이 있는 것. 요청 직후에 막힌 알림은 기록이 없어 링크를 달지 않는다."""
    if not ids:
        return set()
    cursor = database()[PURCHASES].find({"_id": {"$in": ids}}, projection={"_id": 1})
    return {document["_id"] for document in cursor}


def list_purchases(limit: int = 50) -> list[PurchaseRecord]:
    cursor = database()[PURCHASES].find({}, sort=[("createdAt", DESCENDING), ("_id", DESCENDING)], limit=limit)
    return [_to_record(document) for document in cursor]


def get_purchase(purchase_id: str) -> PurchaseRecord | None:
    document = database()[PURCHASES].find_one({"_id": purchase_id})
    return None if document is None else _to_record(document)


def purchase_exists(purchase_id: str) -> bool:
    """같은 구매 번호로 결제가 두 번 일어나지 않게 하는 확인."""
    return database()[PURCHASES].count_documents({"_id": purchase_id}, limit=1) > 0


def save_snapshot(snapshot_hash: str, snapshot: dict[str, Any]) -> None:
    """같은 해시가 이미 있으면 그대로 둔다(덧붙이기만)."""
    database()[SNAPSHOTS].update_one(
        {"_id": snapshot_hash},
        {"$setOnInsert": {"capturedAt": snapshot["capturedAt"], "snapshot": snapshot}},
        upsert=True,
    )


def latest_snapshot() -> dict[str, Any] | None:
    """가장 최근에 받아 온 스냅샷 {snapshot, hash}. 아직 한 번도 받지 않았으면 None."""
    document = database()[SNAPSHOTS].find_one({}, sort=[("capturedAt", DESCENDING)])
    return None if document is None else {"snapshot": document["snapshot"], "hash": document["_id"]}


def drop_test_database() -> None:
    """테스트가 쓰고 버리는 데이터베이스를 지울 때 쓴다. 이름이 테스트용일 때만 지운다."""
    name = _db_name()
    if not name.startswith("agent_m2m_test"):
        raise RuntimeError(f"테스트 데이터베이스가 아닙니다: {name}")
    database().client.drop_database(name)


def is_connected() -> bool:
    return _db is not None


def close_store() -> None:
    """테스트가 연결을 정리할 때 쓴다. 앱 실행 중에는 부르지 않는다."""
    global _client, _db
    with _lock:
        client, _client, _db = _client, None, None
    if client is not None:
        client.close()
