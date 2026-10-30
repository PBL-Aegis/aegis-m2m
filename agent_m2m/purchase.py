"""
구매 한 건의 전체 흐름.

  요청 → 감사(요청 직후) → 모델 선택 → 기록(처리 중) → 감사(송금 직전) → 결제 → 판매창구 확인
  → 결과 → 기록(성공·실패) → 감사(결제 후)

실패하면 결과 없이 실패 사유와 송금 전·후 여부를 남긴다. 실패한 건을 자동으로 다시 결제하지 않는다.
"""

import uuid
from typing import Any

# 감사 규칙 파일들을 불러와 audit.py 의 규칙 목록에 등록한다.
import agent_m2m.rules  # noqa: F401
from agent_m2m import store
from agent_m2m.audit import run_after_payment, run_before_payment, run_on_request
from agent_m2m.benchmark import load_fresh_snapshot
from agent_m2m.domain import PaymentResult, PurchaseRecord, now_iso
from agent_m2m.payment import PaymentError, pay
from agent_m2m.priority_llm import infer_priority
from agent_m2m.provider import mock_result, verify_payment
from agent_m2m.selection import decide


def run_purchase(purchase_input: dict[str, Any]) -> PurchaseRecord:
    """
    purchase_input: prompt·budgetUnits, 선택으로 priority·requestId·userId·maxOutputTokens·requiredCapabilities.
    우선순위가 없으면 로컬 Qwen 이 요청 문장을 보고 정한다. 요청 번호가 없으면 새로 만들고, 사용자가 없으면 None.
    """
    purchase_id = str(uuid.uuid4())
    if store.purchase_exists(purchase_id):
        raise RuntimeError("구매 번호가 중복되었습니다")

    incoming = {
        **purchase_input,
        "requestId": purchase_input.get("requestId") or str(uuid.uuid4()),
        "userId": purchase_input.get("userId"),
    }

    # 0) 감사(요청 직후) — 이전 기록을 돌려받으면 새로 처리하지 않고 그대로 응답한다.
    previous = run_on_request(purchase_id, incoming)
    if previous is not None:
        return previous

    # 우선순위가 없으면 로컬 Qwen 이 요청 문장을 보고 정한다. 실패하면 결제 전에 멈춘다.
    inferred = infer_priority(incoming["prompt"]) if incoming.get("priority") is None else None
    request = {**incoming, "priority": inferred["priority"] if inferred else incoming["priority"]}

    # 1) 선택 — 여기서 실패하면 결제는 시작조차 하지 않는다.
    source = load_fresh_snapshot()
    decision = decide(request, source)
    if source["refreshError"] is not None:
        decision["snapshotRefreshError"] = source["refreshError"]
    decision["prioritySource"] = "request" if inferred is None else "local-llm"
    if inferred is not None:
        decision["priorityModel"] = inferred["model"]

    # 결제 직전에 처리 중으로 먼저 남긴다. 중간에 멈춰도 기록이 남는다.
    record: PurchaseRecord = {
        "id": purchase_id,
        "requestId": request["requestId"],
        "userId": request["userId"],
        "createdAt": now_iso(),
        "prompt": request["prompt"],
        "status": "PROCESSING",
        "decision": decision,
        "payment": None,
        "resultText": None,
        "failureReason": None,
    }
    store.save_purchase(record)

    payment: PaymentResult | None = None
    try:
        # 2) 감사(송금 직전) — 하나라도 막으면 송금하지 않는다.
        run_before_payment(purchase_id, request, decision)

        # 3) 결제
        winner = decision["winner"]
        payment = pay(winner["amountUnits"], winner["recipient"], purchase_id, request["requestId"])

        # 4) 판매창구가 스스로 확인한 뒤에만 결과를 준다.
        verify_payment(payment, winner, request["requestId"])
        outcome = {
            "status": "SETTLED",
            "payment": payment,
            "resultText": mock_result(request["prompt"], winner),
            "failureReason": None,
        }
    except Exception as error:  # noqa: BLE001
        # 결제 결과를 받았거나 송금 뒤에 실패했으면 돈이 나갔을 수 있다. 거래번호를 지우지 않고 남긴다.
        sent = payment is not None or (isinstance(error, PaymentError) and error.sent)
        outcome = {
            "status": "FAILED",
            "payment": payment,
            "resultText": None,
            "failureReason": str(error) or "알 수 없는 오류",
            "failureStage": "after-send" if sent else "before-send",
        }
    updated_at = store.update_purchase(purchase_id, outcome)
    settled = {**record, **outcome, "updatedAt": updated_at}

    # 5) 감사(결제 후) — 결과는 이미 기록됐다. 예약해 둔 한도를 되돌리는 일 등을 한다.
    run_after_payment(purchase_id, request, decision, settled)
    return settled
