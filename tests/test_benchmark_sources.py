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


def aa(slug: str, name: str, speed: float | None = 100) -> dict:
    return {"slug": slug, "name": name, "performance": {"median_output_tokens_per_second": speed}}


def recipient(provider: str) -> str:
    return f"0x{provider}"


def test_세_출처_이름이_기호_대소문자만_다르면_짝짓고_OpenRouter_기능을_옮긴다():
    catalog = build_catalog(
        [epoch("Claude Opus 5.5")],
        [listing("anthropic/claude-opus-5.5", "Claude Opus 5.5")],
        [aa("claude-opus-5-5", "Claude Opus 5.5")],
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
            "aaSlugs": ["claude-opus-5-5"],
            "recipient": "0xanthropic",
            "capabilities": ["reasoning", "tools", "vision"],
        }
    ]
    assert normalize_name("Claude Opus 5.5") == normalize_name("claude-opus-5.5")


def test_AA_생각_단계가_여러_개면_모두_묶고_출력_속도는_단계별_평균을_쓴다():
    epoch_rows = [epoch("Model A")]
    listings = [listing("org/model-a", "Model A")]
    variants = [aa("a-low", "Model A (Low)", 100), aa("a-max", "Model A (Max)", 110), aa("a-off", "Model A (Non-reasoning)", None)]
    catalog = build_catalog(epoch_rows, listings, variants, recipient)
    assert [[entry["key"], entry["aaSlugs"]] for entry in catalog["entries"]] == [["org/model-a", ["a-low", "a-max"]]]
    snapshot = build_snapshot(catalog, epoch_rows, listings, variants)
    assert snapshot["models"][0]["outputTokensPerSecond"] == "105"
    assert snapshot["models"][0]["aaModelNames"] == ["Model A (Low)", "Model A (Max)"]


def test_AA_에_이름은_있지만_출력_속도가_없으면_뺀다():
    catalog = build_catalog([epoch("Model B")], [listing("org/model-b", "Model B")], [aa("b", "Model B", None)], recipient)
    assert catalog["entries"] == []
    assert catalog["excluded"] == [{"name": "Model B", "reason": "AA 출력 속도 없음 또는 0"}]


def test_이름이_다르거나_가격이_0_이면_추측하지_않고_이유와_함께_뺀다():
    catalog = build_catalog(
        [epoch("Model C"), epoch("Model D")],
        [listing("org/model-c-pro", "Model C Pro"), listing("org/model-d", "Model D", "0")],
        [aa("c", "Model C"), aa("d", "Model D")],
        recipient,
    )
    assert catalog["entries"] == []
    assert catalog["excluded"] == [
        {"name": "Model C", "reason": "OpenRouter 에 같은 이름 없음"},
        {"name": "Model D", "reason": "OpenRouter 가격 없음 또는 0"},
    ]


def test_ECI_가_최소_성능_기준보다_낮으면_이유와_함께_뺀다():
    catalog = build_catalog([epoch("Model E", "139.9")], [listing("org/model-e", "Model E")], [aa("e", "Model E")], recipient)
    assert catalog["entries"] == []
    assert catalog["excluded"] == [{"name": "Model E", "reason": "최소 성능 기준(ECI 140) 미만: 139.9"}]
