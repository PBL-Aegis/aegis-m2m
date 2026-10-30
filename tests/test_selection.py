import json
import shutil

import pytest

from agent_m2m.selection import (
    SelectionError,
    amount_units,
    decide,
    eci_score,
    log_higher_is_better_score,
    log_lower_is_better_score,
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


def test_세_후보가_모두_예산_안이면_기본_우선순위는_테스트_Google_을_고른다():
    decision = decide(request("default"))
    assert decision["estimatedInputTokens"] == 400
    assert len(decision["candidates"]) == 3
    assert decision["rejected"] == []
    assert decision["winner"]["key"] == "google/test-flash"
    assert decision["winner"]["amountUnits"] == 20120
    assert decision["weights"] == {"price": 34, "time": 33, "intelligence": 33}


def test_가격_우선이면_테스트_OpenAI_를_고른다():
    decision = decide(request("price"))
    assert decision["winner"]["key"] == "openai/test-mini"
    assert decision["winner"]["amountUnits"] == 12960
    assert decision["weights"] == {"price": 80, "time": 10, "intelligence": 10}


def test_reasoning_기능을_요구하면_테스트_Google_은_사유와_함께_탈락한다():
    decision = decide(request("default", requiredCapabilities=["reasoning"]))
    assert "google/test-flash" not in [item["key"] for item in decision["candidates"]]
    google = next(item for item in decision["rejected"] if item["key"] == "google/test-flash")
    assert google["reasons"] == ["필요 기능 없음: reasoning"]


def test_같은_입력이면_항상_같은_결과가_나온다():
    assert decide(request("speed")) == decide(request("speed"))


def test_ECI_는_후보_중_최저_0점_최고_100점으로_편다():
    assert eci_score(160, 140, 160) == 100
    assert eci_score(140, 140, 160) == 0
    assert eci_score(150, 140, 160) == 50
    assert eci_score(150, 150, 150) == 100


def test_성능_점수에_ECI_신뢰구간_속도를_잰_AA_항목을_남긴다():
    decision = decide(request("intelligence"))
    haiku = next(item for item in decision["candidates"] if item["key"] == "anthropic/test-haiku")
    assert haiku["intelligenceScore"] == 100
    assert haiku["eci"] == 160
    assert [haiku["eciCiLow"], haiku["eciCiHigh"]] == [157, 163]
    assert haiku["aaModelNames"] == ["Test Haiku"]
    assert decision["references"]["minEci"] == 140
    assert decision["references"]["maxEci"] == 160
    flash = next(item for item in decision["candidates"] if item["key"] == "google/test-flash")
    assert flash["intelligenceScore"] == 50


def test_ECI_가_빠진_모델이_있으면_기본값으로_메우지_않고_멈춘다(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "tests" / "fixtures", tmp_path, dirs_exist_ok=True)
    file = tmp_path / "benchmark.json"
    snapshot = json.loads(file.read_text())
    del snapshot["models"][0]["eci"]
    file.write_text(json.dumps(snapshot))
    monkeypatch.setenv("AGENT_M2M_DATA_DIR", str(tmp_path))
    with pytest.raises(SelectionError):
        decide(request("default"))


def test_가장_싼_값_100점_가장_비싼_값_0점이고_2배_차이는_어느_구간에서든_같은_점수_차이다():
    assert log_lower_is_better_score(1, 1, 8) == 100
    assert log_lower_is_better_score(8, 1, 8) == pytest.approx(0, abs=1e-9)
    step1 = log_lower_is_better_score(1, 1, 8) - log_lower_is_better_score(2, 1, 8)
    step2 = log_lower_is_better_score(4, 1, 8) - log_lower_is_better_score(8, 1, 8)
    assert step1 == pytest.approx(step2, abs=1e-9)
    assert log_lower_is_better_score(5, 5, 5) == 100


def test_가격_우선에서_가장_싼_후보_100점_가장_비싼_후보_0점_중간은_로그_위치대로다():
    decision = decide(request("price"))
    score = {item["key"]: item["priceScore"] for item in decision["candidates"]}
    assert score["openai/test-mini"] == 100
    assert score["anthropic/test-haiku"] == 0
    assert score["google/test-flash"] == pytest.approx(61.31, abs=0.05)


def test_출력_속도는_클수록_좋다():
    assert log_higher_is_better_score(150, 40, 150) == 100
    assert log_higher_is_better_score(40, 40, 150) == pytest.approx(0, abs=1e-9)
    decision = decide(request("speed"))
    assert decision["winner"]["key"] == "google/test-flash"
    assert decision["winner"]["outputTokensPerSecond"] == 150
    assert decision["references"]["minOutputTokensPerSecond"] == 40
    assert decision["references"]["maxOutputTokensPerSecond"] == 150
