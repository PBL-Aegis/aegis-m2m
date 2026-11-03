import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_m2m import audit, seller as seller_module, store
from agent_m2m.api import app
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.payment import buyer_balance, request_id_hash
from agent_m2m.purchase import run_purchase
from agent_m2m.seller import SellerAgent, find_seller
from agent_m2m.shopping import shop, shortlist
from agent_m2m.strategy import price_step

ASKS = [4_001, 12_960, 100_000, 400_000, 1_234_567]
LARGE_BUDGET = 10_000_000
RATIO = 0.8
INPUT = {"prompt": "이 글 요약해 줘", "budgetUnits": LARGE_BUDGET, "priority": "price"}


@pytest.fixture(autouse=True)
def empty_rules():
    """규칙이 금액을 보는 자리만 시험하므로, 등록된 실제 규칙을 잠시 비운다."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


@pytest.mark.parametrize("ask", ASKS)
def test_같은_입력이면_항상_같은_값에_합의하고_호가보다_싸다(ask):
    first = negotiate(ask, LARGE_BUDGET, RATIO)
    second = negotiate(ask, LARGE_BUDGET, RATIO)
    assert first == second
    assert first["status"] == "agreed"
    assert first["agreedUnits"] < ask


@pytest.mark.parametrize("ask", ASKS)
@pytest.mark.parametrize("ratio", [0.75, 0.8, 0.85, 0.9])
def test_판매자는_최저가_아래로_합의하거나_부르지_않는다(ask, ratio):
    floor = ask * ratio
    result = negotiate(ask, LARGE_BUDGET, ratio)
    assert result["agreedUnits"] >= floor
    assert all(turn["priceUnits"] >= floor for turn in result["transcript"] if turn["from"] == "seller")


@pytest.mark.parametrize("ask", ASKS)
def test_구매자는_예산을_넘겨_부르지_않는다(ask):
    budget = round(ask * 0.9)
    result = negotiate(ask, budget, RATIO)
    assert result["agreedUnits"] <= budget
    assert all(turn["priceUnits"] <= budget for turn in result["transcript"] if turn["from"] == "buyer")


def test_작은_금액도_첫_제안이_0으로_내려가지_않는다():
    assert price_step(12_960) == 100
    first = negotiate(12_960, LARGE_BUDGET, RATIO)["transcript"][0]
    assert first["priceUnits"] > 0


def test_기록에_판매자_최저가가_담기지_않는다():
    result = negotiate(100_000, LARGE_BUDGET, RATIO)
    assert "floor" not in json.dumps(result).lower()
    assert not hasattr(SellerAgent(100_000, RATIO), "floor_units")


def test_값을_내리지_않는_판매자에게서는_예산이_맞아도_사지_않는다():
    with pytest.raises(NegotiationError) as caught:
        negotiate(100_000, LARGE_BUDGET, 1)
    assert caught.value.negotiation["status"] == "no-deal"


def test_실제_판매_목록은_세_판매_에이전트가_등록한_8개_모델만_있다():
    data = Path(__file__).resolve().parent.parent / "data"
    sellers = json.loads((data / "sellers.json").read_text())["sellers"]
    assert set(sellers) == {"anthropic", "openai", "google"}
    assert all(0 < seller["floorRatio"] <= 0.9 for seller in sellers.values())
    entries = json.loads((data / "catalog.json").read_text())["entries"]
    assert len(entries) == 8
    assert all(entry["displayName"] in sellers[entry["providerId"]]["models"] for entry in entries)
    assert all(entry["recipient"] == sellers[entry["providerId"]]["address"] for entry in entries)
    models = json.loads((data / "benchmark.json").read_text())["models"]
    assert {model["key"] for model in models} == {entry["key"] for entry in entries}


def candidate(provider: str, key: str, amount: int, speed: float = 100, eci: float = 150, score: float = 50) -> dict:
    return {"key": key, "displayName": key, "providerId": provider, "amountUnits": amount, "outputTokensPerSecond": speed, "eci": eci, "totalScore": score}


def test_우선순위가_보는_지표로_회사별_대표를_뽑고_1등과_가까운_곳만_남긴다():
    candidates = [
        candidate("a", "a-small", 4_000, speed=180, eci=159, score=90),
        candidate("a", "a-big", 160_000, speed=90, eci=168.8, score=70),
        candidate("b", "b-small", 4_000, speed=120, eci=156, score=80),
        candidate("b", "b-big", 80_000, speed=60, eci=168.4, score=60),
        candidate("c", "c-fast", 20_000, speed=430, eci=145, score=55),
    ]
    keys = lambda priority: [item["key"] for item in shortlist(candidates, priority)]
    assert keys("price") == ["a-small", "b-small"]
    assert keys("speed") == ["c-fast"]
    assert keys("intelligence") == ["a-big", "b-big"]
    assert keys("default") == ["a-small", "b-small"]


def test_여러_후보와_흥정해_합의가가_가장_낮은_곳에서_사고_나머지는_취소한다():
    result = shop([candidate("anthropic", "a", 4_001), candidate("openai", "b", 4_001)], "price", LARGE_BUDGET)
    assert result["winner"]["key"] == "b"
    assert result["winner"]["listAmountUnits"] == 4_001
    assert result["winner"]["amountUnits"] == result["negotiation"]["agreedUnits"] < 4_001
    statuses = {quote["key"]: quote["status"] for quote in result["quotes"]}
    assert statuses == {"a": "cancelled", "b": "agreed"}
    cancelled = next(quote for quote in result["quotes"] if quote["key"] == "a")
    assert cancelled["transcript"][-1]["action"] == "reject"


def test_일부가_결렬돼도_합의한_곳에서_산다():
    result = shop([candidate("anthropic", "a", 4_001), candidate("openai", "b", 4_001)], "price", 3_300)
    assert result["winner"]["key"] == "b"
    assert {quote["key"]: quote["status"] for quote in result["quotes"]} == {"a": "no-deal", "b": "agreed"}


def test_후보가_모두_결렬되면_대화_기록과_함께_멈춘다():
    with pytest.raises(NegotiationError) as caught:
        shop([candidate("anthropic", "a", 4_001), candidate("openai", "b", 4_001)], "price", 1)
    assert caught.value.negotiation["status"] == "no-deal"
    assert len(caught.value.negotiation["quotes"]) == 2


def test_산_곳의_판매_에이전트_최저가_아래로_내려가지_않는다():
    for priority in ("price", "speed", "intelligence", "default"):
        record = run_purchase({**INPUT, "priority": priority})
        winner = record["decision"]["winner"]
        seller = find_seller(winner["providerId"])
        assert record["decision"]["negotiation"]["sellerName"] == seller["name"]
        assert winner["amountUnits"] >= winner["listAmountUnits"] * seller["floorRatio"]
        assert record["payment"]["to"].lower() == winner["recipient"].lower()


def test_판매_에이전트가_없는_회사거나_비율이_틀리면_받지_않는다(monkeypatch):
    with pytest.raises(ValueError, match="판매 에이전트가 없는"):
        find_seller("no-such-company")
    monkeypatch.setattr(seller_module, "load_sellers", lambda: {"bad": {"name": "x", "floorRatio": 1.5}})
    with pytest.raises(ValueError, match="floorRatio"):
        find_seller("bad")


def test_합의가로_결제하고_확인까지_통과한다():
    before = buyer_balance()["units"]
    record = run_purchase({**INPUT, "requestId": "req-agreed"})
    winner = record["decision"]["winner"]
    assert record["status"] == "SETTLED"
    assert winner["amountUnits"] == record["decision"]["negotiation"]["agreedUnits"]
    assert winner["amountUnits"] < winner["listAmountUnits"]
    assert record["payment"]["amountUnits"] == winner["amountUnits"]
    assert buyer_balance()["units"] == before - winner["amountUnits"]
    assert record["decision"]["candidates"][0]["amountUnits"] == winner["listAmountUnits"]


def test_요청_번호는_그대로_서명의_일회용_번호로_쓰인다():
    record = run_purchase({**INPUT, "requestId": "req-nonce"})
    assert record["payment"]["requestIdHash"] == request_id_hash("req-nonce")


def test_송금_직전_감사_규칙은_합의가를_본다():
    seen = []
    audit.BEFORE_PAYMENT_CHECKS.append(lambda ctx: seen.append(ctx.decision["winner"]["amountUnits"]))
    record = run_purchase(INPUT)
    assert seen == [record["payment"]["amountUnits"]]


def test_결렬되면_기록도_결제도_결제_후_규칙도_없다():
    after_payment = []
    audit.AFTER_PAYMENT_CHECKS.append(lambda ctx, record: after_payment.append(record))
    before_balance = buyer_balance()["units"]
    before_records = len(store.list_purchases(500))
    with pytest.raises(NegotiationError):
        run_purchase({**INPUT, "budgetUnits": 1})
    assert buyer_balance()["units"] == before_balance
    assert len(store.list_purchases(500)) == before_records
    assert after_payment == []


def test_API_는_결렬을_대화_기록과_함께_409_로_알린다():
    response = TestClient(app).post("/api/purchase", json={"prompt": "결렬 확인", "budget": "0.000001", "priority": "price"})
    assert response.status_code == 409
    assert response.json()["negotiation"]["status"] == "no-deal"
