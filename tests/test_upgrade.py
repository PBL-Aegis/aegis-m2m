import pytest

from agent_m2m import audit, purchase, store
from agent_m2m.payment import buyer_balance
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import upgrade


@pytest.fixture(autouse=True)
def upgrade_only():
    """다른 규칙은 비우고 이 규칙만 등록한다(다른 팀원 규칙이 합쳐져도 이 시험은 흔들리지 않게)."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    audit.BEFORE_PAYMENT_CHECKS.append(upgrade.check_unintended_upgrade)
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def gemma_picks(monkeypatch, priority: str) -> None:
    """로컬 Gemma 가 요청 문장을 보고 이 우선순위를 골랐다고 둔다."""
    monkeypatch.setattr(purchase, "infer_priority", lambda prompt: {"priority": priority, "model": "gemma-test"})


def request(name: str, priority: str | None = None) -> dict:
    body = {"prompt": f"이 글 정리해 줘 {name}", "budgetUnits": 400_000, "userId": f"upgrade-{name}", "requestId": f"upgrade-{name}"}
    if priority is not None:
        body["priority"] = priority
    return body


def blocks_of(user_id: str) -> list[dict]:
    return [alert for alert in store.list_alerts(500) if alert["rule"] == upgrade.RULE and alert["userId"] == user_id]


def test_Gemma_가_정한_우선순위로_상위_등급을_사면_송금_전에_막힌다(monkeypatch):
    gemma_picks(monkeypatch, "intelligence")
    balance = buyer_balance()["units"]

    record = run_purchase(request("gemma-up"))

    assert (record["status"], record["failureStage"], record["blockedRule"]) == ("FAILED", "before-send", upgrade.RULE)
    assert record["decision"]["prioritySource"] == "local-llm"
    assert buyer_balance()["units"] == balance
    [block] = blocks_of("upgrade-gemma-up")
    assert block["blocked"] is True
    assert "intelligence" in block["message"] and record["decision"]["winner"]["displayName"] in block["message"]


def test_사용자가_직접_상위_등급을_고르면_막지_않는다(monkeypatch):
    gemma_picks(monkeypatch, "price")  # 불리면 안 된다. 불리면 등급이 바뀌어 아래 확인이 깨진다.

    record = run_purchase(request("user-up", "intelligence"))

    assert record["status"] == "SETTLED"
    assert record["decision"]["prioritySource"] == "request"
    assert blocks_of("upgrade-user-up") == []


@pytest.mark.parametrize("priority", [tier for tier in upgrade.TIERS if upgrade.TIERS.index(tier) <= upgrade.TIERS.index(upgrade.MAX_PRIORITY)])
def test_Gemma_가_한도_안의_등급을_정하면_막지_않는다(monkeypatch, priority):
    gemma_picks(monkeypatch, priority)

    record = run_purchase(request(f"gemma-{priority}"))

    assert record["status"] == "SETTLED"
    assert blocks_of(f"upgrade-gemma-{priority}") == []


def test_한도를_가장_높은_등급으로_두면_Gemma_가_정해도_막지_않는다(monkeypatch):
    gemma_picks(monkeypatch, "intelligence")
    monkeypatch.setattr(upgrade, "MAX_PRIORITY", upgrade.TIERS[-1])

    record = run_purchase(request("gemma-allowed"))

    assert record["status"] == "SETTLED"
