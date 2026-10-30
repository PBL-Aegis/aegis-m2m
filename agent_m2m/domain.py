"""
이 프로젝트에서 쓰는 고정 값과 기록의 모양.

기록(구매·결정·결제·알림)은 MongoDB 문서와 API 응답이 같은 모양이 되도록 camelCase 키를 가진 dict 로 다룬다.
칸 하나하나의 뜻은 화면 쪽 web/src/lib/types.ts 에 적혀 있고, 서버와 화면이 같은 이름을 쓴다.
"""

from datetime import datetime, timezone
from typing import Any

# 요청이 무엇을 중요하게 보는지. 이 네 값이 가중치 한 줄을 고른다.
PRIORITIES: tuple[str, ...] = ("default", "price", "speed", "intelligence")

# 우선순위마다 고정된 배점표(가격·시간·지능, 합 100). 코드 밖에서 바꿀 수 없다.
PRIORITY_WEIGHTS: dict[str, dict[str, int]] = {
    "default": {"price": 34, "time": 33, "intelligence": 33},
    "price": {"price": 80, "time": 10, "intelligence": 10},
    "speed": {"price": 10, "time": 80, "intelligence": 10},
    "intelligence": {"price": 10, "time": 10, "intelligence": 80},
}

# 구매 기록·결정·결제 결과·알림. 모양은 web/src/lib/types.ts 의 같은 이름 타입을 따른다.
PurchaseRecord = dict[str, Any]
Decision = dict[str, Any]
PaymentResult = dict[str, Any]
AuditAlert = dict[str, Any]


def now_iso() -> str:
    """지금 시각을 2026-10-30T10:03:43.512Z 모양(UTC, 밀리초)으로."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso_ms(text: str) -> float:
    """ISO 시각 → 1970년부터의 밀리초."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000
