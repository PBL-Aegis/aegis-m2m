import json
import shutil

import httpx
import pytest

from agent_m2m import benchmark_sources, store
from agent_m2m.benchmark import load_fresh_snapshot
from agent_m2m.domain import parse_iso_ms
from tests.conftest import ROOT

HOUR_MS = 60 * 60 * 1000

MODELS = [
    {"epoch": "Test Mini", "openRouter": "openai/test-mini", "aa": "test-mini"},
    {"epoch": "Test Haiku", "openRouter": "anthropic/test-haiku", "aa": "test-haiku"},
    {"epoch": "Test Flash", "openRouter": "google/test-flash", "aa": "test-flash"},
]


@pytest.fixture(autouse=True)
def fixture_copy(tmp_path, monkeypatch):
    """픽스처를 임시 폴더에 복사해 쓴다. 시작값(benchmark.json)은 픽스처 그대로다."""
    shutil.copytree(ROOT / "tests" / "fixtures", tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("AGENT_M2M_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AA_API_KEY", "test-key")


def fake_sources(calls: list[str]):
    """세 출처를 흉내 낸다. Epoch 는 CSV, 나머지는 JSON 이다."""

    def get(url: str, headers=None) -> httpx.Response:
        calls.append(url)
        if url.startswith("https://epoch.ai/"):
            header = "Model,Display name,eci,eci_ci_low,eci_ci_high,date,Organization,Country (of organization),Model accessibility,Accessibility group,model_versions"
            rows = [f"{model['epoch']},{model['epoch']},150,148,152,2026-10-01,Org,Country,API access,Closed weights," for model in MODELS]
            return httpx.Response(200, text="\n".join([header, *rows]))
        if url.startswith("https://openrouter.ai/"):
            data = [
                {"id": model["openRouter"], "name": model["epoch"], "pricing": {"prompt": "0.000001", "completion": "0.000002"}}
                for model in MODELS
            ]
            return httpx.Response(200, text=json.dumps({"data": data}))
        data = [{"slug": model["aa"], "name": model["epoch"], "performance": {"median_output_tokens_per_second": 100}} for model in MODELS]
        return httpx.Response(200, text=json.dumps({"data": data}))

    return get


def test_값이_1시간보다_오래되면_실패해도_마지막_값으로_계속하고_사유를_남긴다(monkeypatch):
    monkeypatch.setattr(benchmark_sources, "http_get", lambda url, headers=None: httpx.Response(503, text="down"))
    result = load_fresh_snapshot()
    assert result["snapshot"]["snapshotId"] == "test-fixture-v3"
    assert "503" in result["refreshError"]


def test_값이_오래되면_세_출처에서_새로_받아_저장한다(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(benchmark_sources, "http_get", fake_sources(calls))
    result = load_fresh_snapshot()
    assert result["refreshError"] is None
    assert [[model["key"], model["eci"], model["inputPricePerMillion"]] for model in result["snapshot"]["models"]] == [
        ["openai/test-mini", "150", "1"],
        ["anthropic/test-haiku", "150", "1"],
        ["google/test-flash", "150", "1"],
    ]
    assert len(calls) == 3
    assert store.latest_snapshot() == {"snapshot": result["snapshot"], "hash": result["hash"]}


def test_1시간이_지나지_않았으면_다시_받지_않는다(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(benchmark_sources, "http_get", fake_sources(calls))
    latest = store.latest_snapshot()
    result = load_fresh_snapshot(parse_iso_ms(latest["snapshot"]["capturedAt"]) + HOUR_MS - 1)
    assert calls == []
    assert result["hash"] == latest["hash"]
