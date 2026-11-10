import json

import pytest
from fastapi.testclient import TestClient

from agent_m2m import persona as persona_module, shopping
from agent_m2m.api import app
from agent_m2m.evaluation import evaluate
from agent_m2m.negotiation import negotiate
from agent_m2m.persona import PersonaError, load_persona, persona_ids
from agent_m2m.shopping import shop

LARGE_BUDGET = 10_000_000
THRIFTY, QUALITY = load_persona("thrifty"), load_persona("quality")


def candidate(provider: str, key: str, amount: int, eci: float) -> dict:
    return {"key": key, "displayName": key, "providerId": provider, "amountUnits": amount, "eci": eci}


# 호가가 같고 a 의 성능이 높다. 구매자는 b 와 흥정할 때 'a 가 성능이 높다' 카드가 있어 b 를 더 싸게 산다.
PAIR = [candidate("anthropic", "a", 4_001, eci=160), candidate("openai", "b", 4_001, eci=150)]


@pytest.fixture
def pair_table(monkeypatch):
    monkeypatch.setattr(shopping, "load_priority_models", lambda: {"price": ["a", "b"]})


def test_페르소나는_마크다운_파일에서_읽는다():
    assert persona_ids() == ("quality", "thrifty")
    assert (THRIFTY["name"], THRIFTY["openingRatio"], THRIFTY["premiumLimit"]) == ("최저가형", 0.7, 0)
    assert (QUALITY["name"], QUALITY["openingRatio"], QUALITY["premiumLimit"]) == ("품질형", 0.85, 0.2)
    assert THRIFTY["concede"] == {"new": 0.5, "used": 0.3, "none": 0.15}
    assert QUALITY["concede"] == {"new": 0.75, "used": 0.5, "none": 0.25}
    assert THRIFTY["goal"].startswith("같은 일을 하는 모델이면 가장 싸게")
    assert THRIFTY["hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "raw,message",
    [
        ("name: x\n목표: y", "--- 로 감싼"),
        ("---\nname: x\nopening_ratio: 0.7\n---\n본문", "'목표:'"),
        ("---\nname: x\nopening_ratio: 1.5\nconcede_new_card: 0.5\nconcede_used_card: 0.3\nconcede_no_card: 0.1\npremium_limit: 0\n---\n목표: y", "0 초과 1 이하"),
        ("---\nname: x\nopening_ratio: 0.7\n---\n목표: y", "concede_new_card"),
    ],
)
def test_설정이_틀린_페르소나는_받지_않는다(raw, message):
    with pytest.raises(PersonaError, match=message):
        persona_module._parse("bad", raw)
    with pytest.raises(PersonaError, match="없는 페르소나"):
        load_persona("no-such-persona")


def test_같은_페르소나면_항상_같은_흥정이고_품질형은_많이_양보해_더_비싸게_합의한다():
    assert negotiate(100_000, LARGE_BUDGET, 0.8, persona=QUALITY) == negotiate(100_000, LARGE_BUDGET, 0.8, persona=QUALITY)
    thrifty = negotiate(100_000, LARGE_BUDGET, 0.8, persona=THRIFTY)
    quality = negotiate(100_000, LARGE_BUDGET, 0.8, persona=QUALITY)
    assert (thrifty["transcript"][0]["priceUnits"], quality["transcript"][0]["priceUnits"]) == (70_000, 85_000)
    # 판매자는 구매자 값과의 차이에 비례해 내리므로, 빨리 올리는 품질형은 덜 깎는다.
    assert thrifty["agreedUnits"] < quality["agreedUnits"]


def test_구매자의_말마다_페르소나_근거가_있고_판매자의_말에는_없다():
    result = negotiate(100_000, LARGE_BUDGET, 0.8, persona=QUALITY)
    for turn in result["transcript"]:
        if turn["from"] == "buyer":
            assert turn["reason"]["persona"] == "quality"
            assert turn["reason"]["text"].startswith("품질형: ")
        else:
            assert "reason" not in turn
    assert [turn["reason"]["rule"] for turn in result["transcript"] if turn["from"] == "buyer"][0] == "opening"
    assert "floor" not in json.dumps(result).lower()
    assert "최저가 " not in json.dumps(result, ensure_ascii=False)


def test_양보_근거에는_판매자_카드와_올린_비율이_적힌다():
    turns = negotiate(4_000, LARGE_BUDGET, 0.5, seller_cards=("성능 우위",), persona=THRIFTY)["transcript"]
    concede = turns[2]["reason"]
    assert concede["rule"] == "concede"
    assert concede["inputs"] == {"card": "성능 우위", "freshness": "new", "ratio": 0.5, "lastOfferUnits": 2_800, "counterUnits": 3_700}
    assert "'성능 우위' 카드(처음 낸 카드)" in concede["text"] and "50%" in concede["text"]


def test_최대가를_넘어_거절할_때도_근거를_남긴다():
    from agent_m2m.negotiation import NegotiationError

    with pytest.raises(NegotiationError) as caught:
        negotiate(100_000, 80_000, 0.85, persona=THRIFTY)
    last = caught.value.negotiation["transcript"][-1]
    assert (last["action"], last["reason"]["rule"]) == ("reject", "over-max")
    assert "최대가 0.08 AEGIS" in last["reason"]["text"]


def test_최저가형은_싼_곳을_품질형은_한도_안에서_성능이_높은_곳을_산다(pair_table):
    thrifty = shop(PAIR, "price", LARGE_BUDGET, persona=THRIFTY)
    quality = shop(PAIR, "price", LARGE_BUDGET, persona=QUALITY)
    assert thrifty["winner"]["key"] == "b"
    assert quality["winner"]["key"] == "a"
    assert quality["winner"]["amountUnits"] > next(q["agreedUnits"] for q in quality["quotes"] if q["key"] == "b")
    assert (thrifty["persona"]["id"], quality["persona"]["id"]) == ("thrifty", "quality")

    cancelled = next(quote for quote in quality["quotes"] if quote["status"] == "cancelled")
    assert cancelled["transcript"][-1]["reason"]["rule"] == "cancel"
    assert "ECI가 10.00 높고" in cancelled["transcript"][-1]["reason"]["text"]


def test_비싸게_샀으면_평가에_그_이유가_적힌다(pair_table):
    result = shop(PAIR, "price", LARGE_BUDGET, persona=QUALITY)
    evaluation = result["evaluation"]
    assert (evaluation["verdict"], evaluation["headline"]) == ("good", "품질형 기준 이득")
    assert any("비싸게 샀습니다" in line and "한도 20% 안" in line for line in evaluation["lines"])


def test_최저가형이_싸게_샀으면_이득이고_성능을_포기한_것도_적는다(pair_table):
    evaluation = shop(PAIR, "price", LARGE_BUDGET, persona=THRIFTY)["evaluation"]
    assert evaluation["verdict"] == "good"
    assert any("싸게 샀습니다" in line for line in evaluation["lines"])
    assert any("ECI가 10.00 높지만 최저가형은 값만 봅니다" in line for line in evaluation["lines"])


def quote(key: str, status: str, agreed: int | None, eci: float, ask: int = 100_000) -> dict:
    item = {"key": key, "displayName": key, "status": status, "askUnits": ask, "eci": eci, "transcript": [{"from": "seller", "priceUnits": agreed or ask}]}
    if agreed is not None:
        item["agreedUnits"] = agreed
    return item


def test_품질형이_한도를_넘어_성능을_포기하면_일부_이득이다():
    cheap, better = quote("cheap", "agreed", 50_000, eci=150), quote("better", "cancelled", 90_000, eci=160)
    evaluation = evaluate(QUALITY, cheap, [cheap, better], LARGE_BUDGET)
    assert evaluation["verdict"] == "partial"
    assert any("한도 20%를 넘었습니다" in line for line in evaluation["lines"])


def test_예산을_넘겨_샀으면_손해다():
    chosen = {**quote("a", "agreed", 90_000, eci=150), "overBudget": True}
    evaluation = evaluate(THRIFTY, chosen, [chosen], 80_000)
    assert evaluation["verdict"] == "bad"
    assert any("예산 0.08 AEGIS보다 0.01 AEGIS 더 내고" in line for line in evaluation["lines"])


def test_목표로_설명할_수_없게_비싸게_샀으면_손해다():
    chosen, other = quote("a", "agreed", 90_000, eci=150), quote("b", "cancelled", 50_000, eci=160)
    evaluation = evaluate(THRIFTY, chosen, [chosen, other], LARGE_BUDGET)
    assert evaluation["verdict"] == "bad"
    assert any("설명할 수 없는 값" in line for line in evaluation["lines"])


def test_API_는_페르소나_목록을_주고_없는_페르소나는_받지_않는다():
    client = TestClient(app)
    assert [item["id"] for item in client.get("/api/personas").json()] == ["thrifty", "quality"]
    response = client.post("/api/purchase", json={"prompt": "요약", "budget": "1", "priority": "price", "persona": "greedy"})
    assert response.status_code == 400
    assert "persona" in response.json()["error"]


def test_값이_같아_성능으로_골랐으면_평가에_그_이유가_적힌다():
    chosen, other = quote("a", "agreed", 50_000, eci=160), quote("b", "cancelled", 50_000, eci=150)
    evaluation = evaluate(THRIFTY, chosen, [chosen, other], LARGE_BUDGET)
    assert any("값이 같아 ECI가 10.00 높은 이곳을 골랐습니다" in line for line in evaluation["lines"])
