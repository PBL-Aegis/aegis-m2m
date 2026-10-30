"""
감사 규칙. 구매 한 건에서 세 번 돈다.

  ON_REQUEST_CHECKS     요청이 들어오자마자. 모델을 고르기 전이고 기록도 아직 없다.
                        이전 기록을 돌려주면 새로 처리하지 않고 그 기록을 그대로 응답한다.
  BEFORE_PAYMENT_CHECKS 모델을 고르고 처리 중 기록을 남긴 뒤, 송금 직전.
  AFTER_PAYMENT_CHECKS  결과(성공·실패)를 기록한 뒤. 예약해 둔 한도를 되돌리는 일 등을 한다.

규칙은 agent_m2m/rules/ 에 파일로 두고, 그 파일이 맞는 목록에 함수 하나를 append 한다(rules/__init__.py 에서 불러옴).
막을 때는 AuditBlockedError 를 던지고, 결제는 진행하되 알리기만 할 때는 ctx.alert 를 부른다.
규칙이 막으면 여기서 "차단" 알림을 자동으로 남긴다. 그래서 막힌 거래는 규칙이 따로 알리지 않아도
대시보드의 이상 거래에 뜬다.
체인에서 다시 막는 검사는 여기가 아니라 contracts/src/rules/ 에 둔다.
체인에서는 구매자 지갑 하나를 사용자 한 명으로 본다.

요청은 여러 개가 동시에 처리된다(스레드). 규칙이 공유 상태를 바꾸면 "확인"과 "기록"을 MongoDB 명령 하나로 같이 한다.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_m2m import store
from agent_m2m.domain import Decision, PurchaseRecord, now_iso


class AuditBlockedError(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


@dataclass
class RequestContext:
    """요청 직후의 문맥. request 의 priority 는 아직 비어 있을 수 있다."""

    purchase_id: str
    request: dict[str, Any]
    alert: Callable[[str, str], None]
    """결제를 막지 않는 알림을 남긴다. ctx.alert(규칙 이름, 메시지)."""


@dataclass
class AuditContext:
    """송금 직전·결제 후의 문맥. decision 에 고른 모델·금액·점수가 있다."""

    purchase_id: str
    request: dict[str, Any]
    decision: Decision
    alert: Callable[[str, str], None]
    """결제를 막지 않는 알림을 남긴다. ctx.alert(규칙 이름, 메시지)."""


# 이전 기록을 돌려주면 새로 처리하지 않는다.
RequestCheck = Callable[[RequestContext], PurchaseRecord | None]
AuditCheck = Callable[[AuditContext], None]
# record 는 상태가 SETTLED 나 FAILED 로 확정된 기록이다.
AfterPaymentCheck = Callable[[AuditContext, PurchaseRecord], None]

ON_REQUEST_CHECKS: list[RequestCheck] = []
BEFORE_PAYMENT_CHECKS: list[AuditCheck] = []
AFTER_PAYMENT_CHECKS: list[AfterPaymentCheck] = []


def _save_stage_alert(purchase_id: str, request: dict[str, Any], stage: str, blocked: bool, rule: str, message: str) -> None:
    store.save_alert(
        {
            "id": str(uuid.uuid4()),
            "createdAt": now_iso(),
            "purchaseId": purchase_id,
            "userId": request.get("userId"),
            "requestId": request.get("requestId"),
            "stage": stage,
            "blocked": blocked,
            "rule": rule,
            "message": message,
        }
    )


def _alerting(purchase_id: str, request: dict[str, Any], stage: str) -> Callable[[str, str], None]:
    return lambda rule, message: _save_stage_alert(purchase_id, request, stage, False, rule, message)


def _record_block(purchase_id: str, request: dict[str, Any], stage: str, run: Callable[[], Any]) -> Any:
    """규칙이 막으면 차단 알림을 남기고 그대로 다시 던진다."""
    try:
        return run()
    except AuditBlockedError as error:
        _save_stage_alert(purchase_id, request, stage, True, error.rule, str(error))
        raise


def run_on_request(purchase_id: str, request: dict[str, Any], checks: list[RequestCheck] | None = None) -> PurchaseRecord | None:
    """등록 순서대로 돌다가 이전 기록을 돌려준 규칙이 있으면 그 기록을 돌려준다."""
    ctx = RequestContext(purchase_id, request, _alerting(purchase_id, request, "on-request"))
    for check in ON_REQUEST_CHECKS if checks is None else checks:
        previous = _record_block(purchase_id, request, "on-request", lambda: check(ctx))
        if previous:
            return previous
    return None


def run_before_payment(purchase_id: str, request: dict[str, Any], decision: Decision, checks: list[AuditCheck] | None = None) -> None:
    ctx = AuditContext(purchase_id, request, decision, _alerting(purchase_id, request, "before-payment"))
    for check in BEFORE_PAYMENT_CHECKS if checks is None else checks:
        _record_block(purchase_id, request, "before-payment", lambda: check(ctx))


def run_after_payment(
    purchase_id: str,
    request: dict[str, Any],
    decision: Decision,
    record: PurchaseRecord,
    checks: list[AfterPaymentCheck] | None = None,
) -> None:
    """결과가 이미 기록된 뒤라 여기서 실패해도 결과를 바꾸지 않는다. 실패는 알림으로 남기고 다음 규칙을 돈다."""
    ctx = AuditContext(purchase_id, request, decision, _alerting(purchase_id, request, "after-payment"))
    for check in AFTER_PAYMENT_CHECKS if checks is None else checks:
        try:
            check(ctx, record)
        except Exception as error:  # noqa: BLE001
            ctx.alert("after-payment", f"결제 후 규칙이 실패했습니다: {error or '알 수 없는 오류'}")
