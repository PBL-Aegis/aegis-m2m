from agent_m2m.benchmark_sources import build_catalog, build_snapshot, normalize_name, parse_csv, per_million


def test_토큰당_단가를_1M_토큰당_단가로_소수점_오차_없이_바꾼다():
    assert per_million("0.0000001") == "0.1"
    assert per_million("0.000002") == "2"
    assert per_million("0.00000025") == "0.25"
    assert per_million("0.0000002574") == "0.2574"


def test_0_음수_빈_값은_가격으로_쓰지_않는다():
    assert per_million("0") is None
    assert per_million("-1") is None
    assert per_million(None) is None


def test_따옴표_안의_쉼표를_지킨다():
    assert parse_csv('Model,note\nA,"x, y"\n') == [{"Model": "A", "note": "x, y"}]


def epoch(name: str, eci: str = "150") -> dict:
    return {"Model": name, "eci": eci, "eci_ci_low": "148", "eci_ci_high": "152", "date": "2026-10-01"}


def listing(model_id: str, name: str, prompt: str = "0.000001") -> dict:
    return {
        "id": model_id,
        "name": f"Org: {name}",
        "pricing": {"prompt": prompt, "completion": "0.000002"},
        "supported_parameters": ["reasoning", "tools"],
        "architecture": {"input_modalities": ["text", "image"]},
    }


def recipient(provider: str) -> str:
    return f"0x{provider}"


def test_두_출처_이름이_기호_대소문자만_다르면_짝짓고_OpenRouter_기능을_옮긴다():
    catalog = build_catalog(
        [epoch("Claude Opus 5.5")],
        [listing("anthropic/claude-opus-5.5", "Claude Opus 5.5")],
        recipient,
    )
    assert catalog["entries"] == [
        {
            "key": "anthropic/claude-opus-5.5",
            "providerId": "anthropic",
            "providerModelId": "claude-opus-5.5",
            "displayName": "Claude Opus 5.5",
            "epochModel": "Claude Opus 5.5",
            "openRouterId": "anthropic/claude-opus-5.5",
            "recipient": "0xanthropic",
            "capabilities": ["reasoning", "tools", "vision"],
        }
    ]
    assert normalize_name("Claude Opus 5.5") == normalize_name("claude-opus-5.5")


def test_스냅샷은_두_출처의_값만_담는다():
    epoch_rows = [epoch("Model A")]
    listings = [listing("org/model-a", "Model A")]
    catalog = build_catalog(epoch_rows, listings, recipient)
    snapshot = build_snapshot(catalog, epoch_rows, listings)
    assert snapshot["source"] == "epoch.ai + openrouter.ai"
    assert set(snapshot["sources"]) == {"epoch", "openRouter"}
    assert snapshot["models"][0] == {
        "key": "org/model-a",
        "epochModel": "Model A",
        "epochDate": "2026-10-01",
        "eci": "150",
        "eciCiLow": "148",
        "eciCiHigh": "152",
        "inputPricePerMillion": "1",
        "outputPricePerMillion": "2",
        "openRouterId": "org/model-a",
    }


def test_이름이_다르거나_가격이_0_이면_추측하지_않고_이유와_함께_뺀다():
    catalog = build_catalog(
        [epoch("Model C"), epoch("Model D")],
        [listing("org/model-c-pro", "Model C Pro"), listing("org/model-d", "Model D", "0")],
        recipient,
    )
    assert catalog["entries"] == []
    assert catalog["excluded"] == [
        {"name": "Model C", "reason": "OpenRouter 에 같은 이름 없음"},
        {"name": "Model D", "reason": "OpenRouter 가격 없음 또는 0"},
    ]


def test_ECI_가_최소_성능_기준보다_낮으면_이유와_함께_뺀다():
    catalog = build_catalog([epoch("Model E", "139.9")], [listing("org/model-e", "Model E")], recipient)
    assert catalog["entries"] == []
    assert catalog["excluded"] == [{"name": "Model E", "reason": "최소 성능 기준(ECI 140) 미만: 139.9"}]
