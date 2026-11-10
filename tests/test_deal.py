import copy
import json
from pathlib import Path

import pytest
from web3 import Web3

from agent_m2m import audit, provider, store
from agent_m2m.deal import deal_tuple, hash_deal, transcript_hash
from agent_m2m.payment import payment_config, request_id_hash, web3_for
from agent_m2m.provider import DeliveryError, verify_deal
from agent_m2m.purchase import run_purchase

INPUT = {"prompt": "이 글 요약해 줘", "budgetUnits": 10_000_000, "priority": "price"}
ARTIFACT = Path(__file__).resolve().parent.parent / "contracts" / "out" / "AegisToken.sol" / "AegisToken.json"


@pytest.fixture(autouse=True)
def empty_rules():
    """합의 저장만 시험하므로, 등록된 실제 감사 규칙을 잠시 비운다."""
    lists = (audit.ON_REQUEST_CHECKS, audit.BEFORE_PAYMENT_CHECKS, audit.AFTER_PAYMENT_CHECKS)
    saved = [checks.copy() for checks in lists]
    for checks in lists:
        checks.clear()
    yield
    for checks, original in zip(lists, saved):
        checks[:] = original


def token():
    config = payment_config()
    abi = json.loads(ARTIFACT.read_text())["abi"]
    return web3_for(config).eth.contract(address=config["tokenAddress"], abi=abi)


def test_흥정한_구매는_합의를_체인에_저장하고_합의가만큼_보낸다():
    record = run_purchase({**INPUT, "requestId": "req-deal"})
    decision, payment = record["decision"], record["payment"]
    deal = decision["deal"]
    assert record["status"] == "SETTLED"
    assert deal["requestId"] == request_id_hash("req-deal")
    assert deal["agreedUnits"] == decision["winner"]["amountUnits"] == payment["amountUnits"]
    assert deal["askUnits"] == decision["winner"]["listAmountUnits"]
    assert deal["transcriptHash"] == transcript_hash(decision["negotiation"])
    assert payment["dealHash"] == hash_deal(deal)

    stored = token().functions.deals(Web3.to_bytes(hexstr=deal["requestId"])).call()
    assert list(stored) == list(deal_tuple(deal))


def test_서버가_계산한_합의_해시는_컨트랙트의_hashDeal_과_같다():
    deal = run_purchase({**INPUT, "requestId": "req-hash"})["decision"]["deal"]
    assert Web3.to_hex(token().functions.hashDeal(deal_tuple(deal)).call()) == hash_deal(deal)


def test_DB_의_대화를_고치면_판매창구가_체인의_합의와_달라_알아챈다():
    record = run_purchase({**INPUT, "requestId": "req-tamper"})
    saved = store.get_purchase(record["id"])
    verify_deal(saved["payment"], saved["decision"])

    edited = copy.deepcopy(saved["decision"])
    edited["negotiation"]["transcript"][-1]["priceUnits"] += 1
    with pytest.raises(DeliveryError, match="흥정 대화"):
        verify_deal(saved["payment"], edited)

    edited = copy.deepcopy(saved["decision"])
    edited["deal"]["agreedUnits"] -= 1
    with pytest.raises(DeliveryError, match="DealSettled"):
        verify_deal(saved["payment"], edited)


def test_판매창구가_합의를_확인하지_못하면_결과를_주지_않는다(monkeypatch):
    def no_logs(tx_hash):
        receipt = dict(web3_for(payment_config()).eth.get_transaction_receipt(tx_hash))
        return {**receipt, "logs": [log for log in receipt["logs"] if provider._settled_deal(log, payment_config()["tokenAddress"]) is None]}

    monkeypatch.setattr(provider, "get_receipt", no_logs)
    record = run_purchase({**INPUT, "requestId": "req-no-deal-log"})
    assert record["status"] == "FAILED"
    assert record["failureStage"] == "after-send"
    assert record["resultText"] is None
