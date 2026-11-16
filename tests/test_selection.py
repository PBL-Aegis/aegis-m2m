import json
import shutil

import pytest

from agent_m2m.selection import (
    SelectionError,
    amount_units,
    decide,
)
from tests.conftest import ROOT

# 400 입력 토큰이 나오도록 1600 바이트짜리 ASCII 요청을 만든다(4바이트 = 1토큰 어림).
PROMPT_400 = "a" * 1600


def request(priority: str, **extra):
    return {"prompt": PROMPT_400, "budgetUnits": 50_000, "priority": priority, **extra}


def test_입력_400_최대_출력_8000_토큰일_때_세_모델의_금액():
    assert amount_units(400, 8000, "0.4", "1.6") == 12960
    assert amount_units(400, 8000, "1", "5") == 40400
    assert amount_units(400, 8000, "0.3", "2.5") == 20120


def test_필요_기능을_통과한_후보마다_호가와_ECI_를_남긴다():
    decision = decide(request("default"))
    assert decision["estimatedInputTokens"] == 400
    assert decision["rejected"] == []
    assert {item["key"]: item["amountUnits"] for item in decision["candidates"]} == {
        "openai/test-mini": 12960,
        "anthropic/test-haiku": 40400,
        "google/test-flash": 20120,
    }
    haiku = next(item for item in decision["candidates"] if item["key"] == "anthropic/test-haiku")
    assert [haiku["eci"], haiku["eciCiLow"], haiku["eciCiHigh"]] == [160, 157, 163]


def test_reasoning_기능을_요구하면_테스트_Google_은_사유와_함께_탈락한다():
    decision = decide(request("default", requiredCapabilities=["reasoning"]))
    assert "google/test-flash" not in [item["key"] for item in decision["candidates"]]
    google = next(item for item in decision["rejected"] if item["key"] == "google/test-flash")
    assert google["reasons"] == ["필요 기능 없음: reasoning"]


def test_같은_입력이면_항상_같은_결과가_나온다():
    assert decide(request("default")) == decide(request("default"))


def test_ECI_가_빠진_모델이_있으면_기본값으로_메우지_않고_멈춘다(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "tests" / "fixtures", tmp_path, dirs_exist_ok=True)
    file = tmp_path / "benchmark.json"
    snapshot = json.loads(file.read_text())
    del snapshot["models"][0]["eci"]
    file.write_text(json.dumps(snapshot))
    monkeypatch.setenv("AGENT_M2M_DATA_DIR", str(tmp_path))
    with pytest.raises(SelectionError):
        decide(request("default"))
