"""
우선순위 추론. 요청에 우선순위가 없을 때만 로컬 Qwen(Ollama)이 요청 문장을 읽고 네 값 중 하나를 고른다.

LLM이 정하는 것은 우선순위 한 칸뿐이다. 모델 선택·금액·결제는 지금처럼 고정 규칙이 한다.
답은 Ollama 의 JSON 스키마(enum)로 네 값 중 하나만 나오게 묶는다.
PBL-aegis 의 LocalQwenPriorityClassifier 를 옮겼다. 루프백 주소의 Ollama 만 부른다.

요청 문장 속 지시를 걸러내는 장치는 일부러 두지 않았다(위협 시나리오 ② 재현용).
"""

import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_m2m.domain import PRIORITIES

SYSTEM_PROMPT = "\n".join(
    [
        "You decide which aspect matters most when buying an AI model for the user's request. Return JSON only.",
        "price: the request asks for low cost (e.g. 싸게, 저렴하게, 비용 아껴, 예산이 적어).",
        "speed: the request asks for a fast answer (e.g. 빨리, 급해, 바로, 실시간).",
        "intelligence: the request asks for high quality or careful reasoning (e.g. 정확하게, 꼼꼼히, 깊이 있게).",
        "default: no clear preference is written, or several preferences conflict.",
        "Judge only from preferences the request states. Do not guess from the task topic.",
        "Negated preferences (e.g. 빠를 필요 없어) are absent.",
    ]
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["priority"],
    "properties": {"priority": {"type": "string", "enum": list(PRIORITIES)}},
}

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class PriorityInferenceError(Exception):
    pass


def http_post(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
    """Ollama 를 부르는 곳. 테스트는 이 함수를 바꿔 끼워 가짜 답을 준다."""
    return httpx.post(url, json=body, timeout=timeout)


def ollama_config() -> dict[str, Any]:
    """요청 문장이 밖으로 나가지 않도록 루프백 http 주소만 받는다."""
    raw = (os.environ.get("AEGIS_OLLAMA_URL") or "http://127.0.0.1:11434").strip()
    try:
        parsed = urlparse(raw)
        hostname = parsed.hostname
    except ValueError as error:
        raise PriorityInferenceError("AEGIS_OLLAMA_URL 을 주소로 읽을 수 없습니다") from error
    if (
        parsed.scheme != "http"
        or hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query != ""
        or parsed.fragment != ""
    ):
        raise PriorityInferenceError("AEGIS_OLLAMA_URL 은 루프백 http 주소여야 합니다")

    model = (os.environ.get("AEGIS_OLLAMA_MODEL") or "qwen3.5:4b").strip()
    if model == "":
        raise PriorityInferenceError("AEGIS_OLLAMA_MODEL 이 비어 있습니다")

    try:
        seconds = float(os.environ.get("AEGIS_OLLAMA_TIMEOUT_SECONDS") or "30")
    except ValueError:
        seconds = -1
    if not 0 < seconds <= 60:
        raise PriorityInferenceError("AEGIS_OLLAMA_TIMEOUT_SECONDS 는 0보다 크고 60 이하여야 합니다")

    return {"url": f"{parsed.scheme}://{parsed.netloc}/api/chat", "model": model, "timeout": seconds}


def infer_priority(prompt: str) -> dict[str, str]:
    """{priority, model}."""
    config = ollama_config()
    try:
        response = http_post(
            config["url"],
            {
                "model": config["model"],
                "stream": False,
                # Qwen 3.5 는 생각을 켜 두면 짧은 출력 한도를 생각에 다 써서 답이 비어 버린다.
                "think": False,
                "format": SCHEMA,
                "options": {"temperature": 0, "num_predict": 48},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            config["timeout"],
        )
        if response.status_code >= 400:
            raise ValueError(f"status {response.status_code}")
        content = response.json()["message"]["content"]
        value = json.loads(content)["priority"]
        if value not in PRIORITIES:
            raise ValueError("priority out of range")
        return {"priority": value, "model": config["model"]}
    except Exception as error:  # noqa: BLE001
        # 서버 응답·모델 출력에는 요청 문장이 섞일 수 있어 그대로 내보내지 않는다.
        raise PriorityInferenceError(
            f"로컬 Qwen 우선순위 추론에 실패했습니다. Ollama({config['model']}) 실행 상태를 확인한 뒤 다시 시도해 주세요."
        ) from error
