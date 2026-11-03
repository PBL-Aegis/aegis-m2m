import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_m2m import audit, benchmark, seller as seller_module, shopping, store
from agent_m2m.api import app
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.payment import buyer_balance, request_id_hash
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import over_budget
from agent_m2m.selection import SelectionError
from agent_m2m.seller import SellerAgent, find_seller
from agent_m2m.shopping import compared_models, shop
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


def test_첫_제안은_호가의_75퍼센트고_양쪽은_차이의_절반씩_움직인다():
    turns = negotiate(4_000, LARGE_BUDGET, 0.5)["transcript"]
    assert [turn["priceUnits"] for turn in turns[:4]] == [3_000, 3_500, 3_250, 3_380]


def test_값을_내리지_않는_판매자는_마지막에_최대가_안이면_호가로_산다():
    result = negotiate(100_000, LARGE_BUDGET, 1)
    assert result["agreedUnits"] == 100_000
    assert sum(turn["action"] == "offer" for turn in result["transcript"]) == 5


def test_판매자의_마지막_값이_최대가를_넘으면_결렬이다():
    with pytest.raises(NegotiationError) as caught:
        negotiate(100_000, 80_000, 0.85)
    negotiation = caught.value.negotiation
    assert negotiation["status"] == "no-deal"
    assert negotiation["transcript"][-1]["action"] == "reject"


def test_실제_판매_목록은_두_판매_에이전트의_6개_모델이고_비교_표도_그_안에_있다():
    data = Path(__file__).resolve().parent.parent / "data"
    registry = json.loads((data / "sellers.json").read_text())
    sellers = registry["sellers"]
    assert set(sellers) == {"anthropic", "openai"}
    assert all(0 < seller["floorRatio"] <= 0.9 for seller in sellers.values())
    entries = json.loads((data / "catalog.json").read_text())["entries"]
    assert len(entries) == 6
    assert all(entry["displayName"] in sellers[entry["providerId"]]["models"] for entry in entries)
    assert all(entry["recipient"] == sellers[entry["providerId"]]["address"] for entry in entries)
    models = json.loads((data / "benchmark.json").read_text())["models"]
    keys = {entry["key"] for entry in entries}
    assert {model["key"] for model in models} == keys
    assert set(registry["priorityModels"]) == {"price", "default", "intelligence"}
    assert set().union(*registry["priorityModels"].values()) == keys


def candidate(provider: str, key: str, amount: int) -> dict:
    return {"key": key, "displayName": key, "providerId": provider, "amountUnits": amount}


def use_table(monkeypatch, table: dict) -> None:
    monkeypatch.setattr(shopping, "load_priority_models", lambda: table)


def test_우선순위별_비교_모델은_표에서_읽고_없는_모델은_건너뛴다(monkeypatch):
    use_table(monkeypatch, {"price": ["z", "b", "a"], "speed": ["z"]})
    candidates = [candidate("anthropic", "a", 1_000), candidate("openai", "b", 1_000)]
    assert [item["key"] for item in compared_models(candidates, "price")] == ["b", "a"]
    with pytest.raises(SelectionError):
        compared_models(candidates, "speed")


def test_여러_모델과_흥정해_합의가가_가장_낮은_곳에서_사고_나머지는_취소한다(monkeypatch):
    use_table(monkeypatch, {"price": ["a", "b"]})
    result = shop([candidate("anthropic", "a", 4_001), candidate("openai", "b", 4_001)], "price", LARGE_BUDGET)
    assert result["winner"]["key"] == "b"
    assert result["winner"]["listAmountUnits"] == 4_001
    assert result["winner"]["amountUnits"] == result["negotiation"]["agreedUnits"] < 4_001
    assert {quote["key"]: quote["status"] for quote in result["quotes"]} == {"a": "cancelled", "b": "agreed"}
    cancelled = next(quote for quote in result["quotes"] if quote["key"] == "a")
    assert cancelled["transcript"][-1]["action"] == "reject"


def test_일부가_결렬돼도_합의한_곳에서_산다(monkeypatch):
    use_table(monkeypatch, {"price": ["a", "b"]})
    result = shop([candidate("anthropic", "a", 4_001), candidate("openai", "b", 4_001)], "price", 3_350)
    assert result["winner"]["key"] == "b"
    assert {quote["key"]: quote["status"] for quote in result["quotes"]} == {"a": "no-deal", "b": "agreed"}


def test_비교_모델이_모두_결렬되면_판매자_마지막_값이_가장_낮은_곳에서_예산을_넘겨_산다(monkeypatch):
    use_table(monkeypatch, {"price": ["a", "b"]})
    result = shop([candidate("anthropic", "a", 4_001), candidate("openai", "b", 4_001)], "price", 3_300)
    assert result["winner"]["key"] == "b"
    assert result["winner"]["amountUnits"] > 3_300
    assert result["negotiation"]["overBudget"] is True
    assert {quote["key"]: quote["status"] for quote in result["quotes"]} == {"a": "no-deal", "b": "agreed"}


def test_판매자_값을_하나도_못_받으면_멈춘다(monkeypatch):
    use_table(monkeypatch, {"price": ["a"]})
    monkeypatch.setattr(shopping, "negotiate", lambda *args: (_ for _ in ()).throw(NegotiationError("막힘", {"status": "blocked", "transcript": []})))
    with pytest.raises(NegotiationError):
        shop([candidate("anthropic", "a", 4_001)], "price", 1)


def test_산_곳의_판매_에이전트_최저가_아래로_내려가지_않는다():
    for priority in ("price", "intelligence", "default"):
        record = run_purchase({**INPUT, "priority": priority})
        winner = record["decision"]["winner"]
        seller = find_seller(winner["providerId"])
        assert record["decision"]["negotiation"]["sellerName"] == seller["name"]
        assert winner["amountUnits"] >= winner["listAmountUnits"] * seller["floorRatio"]
        assert record["payment"]["to"].lower() == winner["recipient"].lower()


def test_구매_때_벤치마크를_새로_받지_않는다(monkeypatch):
    def fail(*args):
        raise AssertionError("외부 벤치마크를 불렀습니다")

    monkeypatch.setattr(benchmark, "_refresh", fail)
    assert run_purchase(INPUT)["status"] == "SETTLED"


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


def test_예산이_너무_낮아도_결제하고_예산_초과_경고를_남긴다():
    audit.BEFORE_PAYMENT_CHECKS.append(over_budget.check_over_budget)
    before = buyer_balance()["units"]
    record = run_purchase({**INPUT, "budgetUnits": 1, "requestId": "req-over-budget", "userId": "user-over"})
    amount = record["payment"]["amountUnits"]
    assert record["status"] == "SETTLED"
    assert record["decision"]["negotiation"]["overBudget"] is True
    assert amount == record["decision"]["winner"]["amountUnits"] > 1
    assert buyer_balance()["units"] == before - amount
    alerts = store.list_alerts_for_purchase(record["id"])
    assert [(item["rule"], item["blocked"]) for item in alerts] == [("over-budget", False)]


def test_API_는_예산이_낮아도_구매_기록을_돌려준다():
    response = TestClient(app).post("/api/purchase", json={"prompt": "예산 확인", "budget": "0.000001", "priority": "price"})
    assert response.status_code == 200
    assert response.json()["status"] == "SETTLED"
