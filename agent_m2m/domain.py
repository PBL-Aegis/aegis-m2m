"""
이 프로젝트에서 쓰는 고정 값과 기록의 모양.

기록(구매·결정·결제·알림)은 MongoDB 문서와 API 응답이 같은 모양이 되도록 camelCase 키를 가진 dict 로 다룬다.
칸 하나하나의 뜻은 화면 쪽 web/src/lib/types.ts 에 적혀 있고, 서버와 화면이 같은 이름을 쓴다.
"""

from datetime import datetime, timezone
from typing import Any

# 요청이 무엇을 중요하게 보는지. 이 세 값이 비교 모델을 고른다.
PRIORITIES: tuple[str, ...] = ("default", "price", "intelligence")

# 구매 기록·결정·결제 결과·알림. 모양은 web/src/lib/types.ts 의 같은 이름 타입을 따른다.
PurchaseRecord = dict[str, Any]
Decision = dict[str, Any]
PaymentResult = dict[str, Any]
AuditAlert = dict[str, Any]


def now_iso() -> str:
    """지금 시각을 2026-10-30T10:03:43.512Z 모양(UTC, 밀리초)으로."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

