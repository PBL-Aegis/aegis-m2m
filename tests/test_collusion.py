"""
시나리오 ③ · 판매자 담합. 판매자의 최저가 비율(floorRatio)을 바꿔 "서로 깎지 않는 시장"을 만들고 알림이 남는지 본다.

판매자 설정은 seller.load_sellers 를, 등급별 비교 모델은 shopping.load_priority_models 를 바꿔 끼운다.
모델 이름과 금액은 적지 않고 픽스처에서 읽는다. 체인은 지갑당 60초에 5건까지라 구매마다 시계를 61초 돌린다.
"""

import pytest

from agent_m2m import audit, benchmark, seller as seller_module, shopping, store
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import collusion
from agent_m2m.selection import decide
from tests.helpers import increase_chain_time

BUDGET_UNITS = 400_000


@pytest.fixture(autouse=True)
def collusion_only(monkeypatch):
    """다른 규칙은 비우고 이 규칙만 등록한다. 기록은 테스트마다 비우고, 최근 N건은 3건으로 줄인다."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    audit.AFTER_PAYMENT_CHECKS.append(collusion.check_collusion)
    store.database()[collusion.QUOTES].delete_many({})
    monkeypatch.setattr(collusion, "WINDOW", 3)
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def set_floors(monkeypatch, floors: dict[str, float]) -> None:
    """회사별 최저가 비율을 바꾼다. 적지 않은 회사는 픽스처 값 그대로다."""
    sellers = benchmark.load_sellers()
    changed = {company: {**seller, "floorRatio": floors.get(company, seller["floorRatio"])} for company, seller in sellers.items()}
    monkeypatch.setattr(seller_module, "load_sellers", lambda: changed)


def everyone(ratio: float) -> dict[str, float]:
    return {company: ratio for company in benchmark.load_sellers()}


def set_tiers(monkeypatch, tiers: dict[str, list[str]]) -> None:
    monkeypatch.setattr(shopping, "load_priority_models", lambda: {**benchmark.load_priority_models(), **tiers})


def keys_by_price() -> list[str]:
    """픽스처 모델을 호가가 싼 순서로. 판매 회사가 모두 다르다."""
    candidates = decide({"prompt": "호가 순서", "budgetUnits": BUDGET_UNITS, "priority": "default"})["candidates"]
    return [candidate["key"] for candidate in sorted(candidates, key=lambda candidate: candidate["amountUnits"])]


def two_sellers(monkeypatch) -> list[str]:
    """'기본' 등급에서 가장 싼 두 모델(서로 다른 판매자)을 비교하게 한다."""
    keys = keys_by_price()[:2]
    set_tiers(monkeypatch, {"default": keys})
    return keys


def buy(name: str, index: int, priority: str = "default", persona: str = "thrifty") -> dict:
    increase_chain_time(61)
    return run_purchase(
        {
            "prompt": f"이 글 정리해 줘 {name} {index}",
            "budgetUnits": BUDGET_UNITS,
            "priority": priority,
            "persona": persona,
            "userId": f"collusion-{name}",
            "requestId": f"collusion-{name}-{index}",
        }
    )


def alerts_of(name: str, kind: str = "") -> list[dict]:
    return [
        alert
        for alert in store.list_alerts(500)
        if alert["rule"] == collusion.RULE and alert["userId"] == f"collusion-{name}" and kind in alert["message"]
    ]


def seller_names(record: dict) -> list[str]:
    return [quote["sellerName"] for quote in record["decision"]["quotes"]]


def test_규칙이_없으면_두_판매자가_깎지_않아도_호가_전액에_결제되고_알림이_없다(monkeypatch):
    audit.AFTER_PAYMENT_CHECKS.clear()
    two_sellers(monkeypatch)
    set_floors(monkeypatch, everyone(1.0))

    records = [buy("no-rule", index) for index in range(collusion.WINDOW)]

    for record in records:
        winner = record["decision"]["winner"]
        assert record["status"] == "SETTLED"
        assert winner["amountUnits"] == winner["listAmountUnits"]
    assert alerts_of("no-rule") == []


def test_두_판매자가_깎지_않으면_N건째에_가격_맞추기_알림이_남고_결제는_된다(monkeypatch):
    two_sellers(monkeypatch)
    set_floors(monkeypatch, everyone(1.0))

    records = [buy("fixed", index) for index in range(collusion.WINDOW)]

    assert all(record["status"] == "SETTLED" for record in records)
    alerts = alerts_of("fixed", "가격 맞추기")
    assert [alert["purchaseId"] for alert in alerts] == [records[-1]["id"]]
    [alert] = alerts
    assert alert["blocked"] is False and alert["stage"] == "after-payment"
    for name in seller_names(records[-1]):
        assert name in alert["message"]


def test_기준과의_차이가_기준값과_딱_같아도_알린다(monkeypatch):
    two_sellers(monkeypatch)
    set_floors(monkeypatch, everyone(round(collusion.REFERENCE_FLOOR_RATIO + collusion.GAP, 6)))

    records = [buy("edge", index) for index in range(collusion.WINDOW)]

    assert [alert["purchaseId"] for alert in alerts_of("edge", "가격 맞추기")] == [records[-1]["id"]]


def test_정상_최저가_비율이면_품질형처럼_덜_깎는_구매자도_알림이_없다(monkeypatch):
    two_sellers(monkeypatch)
    personas = ["thrifty"] * collusion.WINDOW + ["quality"] * collusion.WINDOW
    records = [buy("normal", index, persona=persona) for index, persona in enumerate(personas)]

    assert all(record["status"] == "SETTLED" for record in records)
    # 품질형은 정상 거래에서도 최저가형보다 호가에 가깝게 산다. 기준을 같은 페르소나로 다시 돌려 이 차이는 담합으로 세지 않는다.
    ratios = [record["decision"]["winner"]["amountUnits"] / record["decision"]["winner"]["listAmountUnits"] for record in records]
    assert min(ratios[collusion.WINDOW :]) > max(ratios[: collusion.WINDOW])
    assert alerts_of("normal") == []


def test_한_판매자만_깎지_않으면_구매자가_다른_곳에서_사서_알림이_없다(monkeypatch):
    keys = two_sellers(monkeypatch)
    holdout = keys[1].split("/")[0]
    set_floors(monkeypatch, {holdout: 1.0})

    records = [buy("one", index) for index in range(collusion.WINDOW)]

    assert all(record["decision"]["winner"]["key"] == keys[0] for record in records)
    assert alerts_of("one") == []


def test_두_판매자가_함께_값을_올리면_같이_오름_알림이_남는다(monkeypatch):
    two_sellers(monkeypatch)
    set_floors(monkeypatch, everyone(collusion.REFERENCE_FLOOR_RATIO))
    for index in range(collusion.WINDOW):
        buy("rise", index)
    assert alerts_of("rise") == []

    # 가격 맞추기 기준(GAP)에는 못 미치지만 같이 오른 폭(RISE)은 넘게 올린다.
    raised = collusion.REFERENCE_FLOOR_RATIO + (collusion.RISE + collusion.GAP) / 2
    set_floors(monkeypatch, everyone(raised))
    records = [buy("rise", collusion.WINDOW + index) for index in range(collusion.WINDOW)]

    assert [alert["purchaseId"] for alert in alerts_of("rise", "같이 오름")] == [records[-1]["id"]]
    assert alerts_of("rise", "가격 맞추기") == []


def test_아무도_깎지_않는_두_등급에서_이기는_판매자가_갈리면_시장_나누기_알림이_남는다(monkeypatch):
    cheap, middle, expensive = keys_by_price()
    set_tiers(monkeypatch, {"price": [cheap, middle], "intelligence": [middle, expensive]})
    set_floors(monkeypatch, everyone(1.0))

    price = [buy("split", index, "price") for index in range(collusion.WINDOW)]
    assert alerts_of("split", "시장 나누기") == []
    smart = [buy("split", collusion.WINDOW + index, "intelligence") for index in range(collusion.WINDOW)]

    assert {record["decision"]["winner"]["key"] for record in price} == {cheap}
    assert {record["decision"]["winner"]["key"] for record in smart} == {middle}
    [alert] = alerts_of("split", "시장 나누기")
    assert alert["purchaseId"] == smart[-1]["id"]
    assert price[0]["decision"]["negotiation"]["sellerName"] in alert["message"]
    assert smart[0]["decision"]["negotiation"]["sellerName"] in alert["message"]


def test_송금_전에_실패한_구매는_세지_않는다(monkeypatch):
    two_sellers(monkeypatch)
    set_floors(monkeypatch, everyone(1.0))
    audit.BEFORE_PAYMENT_CHECKS.append(lambda ctx: (_ for _ in ()).throw(audit.AuditBlockedError("test-block", "시험용 차단")))

    records = [buy("failed", index) for index in range(collusion.WINDOW)]

    assert all(record["status"] == "FAILED" for record in records)
    assert store.database()[collusion.QUOTES].count_documents({}) == 0
    assert alerts_of("failed") == []


@pytest.mark.parametrize(("name", "value"), [("AUDIT_COLLUSION_GAP", "0"), ("AUDIT_COLLUSION_SHARE", "1.5"), ("AUDIT_COLLUSION_REFERENCE_FLOOR", "높게")])
def test_비율_설정값이_틀리면_서버를_띄울_때_알려_준다(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        collusion._ratio(name, "0.1")


@pytest.mark.parametrize("value", ["0", "-1", "다섯"])
def test_최근_건수_설정값이_틀리면_서버를_띄울_때_알려_준다(monkeypatch, value):
    monkeypatch.setenv("AUDIT_COLLUSION_WINDOW", value)
    with pytest.raises(ValueError, match="AUDIT_COLLUSION_WINDOW"):
        collusion._positive_integer("AUDIT_COLLUSION_WINDOW", "5")
