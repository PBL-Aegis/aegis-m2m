"""
흥정 대사. 로컬 Gemma 가 코드가 정한 카드와 값을 문장으로 쓴다. 값과 카드는 바꾸지 못한다.

상대 메시지와 최저가는 주지 않는다. 그래서 상대의 지시가 모델에 닿지 않고 최저가도 새지 않는다.
금액 칸이 없거나 받은 자료에 없는 숫자를 쓰면 버리고, 호출이 실패하면 이번 구매의 남은 대사를 부르지 않는다.
둘 다 None 을 돌려주며, 그러면 negotiation.py 의 기본 문장을 쓴다.
"""

import json
import re
from typing import Any

import httpx

from agent_m2m.cards import BETTER, CHEAPER, NO_CARD, RIVAL_BETTER, RIVAL_CHEAPER
from agent_m2m.format import to_aegis
from agent_m2m.priority_llm import PriorityInferenceError, ollama_config

PLACEHOLDER = "{price}"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["line"], "properties": {"line": {"type": "string"}}}
FACTS = {
    BETTER: "my ECI is higher than the rival's",
    CHEAPER: "my price is lower than the rival's",
    RIVAL_CHEAPER: "the rival's price is lower than this model's",
    RIVAL_BETTER: "the rival's ECI is higher than this model's",
    NO_CARD: "there is no comparison advantage; do not claim any",
}
SYSTEM_PROMPT = (
    "Write one short, natural Korean sentence for a {role} agent in a price negotiation about an AI model call. "
    "State only the given fact, using the given numbers if needed. "
    "Include the placeholder {{price}} exactly once where your next price goes. Do not write any other price. "
    "Do not invent facts, discounts, stock, or features. Return JSON only."
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def http_post(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
    """Ollama 를 부르는 곳. 테스트는 이 함수를 바꿔 끼운다."""
    return httpx.post(url, json=body, timeout=timeout)


def _allowed_numbers(model: dict[str, Any], rival: dict[str, Any] | None) -> set[float]:
    allowed: set[float] = set()
    for item in (model, rival):
        if item is None:
            continue
        allowed.update({float(item["eci"]), float(to_aegis(item["amountUnits"]))})
        allowed.update(float(number) for number in NUMBER.findall(item["displayName"]))
    return allowed


class LineWriter:
    """구매 한 건의 대사를 쓴다. 한 번 실패하면 그 구매에서는 다시 부르지 않는다."""

    def __init__(self) -> None:
        self._down = False

    def write(self, role: str, card: str, price: int, model: dict[str, Any], rival: dict[str, Any] | None) -> str | None:
        if self._down:
            return None
        try:
            config = ollama_config()
            payload = {"thisModel": model["displayName"], "thisEci": model["eci"], "thisAsk": to_aegis(model["amountUnits"]), "fact": FACTS[card]}
            if rival is not None:
                payload.update({"rivalModel": rival["displayName"], "rivalEci": rival["eci"], "rivalAsk": to_aegis(rival["amountUnits"])})
            response = http_post(
                config["url"],
                {
                    "model": config["model"],
                    "stream": False,
                    "think": False,
                    "format": SCHEMA,
                    "options": {"temperature": 0.7, "num_predict": 120},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT.format(role=role)},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
                config["timeout"],
            )
            response.raise_for_status()
            line = json.loads(response.json()["message"]["content"])["line"].strip()
        except (httpx.HTTPError, PriorityInferenceError, KeyError, TypeError, ValueError, AttributeError):
            self._down = True
            return None
        return _finish(line, price, _allowed_numbers(model, rival))


def _finish(line: str, price: int, allowed: set[float]) -> str | None:
    if line.count(PLACEHOLDER) != 1:
        return None
    if any(float(number) not in allowed for number in NUMBER.findall(line.replace(PLACEHOLDER, ""))):
        return None
    return line.replace(PLACEHOLDER, f"{to_aegis(price)} AEGIS")
