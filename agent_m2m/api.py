"""
HTTP API. 화면(web/)과 다른 에이전트가 이 주소들만 부른다.

  POST /api/purchase                 요청 한 건을 받아 선택·결제·확인·결과·기록까지 돌린다
  GET  /api/purchases                최근 구매 기록 목록
  GET  /api/purchases/{id}           구매 기록 한 건
  GET  /api/purchases/{id}/alerts    그 구매에 달린 알림
  GET  /api/alerts                   최근 알림과, 그중 구매 기록이 있는 구매 번호
  GET  /api/alerts/summary           차단·경고 개수
  GET  /api/wallet                   구매 에이전트 지갑 잔액
  GET  /api/mode                     결제 모드(local·live)

POST /api/purchase 의 입력은 여기서 모양만 검사한다(문자열인지, 금액 형식인지, 네 우선순위 중 하나인지).
예산(budget)은 사람이 적는 값이라 AEGIS 로 받고(예: "0.5"), 여기서 최소 단위(units)로 바꾼다.
우선순위는 빼도 된다. 빼면 로컬 Qwen 이 요청 문장을 보고 정한다.
requestId·userId 도 빼도 된다. requestId 를 빼면 서버가 새로 만든다.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from agent_m2m import store
from agent_m2m.audit import AuditBlockedError
from agent_m2m.domain import PRIORITIES
from agent_m2m.format import parse_aegis
from agent_m2m.payment import buyer_balance, payment_config
from agent_m2m.priority_llm import PriorityInferenceError
from agent_m2m.purchase import run_purchase
from agent_m2m.selection import SelectionError

app = FastAPI(title="agent-M2M")


def _error(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, **extra}, status_code=status)


def parse_body(body: Any) -> dict[str, Any] | str:
    """요청 본문을 구매 입력으로 바꾼다. 틀린 부분이 있으면 한국어 메시지를 돌려준다."""
    if not isinstance(body, dict):
        return "요청 본문이 JSON 객체가 아닙니다"

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or prompt.strip() == "":
        return "prompt 는 비어 있지 않은 문자열이어야 합니다"

    if "budgetUnits" in body:
        return 'budgetUnits 대신 budget 에 AEGIS 금액을 보내세요 (예: "0.5")'
    budget_units = parse_aegis(body.get("budget"))
    if budget_units is None:
        return 'budget 은 0 이상의 AEGIS 금액이어야 합니다 (예: "0.5", 소수점 6자리까지)'

    request: dict[str, Any] = {"prompt": prompt, "budgetUnits": budget_units}

    for field in ("requestId", "userId"):
        value = body.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or value.strip() == "":
            return f"{field} 는 비어 있지 않은 문자열이거나 비어 있어야 합니다"
        request[field] = value.strip()

    priority = body.get("priority")
    if priority is not None:
        if priority not in PRIORITIES:
            return f"priority 는 {', '.join(PRIORITIES)} 중 하나이거나 비어 있어야 합니다"
        request["priority"] = priority

    if "maxOutputTokens" in body:
        value = body["maxOutputTokens"]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return "maxOutputTokens 는 1 이상의 정수여야 합니다"
        request["maxOutputTokens"] = value

    if "requiredCapabilities" in body:
        value = body["requiredCapabilities"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return "requiredCapabilities 는 문자열 배열이어야 합니다"
        request["requiredCapabilities"] = [item.strip() for item in value if item.strip() != ""]

    return request


@app.post("/api/purchase")
async def post_purchase(http_request: Request) -> JSONResponse:
    try:
        body = await http_request.json()
    except ValueError:
        return _error(400, "요청 본문을 JSON 으로 읽을 수 없습니다")

    parsed = parse_body(body)
    if isinstance(parsed, str):
        return _error(400, parsed)

    try:
        # 결제는 체인·DB 를 기다리는 일이라 스레드에서 돌린다. 요청 여러 개가 동시에 처리된다.
        record = await run_in_threadpool(run_purchase, parsed)
    except SelectionError as error:
        # 선택 단계에서 막힌 경우(후보 없음 등)는 결제 전이므로 기록 없이 400 으로 알린다.
        return _error(400, str(error))
    except AuditBlockedError as error:
        # 요청 직후 감사 규칙이 막은 경우. 모델을 고르기 전이라 기록 없이 409 로 알린다.
        return _error(409, str(error), rule=error.rule)
    except PriorityInferenceError as error:
        # 우선순위 추론이 안 되면 결제 전이다. 기본값으로 메우지 않고 멈춘다.
        return _error(503, str(error))
    except Exception as error:  # noqa: BLE001
        return _error(500, str(error) or "알 수 없는 오류")
    return JSONResponse(record)


@app.get("/api/purchases")
def get_purchases(limit: int = 50) -> list[dict[str, Any]]:
    return store.list_purchases(limit)


@app.get("/api/purchases/{purchase_id}")
def get_purchase(purchase_id: str) -> Any:
    record = store.get_purchase(purchase_id)
    if record is None:
        return _error(404, "해당 구매 기록이 없습니다")
    return record


@app.get("/api/purchases/{purchase_id}/alerts")
def get_purchase_alerts(purchase_id: str) -> list[dict[str, Any]]:
    return store.list_alerts_for_purchase(purchase_id)


@app.get("/api/alerts")
def get_alerts(limit: int = 50) -> dict[str, Any]:
    alerts = store.list_alerts(limit)
    linked = store.existing_purchase_ids([alert["purchaseId"] for alert in alerts])
    return {"alerts": alerts, "linkedPurchaseIds": sorted(linked)}


@app.get("/api/alerts/summary")
def get_alert_summary() -> dict[str, int]:
    return store.count_alerts()


@app.get("/api/wallet")
def get_wallet() -> dict[str, Any]:
    return buyer_balance()


@app.get("/api/mode")
def get_mode() -> dict[str, str]:
    return {"mode": payment_config()["mode"]}
