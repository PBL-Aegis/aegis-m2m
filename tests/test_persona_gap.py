import pytest

from agent_m2m import audit, store
from agent_m2m.audit import AuditBlockedError, AuditContext
from agent_m2m.benchmark import load_snapshot
from agent_m2m.format import aegis_text
from agent_m2m.payment import buyer_balance
from agent_m2m.persona import load_persona
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import persona_gap
from agent_m2m.selection import decide
from agent_m2m.shopping import shop

BUDGET = 400_000
PROMPT = "이 글 정리해 줘"


@pytest.fixture
def gap_only():
    """다른 규칙은 비우고 persona-gap 규칙만 등록한다(다른 팀원 규칙이 합쳐져도 이 시험은 흔들리지 않게)."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    audit.BEFORE_PAYMENT_CHECKS.append(persona_gap.check_persona_gap)
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


@pytest.fixture
def no_rules():
    """규칙이 하나도 없을 때(공격이 그대로 통하는 상태)."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def request(name: str, persona: str | None = None, priority: str = "price", budget: int = BUDGET) -> dict:
    # 호가는 문장 길이로 정해지므로 문장은 모두 같게 둔다. 사용자와 요청 번호만 다르게 한다.
    body = {"prompt": PROMPT, "budgetUnits": budget, "priority": priority, "userId": f"gap-{name}", "requestId": f"gap-{name}"}
    if persona is not None:
        body["persona"] = persona
    return body


def gap_alerts(user_id: str) -> list[dict]:
    return [alert for alert in store.list_alerts(500) if alert["rule"] == persona_gap.RULE and alert["userId"] == user_id]


def paid(record: dict) -> int:
    return record["decision"]["winner"]["amountUnits"]


def context(persona_id: str, priority: str = "price", budget: int = BUDGET) -> tuple[AuditContext, list[tuple[str, str]]]:
    """체인 없이 송금 직전 문맥만 만든다. 결제 흐름(run_purchase)과 같은 순서로 결정을 채운다."""
    req = {"prompt": PROMPT, "budgetUnits": budget, "priority": priority}
    decision = decide(req, load_snapshot())
    decision.update(shop(decision["candidates"], priority, budget, persona=load_persona(persona_id)))
    alerts: list[tuple[str, str]] = []
    return AuditContext("unit", req, decision, lambda rule, message: alerts.append((rule, message))), alerts


def test_규칙이_없으면_품질형은_최저가형보다_비싸게_사고_결제는_그대로_나간다(no_rules):
    thrifty = run_purchase(request("plain-thrifty", "thrifty"))
    quality = run_purchase(request("plain-quality", "quality"))

    assert thrifty["status"] == quality["status"] == "SETTLED"
    assert paid(quality) > paid(thrifty)  # 같은 요청인데 페르소나 때문에 더 냈다
    assert gap_alerts("gap-plain-quality") == []  # 아무 흔적도 남지 않는다


def test_규칙이_있으면_품질형이_더_낸_차이와_이유가_알림으로_남고_결제는_진행된다(gap_only):
    thrifty = run_purchase(request("alert-thrifty", "thrifty"))
    quality = run_purchase(request("alert-quality", "quality"))

    assert quality["status"] == "SETTLED"
    [alert] = gap_alerts("gap-alert-quality")
    assert (alert["blocked"], alert["stage"]) == (False, "before-payment")
    gap = paid(quality) - paid(thrifty)
    assert aegis_text(paid(thrifty)) in alert["message"]  # 기본 페르소나로 다시 돌린 값
    assert aegis_text(gap) in alert["message"]  # 차이
    assert "품질형" in alert["message"] and "최저가형" in alert["message"]
    assert "에서 시작해" in alert["message"] and "차이의" in alert["message"] and "거래 평가" in alert["message"]  # 라운드·양보 속도, 평가
    assert "닿아" in alert["message"] or "그대로 받아" in alert["message"]  # 어떻게 합의했는지


def test_다시_돌린_값은_실제로_기본_페르소나가_산_값과_같다(gap_only):
    thrifty = run_purchase(request("same-thrifty", "thrifty"))
    ctx, _ = context("quality")
    base = persona_gap.baseline(ctx)

    assert base["priceUnits"] == paid(thrifty)
    assert persona_gap.baseline(ctx) == base  # 몇 번을 돌려도 같다


def test_최저가형과_페르소나를_빼먹은_요청은_알림_없이_통과한다(gap_only):
    assert run_purchase(request("pass-thrifty", "thrifty"))["status"] == "SETTLED"
    assert run_purchase(request("pass-default"))["status"] == "SETTLED"
    assert gap_alerts("gap-pass-thrifty") == [] and gap_alerts("gap-pass-default") == []


def test_차이가_설정한_비율_미만이면_알림_없이_통과한다(gap_only, monkeypatch):
    monkeypatch.setattr(persona_gap, "GAP_RATIO", 1.0)
    assert run_purchase(request("below-ratio", "quality"))["status"] == "SETTLED"
    assert gap_alerts("gap-below-ratio") == []


def test_품질형이_성능_때문에_일부러_더_낸_정상_거래는_알림만_남고_막히지_않는다(gap_only):
    # 우선순위 default: 비교 모델이 둘이라 품질형은 값 한도 안에서 성능을 본다. 평가는 bad 가 아니다(설명 가능).
    record = run_purchase(request("normal-quality", "quality", priority="default"))

    assert record["status"] == "SETTLED"
    assert record["decision"]["evaluation"]["verdict"] in ("good", "partial")
    [alert] = gap_alerts("gap-normal-quality")
    assert alert["blocked"] is False


def test_차이가_차단_비율_이상이면_송금_전에_막히고_이유가_남는다(gap_only, monkeypatch):
    monkeypatch.setattr(persona_gap, "BLOCK_RATIO", 0.05)
    thrifty = run_purchase(request("block-thrifty", "thrifty"))
    balance = buyer_balance()["units"]
    record = run_purchase(request("block-quality", "quality"))

    assert (record["status"], record["failureStage"], record["blockedRule"]) == ("FAILED", "before-send", persona_gap.RULE)
    assert record["payment"] is None and buyer_balance()["units"] == balance
    [alert] = gap_alerts("gap-block-quality")
    assert alert["blocked"] is True
    assert aegis_text(paid(thrifty)) in alert["message"] and "기본 페르소나" in alert["message"]


def test_차이가_있고_평가가_bad_면_설명할_수_없는_손해라_막는다(monkeypatch):
    ctx, alerts = context("quality")
    ctx.decision["evaluation"]["verdict"] = "bad"
    monkeypatch.setattr(persona_gap, "BLOCK_RATIO", 1.0)

    with pytest.raises(AuditBlockedError) as blocked:
        persona_gap.check_persona_gap(ctx)

    assert blocked.value.rule == persona_gap.RULE and "설명할 수 없는" in str(blocked.value)
    assert alerts == []  # 막을 때 알림은 audit.py 가 남긴다


def test_bad_차단을_끄면_같은_경우에도_알림만_남는다(monkeypatch):
    ctx, alerts = context("quality")
    ctx.decision["evaluation"]["verdict"] = "bad"
    monkeypatch.setattr(persona_gap, "BLOCK_RATIO", 1.0)
    monkeypatch.setattr(persona_gap, "BLOCK_BAD", False)

    persona_gap.check_persona_gap(ctx)

    assert [rule for rule, _ in alerts] == [persona_gap.RULE]


def test_모든_흥정이_결렬돼_둘_다_예산을_넘겨도_페르소나_탓이_아니라서_통과한다(gap_only):
    # 예산이 판매자 최저가보다 낮으면 품질형과 최저가형이 같은 값(판매자 최저가)에 산다. 이 규칙의 일이 아니다(over_budget 규칙이 알린다).
    record = run_purchase(request("all-over-budget", "quality", budget=1_000))

    assert record["decision"]["negotiation"]["overBudget"] is True
    assert record["status"] == "SETTLED"
    assert gap_alerts("gap-all-over-budget") == []


def turn(action: str, price: int, rule: str, ratio: float | None = None) -> dict:
    why = {"rule": rule, "inputs": {"ratio": ratio} if ratio is not None else {}}
    return {"from": "buyer", "action": action, "priceUnits": price, "reason": why}


def test_양보_비율과_합의_방식이_문장에_구분되어_나온다():
    opening, up1, up2 = turn("offer", 70, "opening"), turn("offer", 74, "concede", 0.5), turn("offer", 77, "concede", 0.3)

    reached = persona_gap._pace_text("가", [opening, up1, turn("accept", 80, "accept", 0.3)], 80, 100)
    assert "차이의 50%·30%를 차례로 올렸고" in reached and "판매자 값에 닿아 호가의 80%에 합의" in reached

    forced = persona_gap._pace_text("나", [opening, up1, up2, turn("accept", 81, "last-round")], 81, 100)
    assert "차이의 50%·30%를 차례로 올렸고" in forced and "마지막에는 판매자 값을 그대로 받아 호가의 81%에 합의" in forced

    same = persona_gap._pace_text("다", [opening, turn("offer", 72, "concede", 0.15), turn("offer", 74, "concede", 0.15), turn("accept", 80, "last-round")], 80, 100)
    assert "차이의 15%씩 2번 올렸고" in same

    over = persona_gap._pace_text("라", [opening, turn("accept", 95, "over-budget")], 95, 100)
    assert "모든 흥정이 결렬돼 예산을 넘겨" in over

    assert persona_gap._pace_text("마", [], 80, 100) is None
