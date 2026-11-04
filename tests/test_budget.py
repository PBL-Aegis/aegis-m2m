"""
시나리오 3 · 요청 바꿔치기. 같은 문장의 우선순위만 "싸게" → "똑똑하게"로 바꿔 보내면 구매자 한 건 예산에 막히는지 본다.

금액과 모델 이름은 적지 않고 모델 선택 결과에서 읽는다. 예산은 "싸게"로 골라지는 모델 금액보다 조금 높게 둔다.
"""

import pytest
from web3 import Web3

from agent_m2m import store
from agent_m2m.format import aegis_text
from agent_m2m.payment import anvil_account, local_token_address, payment_config, web3_for
from agent_m2m.purchase import run_purchase
from agent_m2m.rules import budget
from agent_m2m.selection import decide

PROMPT = "이 글 요약해 줘"


def _request(priority: str, request_id: str, user_id: str, budget_units: int = 0) -> dict:
    return {"prompt": PROMPT, "budgetUnits": budget_units, "priority": priority, "requestId": request_id, "userId": user_id}


# 체인 규칙 BudgetRule 의 상한을 바꾸는 함수. 운영자(anvil 0번 계정)만 부를 수 있다.
SET_BUDGET_ABI = [
    {
        "type": "function",
        "name": "setBudgetPerPayment",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "wallet", "type": "address"}, {"name": "units", "type": "uint256"}],
        "outputs": [],
    }
]


def _set_chain_budget(units: int) -> None:
    config = payment_config()
    w3 = web3_for(config)
    owner = anvil_account(0)
    token = w3.eth.contract(address=Web3.to_checksum_address(local_token_address()), abi=SET_BUDGET_ABI)
    transaction = token.functions.setBudgetPerPayment(config["buyerAddress"], units).build_transaction(
        {"from": owner.address, "nonce": w3.eth.get_transaction_count(owner.address, "pending"), "chainId": config["chainId"]}
    )
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(owner.sign_transaction(transaction).raw_transaction))
    assert receipt["status"] == 1


def _amount(priority: str) -> int:
    return decide({"prompt": PROMPT, "budgetUnits": 0, "priority": priority})["winner"]["amountUnits"]


def _budget_alerts(purchase_id: str) -> list[dict]:
    return [item for item in store.list_alerts_for_purchase(purchase_id) if item["rule"] == budget.RULE]


@pytest.fixture
def budget_above_cheapest(monkeypatch) -> int:
    cheap, smart = _amount("price"), _amount("intelligence")
    units = cheap + 1
    # 테스트 데이터가 바뀌어 "똑똑하게"도 예산 안에 들어오면 이 테스트는 아무것도 증명하지 못한다.
    assert smart > units, "똑똑하게 모델이 예산보다 비싸야 바꿔치기를 시험할 수 있습니다"
    monkeypatch.setattr(budget, "BUDGET_PER_PAYMENT_UNITS", units)
    return units


def test_싸게는_예산_안이라_통과하고_똑똑하게로_바꿔치면_예산_초과로_막힌다(budget_above_cheapest):
    honest = run_purchase(_request("price", "req-budget-honest", "user-budget-1"))
    assert honest["status"] == "SETTLED"
    assert _budget_alerts(honest["id"]) == []

    tampered = run_purchase(_request("intelligence", "req-budget-tampered", "user-budget-1"))
    amount = tampered["decision"]["winner"]["amountUnits"]
    assert amount > budget_above_cheapest
    assert tampered["status"] == "FAILED"
    assert tampered["failureStage"] == "before-send"
    assert tampered["payment"] is None

    alerts = _budget_alerts(tampered["id"])
    assert len(alerts) == 1
    assert alerts[0]["blocked"] is True and alerts[0]["stage"] == "before-payment"
    # 이유에 예산과 실제 금액이 함께 남는다.
    assert aegis_text(amount) in tampered["failureReason"]
    assert aegis_text(budget_above_cheapest) in tampered["failureReason"]


def test_요청의_budget_을_크게_바꿔도_설정값_기준으로_막힌다(budget_above_cheapest):
    huge = _amount("intelligence") * 1000
    record = run_purchase(_request("intelligence", "req-budget-huge", "user-budget-2", budget_units=huge))
    assert record["status"] == "FAILED"
    assert record["failureStage"] == "before-send"
    assert len(_budget_alerts(record["id"])) == 1


def test_예산과_같은_금액은_통과한다(monkeypatch):
    monkeypatch.setattr(budget, "BUDGET_PER_PAYMENT_UNITS", _amount("intelligence"))
    record = run_purchase(_request("intelligence", "req-budget-equal", "user-budget-3"))
    assert record["status"] == "SETTLED"
    assert _budget_alerts(record["id"]) == []


def test_설정값이_비어_있으면_규칙을_적용하지_않아_SETTLED_로_통과하고_알림도_없다(monkeypatch):
    monkeypatch.setattr(budget, "BUDGET_PER_PAYMENT_UNITS", None)
    record = run_purchase(_request("intelligence", "req-budget-off", "user-budget-4"))
    assert record["status"] == "SETTLED"
    assert _budget_alerts(record["id"]) == []


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("", None), ("  ", None), ("0.1", 100_000), ("1", 1_000_000)])
def test_설정값은_AEGIS_로_읽어_units_로_바꾸고_비어_있으면_끈다(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("AEGIS_BUYER_BUDGET_PER_PAYMENT", raising=False)
    else:
        monkeypatch.setenv("AEGIS_BUYER_BUDGET_PER_PAYMENT", value)
    assert budget._budget_units_from_env() == expected


def test_설정값_형식이_틀리면_서버를_띄울_때_알려_준다(monkeypatch):
    monkeypatch.setenv("AEGIS_BUYER_BUDGET_PER_PAYMENT", "0.1 AEGIS")
    with pytest.raises(ValueError, match="AEGIS_BUYER_BUDGET_PER_PAYMENT"):
        budget._budget_units_from_env()


def test_서버_규칙이_뚫려도_운영자가_정한_체인_상한에서_송금_전에_막힌다(monkeypatch):
    # 서버가 해킹돼 서버 규칙이 꺼진 상황. 체인 상한은 운영자만 정할 수 있어 그대로 남아 있다.
    monkeypatch.setattr(budget, "BUDGET_PER_PAYMENT_UNITS", None)
    cheap, smart = _amount("price"), _amount("intelligence")
    assert smart > cheap + 1
    _set_chain_budget(cheap + 1)

    honest = run_purchase(_request("price", "req-chain-honest", "user-budget-5"))
    assert honest["status"] == "SETTLED"

    tampered = run_purchase(_request("intelligence", "req-chain-tampered", "user-budget-5"))
    assert tampered["status"] == "FAILED"
    assert tampered["failureStage"] == "before-send"
    assert tampered["payment"] is None
    # 체인 오류는 지금 해석하지 않은 오류 데이터 그대로 남는다. 맨 앞 4바이트가 BudgetRule 의 오류 이름이다.
    selector = Web3.keccak(text="OverBuyerBudget(address,uint256,uint256)")[:4].hex()
    assert selector.removeprefix("0x") in tampered["failureReason"]
