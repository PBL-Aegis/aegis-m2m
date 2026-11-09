import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_m2m import persona_llm
from agent_m2m.api import app
from agent_m2m.cards import BETTER
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.persona import load_persona

LARGE_BUDGET = 10_000_000
THRIFTY = load_persona("thrifty")


def answers(monkeypatch, replies):
    """LLM 대신 replies 를 차례로 돌려준다. 받은 요청은 sent 에 쌓는다."""
    sent, queue = [], list(replies)

    def fake(url, body, timeout):
        sent.append(body)
        answer = queue.pop(0) if queue else {"action": "accept", "price": "0", "reason": "받습니다."}
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(persona_llm, "http_post", fake)
    return sent


def buyer_turns(result):
    return [turn for turn in result["transcript"] if turn["from"] == "buyer"]


def test_규칙형은_LLM_을_부르지_않는다(monkeypatch):
    sent = answers(monkeypatch, [])
    result = negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY)
    assert sent == []
    assert {turn["reason"]["source"] for turn in buyer_turns(result)} == {"rule"}


def test_LLM_에게는_판매자_문장과_최저가를_주지_않는다(monkeypatch):
    sent = answers(monkeypatch, [{"action": "offer", "price": "0.0028", "reason": "70%로 시작합니다."}])
    negotiate(4_000, LARGE_BUDGET, 0.5, seller_cards=(BETTER,), persona=THRIFTY, mode="llm")
    situation = json.loads(sent[1]["messages"][1]["content"])
    assert set(situation) == {"stage", "allowedActions", "askPrice", "maxPrice", "offersLeftAfterThis", "myLastOffer", "sellerPrice", "sellerCard", "sellerCardIsNew"}
    assert "floor" not in json.dumps(sent).lower()
    assert "한 푼이라도 아끼는" in sent[0]["messages"][0]["content"]


def test_이중형은_규칙을_어긴_LLM_값을_규칙형_값으로_바꾸고_걸린_검사를_남긴다(monkeypatch):
    answers(monkeypatch, [{"action": "offer", "price": "0.0035", "reason": "0.0035로 시작합니다."}])
    first = buyer_turns(negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="hybrid"))[0]
    assert first["priceUnits"] == 2_800
    assert first["reason"]["source"] == "fallback"
    assert first["reason"]["check"] == {"passed": False, "failures": ["persona-line"]}
    assert first["reason"]["llm"]["priceUnits"] == 3_500


def test_LLM형은_규칙을_어겨도_값을_그대로_쓰고_검사만_남긴다(monkeypatch):
    answers(monkeypatch, [{"action": "offer", "price": "0.0035", "reason": "0.0035로 시작합니다."}])
    first = buyer_turns(negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="llm"))[0]
    assert first["priceUnits"] == 3_500
    assert first["reason"]["source"] == "llm"
    assert first["reason"]["check"]["failures"] == ["persona-line"]
    assert first["reason"]["text"] == "최저가형: 0.0035로 시작합니다."


def test_검사를_통과한_LLM_값은_이중형에서도_그대로_쓴다(monkeypatch):
    answers(monkeypatch, [{"action": "offer", "price": "0.0027", "reason": "호가의 70%보다 낮게 시작합니다."}])
    first = buyer_turns(negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="hybrid"))[0]
    assert (first["priceUnits"], first["reason"]["source"]) == (2_700, "llm")
    assert first["reason"]["check"] == {"passed": True, "failures": []}


def test_이유에_받지_않은_숫자를_쓰면_걸린다(monkeypatch):
    answers(monkeypatch, [{"action": "offer", "price": "0.0027", "reason": "시장가 0.0031보다 낮게 시작합니다."}])
    first = buyer_turns(negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="hybrid"))[0]
    assert first["reason"]["check"]["failures"] == ["unknown-number"]


def test_남은_기회가_있는데_거절하면_이중형은_막고_LLM형은_결렬된다(monkeypatch):
    reject = {"action": "reject", "price": "0", "reason": "비싸서 그만합니다."}
    opening = {"action": "offer", "price": "0.0028", "reason": "70%로 시작합니다."}
    answers(monkeypatch, [opening, reject])
    with pytest.raises(NegotiationError) as caught:
        negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="llm")
    last = caught.value.negotiation["transcript"][-1]
    assert (last["action"], last["reason"]["check"]["failures"]) == ("reject", ["persona-line"])

    answers(monkeypatch, [opening, reject])
    second = buyer_turns(negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="hybrid"))[1]
    assert (second["action"], second["reason"]["source"]) == ("offer", "fallback")


def test_LLM_이_최대가를_넘겨_받으려_하면_세이프가드가_막는다(monkeypatch):
    opening = {"action": "offer", "price": "0.0028", "reason": "70%로 시작합니다."}
    answers(monkeypatch, [opening, {"action": "accept", "price": "0", "reason": "받습니다."}])
    with pytest.raises(NegotiationError) as caught:
        negotiate(4_000, 3_000, 0.5, persona=THRIFTY, mode="llm")
    assert caught.value.negotiation["status"] == "blocked"


def test_LLM_을_부르지_못하면_규칙형_값으로_이어간다(monkeypatch):
    def down(url, body, timeout):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(persona_llm, "http_post", down)
    rule = negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY)
    hybrid = negotiate(4_000, LARGE_BUDGET, 0.5, persona=THRIFTY, mode="hybrid")
    assert [turn["priceUnits"] for turn in hybrid["transcript"]] == [turn["priceUnits"] for turn in rule["transcript"]]
    assert buyer_turns(hybrid)[0]["reason"]["check"]["failures"] == ["llm-error"]


def test_API_는_없는_흥정_방식을_받지_않는다():
    response = TestClient(app).post("/api/purchase", json={"prompt": "요약", "budget": "1", "priority": "price", "negotiationMode": "magic"})
    assert response.status_code == 400
    assert "negotiationMode" in response.json()["error"]
