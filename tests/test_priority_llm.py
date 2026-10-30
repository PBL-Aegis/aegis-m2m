import json

import httpx
import pytest

from agent_m2m import priority_llm
from agent_m2m.priority_llm import PriorityInferenceError, infer_priority, ollama_config


def ollama_reply(content: str, status: int = 200) -> httpx.Response:
    """Ollama /api/chat 가 돌려주는 모양으로 답을 흉내 낸다."""
    return httpx.Response(status, text=json.dumps({"message": {"content": content}}))


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    for name in ("AEGIS_OLLAMA_URL", "AEGIS_OLLAMA_MODEL", "AEGIS_OLLAMA_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def test_Qwen_이_고른_우선순위와_모델_이름을_돌려준다(monkeypatch):
    calls = []

    def post(url, body, timeout):
        calls.append((url, body))
        return ollama_reply('{"priority":"price"}')

    monkeypatch.setattr(priority_llm, "http_post", post)
    assert infer_priority("최대한 싸게 요약해 줘") == {"priority": "price", "model": "qwen3.5:4b"}
    url, body = calls[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert body["format"]["properties"]["priority"]["enum"] == ["default", "price", "speed", "intelligence"]
    assert body["messages"][1] == {"role": "user", "content": "최대한 싸게 요약해 줘"}


def test_네_값_밖의_답은_받지_않는다(monkeypatch):
    monkeypatch.setattr(priority_llm, "http_post", lambda url, body, timeout: ollama_reply('{"priority":"cheapest"}'))
    with pytest.raises(PriorityInferenceError):
        infer_priority("싸게")


def test_Ollama_가_실패하면_모델_출력_없이_고정_메시지로_멈춘다(monkeypatch):
    monkeypatch.setattr(priority_llm, "http_post", lambda url, body, timeout: ollama_reply("요청 원문이 섞인 오류", 500))
    with pytest.raises(PriorityInferenceError, match="로컬 Qwen 우선순위 추론에 실패했습니다"):
        infer_priority("싸게")


def test_루프백이_아닌_주소는_부르지_않는다(monkeypatch):
    monkeypatch.setenv("AEGIS_OLLAMA_URL", "http://example.com:11434")
    with pytest.raises(PriorityInferenceError):
        ollama_config()
