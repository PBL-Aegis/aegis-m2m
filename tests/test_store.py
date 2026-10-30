import pytest
from pymongo.errors import DuplicateKeyError

from agent_m2m import store
from agent_m2m.domain import now_iso


def sample(purchase_id: str) -> dict:
    winner = {
        "key": "openai/test-mini",
        "displayName": "테스트 OpenAI",
        "providerId": "openai",
        "providerModelId": "test-mini",
        "recipient": "0xF00E8e0ecEF3B405250242F932849edB409497a0",
        "amountUnits": 12960,
        "outputTokensPerSecond": 60,
        "eci": 140,
        "priceScore": 100,
        "timeScore": 56.547619,
        "intelligenceScore": 75.181159,
        "totalScore": 79.518633,
        "rank": 1,
    }
    return {
        "id": purchase_id,
        "createdAt": now_iso(),
        "prompt": "테스트 요청",
        "status": "SETTLED",
        "decision": {
            "snapshotId": "benchmark-fixture",
            "snapshotHash": "sha256:test",
            "catalogVersion": "agent-m2m-v1",
            "priority": "default",
            "weights": {"price": 34, "time": 33, "intelligence": 33},
            "estimatedInputTokens": 400,
            "maxOutputTokens": 8000,
            "budgetUnits": 50000,
            "references": {"minAmountUnits": 12960},
            "candidates": [winner],
            "rejected": [],
            "winner": winner,
        },
        "payment": {
            "mode": "local",
            "txHash": "0x" + "0" * 64,
            "from": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            "to": winner["recipient"],
            "amountUnits": 12960,
            "tokenAddress": "0x5FbDB2315678afecb367f032d93F642f64180aa3",
            "chainId": 31337,
        },
        "resultText": "결과",
        "failureReason": None,
    }


def test_저장한_기록을_그대로_다시_읽는다():
    record = sample("id-1")
    store.save_purchase(record)
    assert store.purchase_exists("id-1")
    assert store.get_purchase("id-1") == record
    assert store.get_purchase("없는-id") is None


def test_목록은_최신_순이다():
    store.save_purchase({**sample("id-2"), "createdAt": "2026-01-01T00:00:00.000Z"})
    store.save_purchase({**sample("id-3"), "createdAt": "2026-02-01T00:00:00.000Z"})
    ids = [item["id"] for item in store.list_purchases()]
    assert ids.index("id-3") < ids.index("id-2")


def test_같은_구매_번호는_두_번_저장되지_않는다():
    with pytest.raises(DuplicateKeyError):
        store.save_purchase(sample("id-1"))
