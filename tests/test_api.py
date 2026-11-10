import json

from fastapi.testclient import TestClient

from agent_m2m.api import app
from agent_m2m.format import parse_aegis

client = TestClient(app)


def test_사람이_적은_AEGIS_금액을_소수점_오차_없이_최소_단위로_바꾼다():
    assert parse_aegis("0.5") == 500_000
    assert parse_aegis(0.1) == 100_000
    assert parse_aegis("3") == 3_000_000
    assert parse_aegis("0.000001") == 1
    assert parse_aegis(" 0.3 ") == 300_000


def test_음수_글자_소수점_7자리_이상은_받지_않는다():
    assert parse_aegis("-1") is None
    assert parse_aegis("abc") is None
    assert parse_aegis("0.0000001") is None
    assert parse_aegis(None) is None


def test_budget_을_AEGIS_로_받아_기록에는_최소_단위로_남긴다():
    response = client.post("/api/purchase", json={"prompt": "이 글 요약해 줘", "budget": "0.5", "priority": "price"})
    assert response.status_code == 200
    record = response.json()
    assert record["status"] == "SETTLED"
    assert record["decision"]["budgetUnits"] == 500_000


def test_예전_이름_budgetUnits_로_보내면_budget_을_쓰라고_400_으로_알린다():
    response = client.post("/api/purchase", json={"prompt": "이 글 요약해 줘", "budgetUnits": 500_000, "priority": "price"})
    assert response.status_code == 400
    assert "budget" in response.json()["error"]


def test_budget_형식이_틀리면_400_이다():
    response = client.post("/api/purchase", json={"prompt": "이 글 요약해 줘", "budget": "많이", "priority": "price"})
    assert response.status_code == 400


def test_빠르게_우선순위는_받지_않는다():
    response = client.post("/api/purchase", json={"prompt": "빨리 해 줘", "budget": "0.5", "priority": "speed"})
    assert response.status_code == 400


def test_화면이_쓰는_조회_API_가_기록과_알림을_돌려준다():
    record = client.post("/api/purchase", json={"prompt": "조회 확인", "budget": "0.5", "priority": "intelligence"}).json()
    assert client.get(f"/api/purchases/{record['id']}").json()["id"] == record["id"]
    assert client.get("/api/purchases/없는-id").status_code == 404
    assert record["id"] in [item["id"] for item in client.get("/api/purchases").json()]
    assert client.get("/api/alerts").json() == {"alerts": [], "linkedPurchaseIds": []}
    assert client.get("/api/alerts/summary").json() == {"blocked": 0, "warnings": 0}
    assert client.get("/api/mode").json() == {"mode": "local"}
    assert isinstance(client.get("/api/wallet").json()["units"], int)


def _stream(body: dict) -> list[dict]:
    response = client.post("/api/purchase/stream", json=body)
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines()]


def test_스트림은_비교_모델_흥정_대화_기록_순서로_보낸다():
    events = _stream({"prompt": "스트림 확인", "budget": "0.5", "priority": "price"})
    assert events[0]["type"] == "plan"
    assert events[-1]["type"] == "done"

    record = events[-1]["record"]
    assert record["status"] == "SETTLED"
    assert [model["key"] for model in events[0]["models"]] == [quote["key"] for quote in record["decision"]["quotes"]]
    for quote in record["decision"]["quotes"]:
        sent = [event["turn"] for event in events if event["type"] == "turn" and event["key"] == quote["key"]]
        assert sent == quote["transcript"]


def test_스트림은_판매자_최저가를_보내지_않는다():
    response = client.post("/api/purchase/stream", json={"prompt": "최저가 확인", "budget": "0.5", "priority": "price"})
    assert "floorRatio" not in response.text
    assert "floorUnits" not in response.text


def test_스트림도_틀린_요청은_시작_전에_400_으로_막는다():
    response = client.post("/api/purchase/stream", json={"prompt": "", "budget": "0.5"})
    assert response.status_code == 400
    assert "prompt" in response.json()["error"]
