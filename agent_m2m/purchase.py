"""
구매 한 건의 전체 흐름.

  요청 → 감사(요청 직후) → 모델 선택 → 흥정 → 합의 만들기 → 기록(처리 중) → 감사(송금 직전)
  → 체인에 합의 열기 + 감사 결과(운영자) → x402 결제(판매창구 402 → 구매자 서명 → 정산 서버) → 판매창구 확인·결과
  → 기록(성공·실패) → 감사(결제 후) → 체인에 송금 뒤 감사 결과(운영자)

송금 직전 감사가 막으면 체인에 "막음" 기록만 남기고 결제하지 않는다. 체인도 열린 합의가 없는 결제는 받지 않는다.

실패하면 결과 없이 실패 사유와 송금 전·후 여부를 남긴다. 실패한 건을 자동으로 다시 결제하지 않는다.
"""

import os
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from x402.http import decode_payment_required_header, encode_payment_signature_header

# 감사 규칙 파일들을 불러와 audit.py 의 규칙 목록에 등록한다.
import agent_m2m.rules  # noqa: F401
import agent_m2m.rules.over_budget  # noqa: F401
from agent_m2m import store, x402_payment
from agent_m2m.audit import (
    AuditBlockedError,
    audit_before_payment,
    blocked_error,
    report_summary,
    run_after_payment,
    run_on_request,
)
from agent_m2m.benchmark import load_snapshot
from agent_m2m.domain import PaymentResult, PurchaseRecord, now_iso
from agent_m2m.deal import build_deal, hash_deal
from agent_m2m.payment import PaymentError, anvil_account, open_deal, record_after_audit, request_id_hash
from agent_m2m.persona import DEFAULT_PERSONA, load_persona
from agent_m2m.priority_llm import infer_priority
from agent_m2m.selection import decide
from agent_m2m.shopping import shop

# 판매창구(provider.deliver) 주소. 기본은 이 서버 자신(api.py 의 /api/provider/purchases/{id}).
DEFAULT_PROVIDER_URL = "http://127.0.0.1:8000"


def provider_client() -> httpx.Client:
    """판매창구에 HTTP 로 요청하는 클라이언트. 테스트는 이 함수를 바꿔 끼워 서버를 띄우지 않고 부른다."""
    return httpx.Client(base_url=os.environ.get("AGENT_M2M_PROVIDER_URL") or DEFAULT_PROVIDER_URL, timeout=60)


def _record_before_send(purchase_id: str, deal: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """송금 직전 감사 보고서를 DB 에 두고, 결과·걸린 규칙·보고서 해시를 체인에 올린다(합의 열기).
    막은 감사는 체인에 올리지 못해도 결제는 어차피 하지 않으므로 그 사유만 남긴다."""
    summary = report_summary(report)
    entry: dict[str, Any] = {"report": report, "hash": summary["hash"], "txHash": None}
    try:
        entry["txHash"] = open_deal(deal, summary)
    except Exception as error:  # noqa: BLE001
        if report["result"] != "block":
            store.update_purchase(purchase_id, {"audit": {"beforeSend": entry}})
            raise PaymentError(f"체인에 합의와 감사 결과를 올리지 못했습니다: {error}") from error
        entry["chainError"] = str(error)
    store.update_purchase(purchase_id, {"audit": {"beforeSend": entry}})
    return entry


def _pay_with_x402(purchase_id: str, deal: dict[str, Any]) -> dict[str, Any]:
    """판매창구와 x402 로 주고받는다. 402 조건이 합의와 같을 때만 서명한다. 판매창구의 200 본문 {payment, resultText} 를 돌려준다."""
    path = f"/api/provider/purchases/{purchase_id}"
    with provider_client() as client:
        first = client.get(path)
        if first.status_code != 402 or x402_payment.PAYMENT_REQUIRED not in first.headers:
            raise PaymentError(f"판매창구가 402 대신 {first.status_code} 로 답했습니다: {first.text[:200]}")
        required = decode_payment_required_header(first.headers[x402_payment.PAYMENT_REQUIRED])
        try:
            accepted = x402_payment.check_requirements(required.accepts, deal)
        except x402_payment.PaymentRejected as error:
            raise PaymentError(str(error)) from error
        signed = x402_payment.build_payment(anvil_account(1), accepted, hash_deal(deal))
        paid = client.get(path, headers={x402_payment.PAYMENT_SIGNATURE: encode_payment_signature_header(signed)})
    body = paid.json()
    if paid.status_code != 200:
        # 판매창구가 정산 뒤 확인에 실패했으면 거래 기록을 함께 준다. 돈이 나갔다.
        error = PaymentError(f"판매창구가 결제를 받지 않았습니다({paid.status_code}): {body.get('error', paid.text[:200])}", sent="payment" in body)
        error.payment = body.get("payment")
        raise error
    return body


def run_purchase(
    purchase_input: dict[str, Any],
    on_event: Callable[[dict[str, Any]], None] = lambda event: None,
) -> PurchaseRecord:
    """
    purchase_input: prompt(지시)·budgetUnits, 선택으로 content(처리할 내용)·persona·requestId·userId·maxOutputTokens·requiredCapabilities.
    페르소나가 없으면 기본 페르소나(최저가형)로 흥정한다.
    우선순위는 언제나 로컬 Gemma 가 지시와 내용을 읽고 정한다. 요청 번호가 없으면 새로 만들고, 사용자가 없으면 None.
    흥정 진행은 on_event 로 바로 알린다(shopping.py).
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

    # 우선순위는 로컬 Gemma 가 지시와 내용을 읽고 정한다. 실패하면 결제 전에 멈춘다.
    # 내용에 숨긴 지시에 속았는지는 송금 직전 감사(rules/intent_swap.py)가 지시만 다시 읽어 대조한다.
    inferred = infer_priority(incoming["prompt"], incoming.get("content") or "")
    request = {**incoming, "priority": inferred["priority"]}

    # 1) 호가 계산 — 고정된 단가로 후보마다 금액을 낸다. 여기서 실패하면 결제는 시작조차 하지 않는다.
    decision = decide(request, load_snapshot())
    decision["priorityModel"] = inferred["model"]

    # 흥정 — 모두 결렬되면 기록 없이 멈춘다. 합의가를 winner 금액에 넣어 뒤의 감사·결제·확인이 모두 이 값을 본다.
    persona = load_persona(request.get("persona") or DEFAULT_PERSONA)
    decision.update(shop(decision["candidates"], request["priority"], request["budgetUnits"], on_event, persona))
    # 체인에 남길 합의. 대화와 결정 근거는 DB 에 두고 해시만 담는다(deal.py). 기록에 먼저 넣어 나중에 대조할 수 있게 한다.
    decision["deal"] = build_deal(request_id_hash(request["requestId"]), anvil_account(1).address, decision)

    # 결제 직전에 처리 중으로 먼저 남긴다. 중간에 멈춰도 기록이 남는다.
    record: PurchaseRecord = {
        "id": purchase_id,
        "requestId": request["requestId"],
        "userId": request["userId"],
        "createdAt": now_iso(),
        "prompt": request["prompt"],
        "content": request.get("content"),
        "status": "PROCESSING",
        "decision": decision,
        "payment": None,
        "resultText": None,
        "failureReason": None,
    }
    store.save_purchase(record)

    payment: PaymentResult | None = None
    try:
        # 2) 감사(송금 직전) — 보고서를 DB 에 두고 결과를 체인에 올린다. 막으면 체인은 합의를 열지 않는다.
        report = audit_before_payment(purchase_id, request, decision)
        _record_before_send(purchase_id, decision["deal"], report)
        blocked = blocked_error(report)
        if blocked is not None:
            raise blocked

        # 3) x402 결제 — 판매창구가 402 로 조건을 주고, 구매자가 합의 해시를 nonce 로 서명하고, 정산 서버가 체인에 올린다.
        #    판매창구는 체인의 송금·합의·감사 기록을 DB 와 대조한 뒤에만 결과를 준다.
        delivered = _pay_with_x402(purchase_id, decision["deal"])
        payment = delivered["payment"]
        outcome = {
            "status": "SETTLED",
            "payment": payment,
            "resultText": delivered["resultText"],
            "failureReason": None,
        }
    except Exception as error:  # noqa: BLE001
        # 결제 결과를 받았거나 송금 뒤에 실패했으면 돈이 나갔을 수 있다. 거래번호를 지우지 않고 남긴다.
        payment = payment or getattr(error, "payment", None)
        sent = payment is not None or (isinstance(error, PaymentError) and error.sent)
        outcome = {
            "status": "FAILED",
            "payment": payment,
            "resultText": None,
            "failureReason": str(error) or "알 수 없는 오류",
            "failureStage": "after-send" if sent else "before-send",
        }
        # 감사 규칙이 막은 건과 결제가 실패한 건을 화면에서 구분한다.
        if isinstance(error, AuditBlockedError):
            outcome["blockedRule"] = error.rule
    updated_at = store.update_purchase(purchase_id, outcome)
    settled = {**store.get_purchase(purchase_id), "updatedAt": updated_at}

    # 5) 감사(결제 후) — 결과는 이미 기록됐다. 예약해 둔 한도를 되돌리는 일 등을 한다.
    after = run_after_payment(purchase_id, request, decision, settled)
    if settled["status"] == "SETTLED":
        summary = report_summary(after)
        entry: dict[str, Any] = {"report": after, "hash": summary["hash"], "txHash": None}
        try:
            entry["txHash"] = record_after_audit(decision["deal"]["requestId"], summary)
        except Exception as error:  # noqa: BLE001
            entry["chainError"] = str(error)
        store.update_purchase(purchase_id, {"audit.afterSend": entry})
        settled = store.get_purchase(purchase_id) or settled
    return settled
