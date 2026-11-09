"""
LLM 흥정 판단. 로컬 LLM(Ollama)이 페르소나 글을 읽고 구매 에이전트의 다음 행동을 정한다.

흥정 방식은 세 가지다(negotiation.py).
  rule    코드가 페르소나 숫자로 정한다. LLM 을 부르지 않는다.
  llm     LLM 이 정한 값을 그대로 쓴다. 최대가 세이프가드만 막고, 나머지 검사 결과는 기록만 한다.
  hybrid  LLM 이 정한 값을 아래 네 검사로 본다. 하나라도 걸리면 규칙형 값으로 바꾸고 걸린 검사를 남긴다.

검사(check)
  over-max        최대가(예산·호가 중 낮은 값)를 넘었다
  out-of-range    첫 제안이 호가를 넘거나, 제안이 내 지난 제안보다 낮거나 판매자 값보다 높다
  unknown-number  이유에 받은 자료에 없는 숫자를 썼다
  persona-line    페르소나 숫자 선을 넘었다(첫 제안 비율, 양보 비율, 받아도 되는 때, 거절해도 되는 때)

LLM 에게는 페르소나 글, 호가, 최대가, 내 마지막 제안, 판매자 값, 판매자 카드, 남은 제안 횟수만 준다.
판매자의 문장과 최저가는 주지 않는다. 상대 문장 속 지시가 닿지 않고 최저가도 새지 않게 하기 위해서다.
어디서 살지는 세 방식 모두 코드가 정한다(shopping.py).
"""

import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from agent_m2m.format import UNITS_PER_AEGIS, to_aegis
from agent_m2m.priority_llm import PriorityInferenceError, ollama_config
from agent_m2m.strategy import MAX_ROUNDS, round_down

MODES = ("rule", "llm", "hybrid")
DEFAULT_MODE = "rule"
DEFAULT_MODEL = "qwen3:14b"
DEFAULT_TIMEOUT_SECONDS = 120.0
NUMBER = re.compile(r"\d+(?:\.\d+)?")

SYSTEM_PROMPT = (
    "You are the buyer agent in a price negotiation for one AI model call. "
    "Act exactly as the persona below describes. Prices are in AEGIS.\n"
    "Decide your next move from the situation JSON and return JSON only: "
    '{"action": one of the allowed actions, "price": your price as a decimal string, "reason": one short Korean sentence}.\n'
    "offer: propose a new price. accept: take the seller's current price. reject: walk away.\n"
    "Never go above maxPrice. Use only numbers that appear in the situation or the persona in your reason.\n\n"
    "# Persona\n{persona}"
)


class LlmDecisionError(Exception):
    """LLM 을 부르지 못했거나 답을 읽을 수 없다. 흥정은 규칙형 값으로 이어간다."""


def http_post(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
    """Ollama 를 부르는 곳. 테스트는 이 함수를 바꿔 끼운다."""
    return httpx.post(url, json=body, timeout=timeout)


def llm_config() -> dict[str, Any]:
    """주소는 우선순위 추론과 같은 루프백 Ollama 다. 모델과 기다리는 시간은 흥정용 값을 따로 쓴다."""
    try:
        base = ollama_config()
    except PriorityInferenceError as error:
        raise LlmDecisionError(str(error)) from error
    model = (os.environ.get("AEGIS_NEGOTIATION_MODEL") or DEFAULT_MODEL).strip()
    try:
        seconds = float(os.environ.get("AEGIS_NEGOTIATION_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    except ValueError as error:
        raise LlmDecisionError("AEGIS_NEGOTIATION_TIMEOUT_SECONDS 는 숫자여야 합니다") from error
    return {"url": base["url"], "model": model, "timeout": seconds}


def allowed_actions(situation: dict[str, Any]) -> list[str]:
    if situation["stage"] == "opening":
        return ["offer"]
    if situation["roundsLeft"] == 0:
        return ["accept", "reject"]
    return ["offer", "accept", "reject"]


def _to_units(text: str) -> int:
    try:
        value = Decimal(str(text).strip())
    except InvalidOperation as error:
        raise LlmDecisionError("LLM 이 낸 값을 금액으로 읽을 수 없습니다") from error
    if not value.is_finite() or value < 0:
        raise LlmDecisionError("LLM 이 낸 값이 0 이상의 금액이 아닙니다")
    return int((value * UNITS_PER_AEGIS).to_integral_value())


def _situation_payload(situation: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "stage": situation["stage"],
        "allowedActions": allowed_actions(situation),
        "askPrice": to_aegis(situation["askUnits"]),
        "maxPrice": to_aegis(situation["maxUnits"]),
        "offersLeftAfterThis": situation["roundsLeft"],
    }
    if situation["stage"] == "reply":
        payload.update(
            {
                "myLastOffer": to_aegis(situation["lastOfferUnits"]),
                "sellerPrice": to_aegis(situation["counterUnits"]),
                "sellerCard": situation["sellerCard"],
                "sellerCardIsNew": situation["freshness"] == "new",
            }
        )
    return payload


def decide(persona: dict[str, Any], situation: dict[str, Any]) -> dict[str, Any]:
    """{action, priceUnits, reason}. 부르지 못하거나 답이 틀리면 LlmDecisionError."""
    config = llm_config()
    actions = allowed_actions(situation)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "price", "reason"],
        "properties": {"action": {"type": "string", "enum": actions}, "price": {"type": "string"}, "reason": {"type": "string"}},
    }
    try:
        response = http_post(
            config["url"],
            {
                "model": config["model"],
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0, "num_predict": 200},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT.replace("{persona}", persona["body"])},
                    {"role": "user", "content": json.dumps(_situation_payload(situation), ensure_ascii=False)},
                ],
            },
            config["timeout"],
        )
        response.raise_for_status()
        answer = json.loads(response.json()["message"]["content"])
        action, reason = answer["action"], str(answer["reason"]).strip()
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise LlmDecisionError(f"LLM 흥정 판단을 받지 못했습니다({config['model']})") from error
    if action not in actions or reason == "":
        raise LlmDecisionError("LLM 이 허용되지 않은 행동을 냈거나 이유를 비웠습니다")
    price = situation["counterUnits"] if action in ("accept", "reject") else _to_units(answer["price"])
    return {"action": action, "priceUnits": price, "reason": reason}


def _allowed_numbers(persona: dict[str, Any], situation: dict[str, Any], price: int) -> set[float]:
    units = [situation["askUnits"], situation["maxUnits"], price]
    if situation["stage"] == "reply":
        units += [situation["lastOfferUnits"], situation["counterUnits"]]
    allowed = {float(to_aegis(value)) for value in units}
    allowed.update(float(number) for number in NUMBER.findall(persona["body"]))
    allowed.update({float(situation["roundsLeft"]), float(MAX_ROUNDS)})
    return allowed


def check(persona: dict[str, Any], situation: dict[str, Any], decision: dict[str, Any], rule_action: str, step: int) -> list[str]:
    """LLM 의 결정이 걸린 검사 이름들. 비어 있으면 통과다. rule_action 은 같은 자리에서 규칙형이 한 행동이다."""
    failures = []
    action, price = decision["action"], decision["priceUnits"]
    if action != "reject" and price > situation["maxUnits"]:
        failures.append("over-max")

    if situation["stage"] == "opening":
        if price > situation["askUnits"]:
            failures.append("out-of-range")
        if price > round_down(situation["askUnits"] * persona["openingRatio"], step):
            failures.append("persona-line")
    elif action == "offer":
        last, counter = situation["lastOfferUnits"], situation["counterUnits"]
        if not last <= price <= counter:
            failures.append("out-of-range")
        ratio = persona["concede"][situation["freshness"]]
        if price > round_down(last + (counter - last) * ratio, step):
            failures.append("persona-line")
    elif action == "accept" and rule_action != "accept":
        failures.append("persona-line")
    elif action == "reject" and rule_action != "reject":
        failures.append("persona-line")

    allowed = _allowed_numbers(persona, situation, price)
    if any(float(number) not in allowed for number in NUMBER.findall(decision["reason"])):
        failures.append("unknown-number")
    return failures
