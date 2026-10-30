"""
세 출처에서 값을 떠서 판매 목록(catalog)과 스냅샷을 만든다.
앱(구매 시 자동 갱신)과 scripts/capture_benchmark.py 가 같이 쓴다.

  Epoch AI       — 성능. Epoch Capabilities Index(ECI)와 95% 신뢰구간. 여러 벤치마크를 난이도까지
                   고려해 통계적으로 합친 지수다. 키 없이 받는다.
  OpenRouter     — 가격. 실제로 파는 1M 토큰당 입력·출력 단가. 키 없이 받는다.
  Artificial Analysis — 속도. 출력 속도(1초에 내보내는 토큰 수)의 최근 72시간 중앙값. AA_API_KEY 가 필요하다.

판매 목록은 사람이 이름을 적지 않고 build_catalog 가 만든다. 짝짓기는 추측하지 않는다.
  - 세 출처의 모델 이름에서 기호를 빼고 소문자로 바꾼 값이 정확히 같을 때만 짝짓는다.
  - AA 는 같은 모델을 생각 단계(effort)별로 따로 잰다. 끝까지 걸린 시간은 단계에 따라 몇 배씩 달라지지만
    출력 속도는 모델을 돌리는 서버의 속도라 단계가 달라도 거의 같다(같은 모델 19쌍에서 중앙값 8% 차이).
    그래서 단계를 고르지 않고, AA 가 잰 단계들의 출력 속도 평균을 쓴다.
  - 값이 비거나 0 인 모델도 뺀다. 빈칸을 기본값으로 채우지 않는다.
  - ECI 가 MIN_ECI 보다 낮은 모델은 팔지 않는다(판매 최소 품질 기준). 운영 판단으로 정한 값이다.
뺀 모델은 이유와 함께 catalog["excluded"] 에 남긴다.

판매 목록은 capture 스크립트를 돌려 사람이 확인하고 커밋할 때만 바뀐다. 자동 갱신은 목록에 있는
모델의 숫자만 새로 받고, 한 출처라도 값이 없으면 스냅샷을 만들지 않고 멈춘다.
"""

import csv
import io
import math
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free"
EPOCH_ECI_URL = "https://epoch.ai/data/eci_scores.csv"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
# 판매 최소 품질 기준. 이보다 ECI 가 낮은 모델은 판매 목록에 넣지 않는다.
MIN_ECI = 140

_DECIMAL = re.compile(r"^\d+(\.\d+)?$")


def http_get(url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    """세 출처를 부르는 곳. 테스트는 이 함수를 바꿔 끼워 가짜 응답을 준다."""
    return httpx.get(url, headers=headers, timeout=20)


def _at(value: Any, dotted: str) -> Any:
    for key in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def js_number_text(value: float | int) -> str:
    """숫자를 JavaScript String(숫자) 와 같은 모양으로. 100.0 은 "100", 105.5 는 "105.5"."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return repr(value) if isinstance(value, float) else str(value)


def normalize_name(name: object) -> str:
    """이름 비교용. 기호와 공백을 빼고 소문자로. "Claude Opus 5.5" 와 "claude-opus-5.5" 가 같아진다."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _positive_decimal(value: object) -> str | None:
    """0 보다 큰 소수점 문자열인지. 숫자는 문자열로 둬서 소수점 오차를 만들지 않는다."""
    if isinstance(value, bool):
        return None
    text = js_number_text(value) if isinstance(value, (int, float)) else value
    if not isinstance(text, str) or _DECIMAL.match(text) is None:
        return None
    return text if re.search(r"[1-9]", text) else None


def per_million(per_token: object) -> str | None:
    """토큰 1개당 단가(문자열)를 1M 토큰당 단가로. 소수점만 여섯 자리 옮긴다."""
    text = _positive_decimal(per_token)
    if text is None:
        return None
    whole, _, fraction = text.partition(".")
    digits = whole + fraction.ljust(6, "0")
    point = len(whole) + 6
    integer = digits[:point].lstrip("0") or "0"
    rest = digits[point:].rstrip("0")
    return integer if rest == "" else f"{integer}.{rest}"


def parse_csv(text: str) -> list[dict[str, str]]:
    """따옴표 안의 쉼표·줄바꿈을 지키는 CSV 읽기. 빈 줄은 건너뛰고, 모자란 칸은 빈 문자열로 둔다."""
    rows = [row for row in csv.reader(io.StringIO(text, newline="")) if any(cell != "" for cell in row)]
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    return [{name: (cells[column] if column < len(cells) else "") for column, name in enumerate(header)} for cells in body]


def fetch_aa(key: str) -> list[dict[str, Any]]:
    response = http_get(AA_URL, headers={"x-api-key": key})
    if response.status_code >= 400:
        raise RuntimeError(f"AA API {response.status_code}: {response.text[:200]}")
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        raise RuntimeError("AA 응답에 모델 목록이 없습니다")
    return data


def fetch_epoch() -> list[dict[str, str]]:
    response = http_get(EPOCH_ECI_URL)
    if response.status_code >= 400:
        raise RuntimeError(f"Epoch ECI {response.status_code}")
    rows = parse_csv(response.text)
    if not rows or "eci" not in rows[0]:
        raise RuntimeError("Epoch 응답에 ECI 표가 없습니다")
    return rows


def fetch_openrouter() -> list[dict[str, Any]]:
    response = http_get(OPENROUTER_URL)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenRouter {response.status_code}")
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        raise RuntimeError("OpenRouter 응답에 모델 목록이 없습니다")
    return data


def _openrouter_name(model: dict[str, Any]) -> str:
    """OpenRouter 이름 "Anthropic: Claude Opus 5" 에서 회사 이름을 뗀다."""
    return str(model.get("name") or model.get("id")).split(": ")[-1]


def _is_base_listing(model: dict[str, Any]) -> bool:
    """":free", ":batch" 처럼 같은 모델의 다른 판매 방식은 빼고 기본 판매만 본다."""
    return isinstance(model.get("id"), str) and ":" not in model["id"]


def _aa_base_name(model: dict[str, Any]) -> str:
    """AA 이름 "Claude Haiku 5.5 (High)" 에서 단계 표시를 뗀다."""
    return re.sub(r"\s*\(.*?\)", "", str(model.get("name") or "")).strip()


def _output_speed(model: dict[str, Any]) -> str | None:
    return _positive_decimal(_at(model, "performance.median_output_tokens_per_second"))


def _average_output_speed(variants: list[dict[str, Any]]) -> str | None:
    """같은 모델의 단계별 출력 속도 평균(소수점 둘째 자리). 값이 있는 단계만 센다."""
    speeds = [float(value) for value in map(_output_speed, variants) if value is not None]
    if not speeds:
        return None
    mean = sum(speeds) / len(speeds)
    return js_number_text(math.floor(mean * 100 + 0.5) / 100)


def _capabilities_of(model: dict[str, Any]) -> list[str]:
    parameters = model.get("supported_parameters") if isinstance(model.get("supported_parameters"), list) else []
    inputs = _at(model, "architecture.input_modalities")
    inputs = inputs if isinstance(inputs, list) else []
    result = []
    if "reasoning" in parameters:
        result.append("reasoning")
    if "tools" in parameters:
        result.append("tools")
    if "image" in inputs:
        result.append("vision")
    return result


def _group_by(items: list[dict[str, Any]], key_of: Callable[[dict[str, Any]], str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(key_of(item), []).append(item)
    return groups


def _eci_number(row: dict[str, str]) -> float:
    try:
        return float(row.get("eci", ""))
    except ValueError:
        return 0.0


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_catalog(
    epoch_rows: list[dict[str, str]],
    openrouter_models: list[dict[str, Any]],
    aa_models: list[dict[str, Any]],
    recipient_of: Callable[[str], str],
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    세 출처를 짝지어 판매 목록을 만든다. recipient_of(provider_id) 는 회사별 판매자 주소를 돌려준다.
    ECI 가 높은 순서로 적는다.
    """
    now = now or datetime.now(timezone.utc)
    openrouter = _group_by([model for model in openrouter_models if _is_base_listing(model)], lambda model: normalize_name(_openrouter_name(model)))
    aa = _group_by(aa_models, lambda model: normalize_name(_aa_base_name(model)))
    entries: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []

    for row in sorted(epoch_rows, key=_eci_number, reverse=True):
        name = row.get("Model", "")
        key = normalize_name(name)

        def skip(reason: str) -> None:
            excluded.append({"name": name, "reason": reason})

        if _positive_decimal(row.get("eci")) is None:
            skip("Epoch ECI 값 없음")
            continue
        if float(row["eci"]) < MIN_ECI:
            skip(f"최소 성능 기준(ECI {MIN_ECI}) 미만: {row['eci']}")
            continue
        listings = openrouter.get(key, [])
        if not listings:
            skip("OpenRouter 에 같은 이름 없음")
            continue
        if len(listings) > 1:
            skip(f"OpenRouter 에 같은 이름이 여러 개: {', '.join(item['id'] for item in listings)}")
            continue
        listing = listings[0]
        input_price = per_million(_at(listing, "pricing.prompt"))
        output_price = per_million(_at(listing, "pricing.completion"))
        if input_price is None or output_price is None:
            skip("OpenRouter 가격 없음 또는 0")
            continue
        variants = [item for item in aa.get(key, []) if _output_speed(item) is not None]
        if not variants:
            skip("Artificial Analysis 에 같은 이름 없음" if not aa.get(key) else "AA 출력 속도 없음 또는 0")
            continue

        provider_id, provider_model_id = listing["id"].split("/", 1)
        entries.append(
            {
                "key": listing["id"],
                "providerId": provider_id,
                "providerModelId": provider_model_id,
                "displayName": name,
                "epochModel": name,
                "openRouterId": listing["id"],
                "aaSlugs": sorted(str(item.get("slug")) for item in variants),
                "recipient": recipient_of(provider_id),
                "capabilities": _capabilities_of(listing),
            }
        )

    return {
        "catalogVersion": f"agent-m2m-{_iso(now)[:10]}",
        "matching": (
            f"ECI {MIN_ECI} 이상이고, Epoch·OpenRouter·AA 이름(기호 제거, 소문자)이 정확히 같은 모델만. "
            "속도는 AA 가 잰 생각 단계들의 출력 속도 평균"
        ),
        "entries": entries,
        "excluded": excluded,
    }


def build_snapshot(
    catalog: dict[str, Any],
    epoch_rows: list[dict[str, str]],
    openrouter_models: list[dict[str, Any]],
    aa_models: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """판매 목록의 모델마다 세 출처의 값을 짝지어 스냅샷을 만든다. 하나라도 없으면 멈춘다."""
    now = now or datetime.now(timezone.utc)
    models = []
    for entry in catalog["entries"]:
        epoch = next((row for row in epoch_rows if row.get("Model") == entry["epochModel"]), None)
        if epoch is None:
            raise RuntimeError(f"Epoch 에 {entry['epochModel']} 가 없습니다")
        listing = next((model for model in openrouter_models if model.get("id") == entry["openRouterId"]), None)
        if listing is None:
            raise RuntimeError(f"OpenRouter 에 {entry['openRouterId']} 가 없습니다")
        variants = [next((model for model in aa_models if model.get("slug") == slug), None) for slug in entry["aaSlugs"]]
        missing_slug = next((slug for slug, found in zip(entry["aaSlugs"], variants) if found is None), None)
        if missing_slug is not None:
            raise RuntimeError(f"AA 에 슬러그 {missing_slug} 가 없습니다")

        values = {
            "eci": _positive_decimal(epoch.get("eci")),
            "eciCiLow": _positive_decimal(epoch.get("eci_ci_low")),
            "eciCiHigh": _positive_decimal(epoch.get("eci_ci_high")),
            "inputPricePerMillion": per_million(_at(listing, "pricing.prompt")),
            "outputPricePerMillion": per_million(_at(listing, "pricing.completion")),
            "outputTokensPerSecond": _average_output_speed(variants),
        }
        missing = [name for name, value in values.items() if value is None]
        if missing:
            raise RuntimeError(f"{entry['key']}: 값이 없습니다 ({', '.join(missing)})")

        model: dict[str, Any] = {"key": entry["key"], "epochModel": entry["epochModel"]}
        if epoch.get("date") is not None:
            model["epochDate"] = epoch["date"]
        model.update(values)
        model.update(
            {
                "openRouterId": entry["openRouterId"],
                "aaSlugs": entry["aaSlugs"],
                "aaModelNames": [str(variant["name"]) for variant in variants],
            }
        )
        models.append(model)

    iso = _iso(now)
    return {
        "snapshotId": f"epoch-openrouter-aa-{iso[:16]}",
        "capturedAt": iso,
        "source": "epoch.ai + openrouter.ai + artificialanalysis.ai",
        "sources": {"epoch": EPOCH_ECI_URL, "openRouter": OPENROUTER_URL, "aa": AA_URL},
        "note": (
            "성능은 Epoch Capabilities Index(95% 신뢰구간 포함), 가격은 OpenRouter 판매 단가, "
            "속도는 Artificial Analysis 가 잰 출력 속도(토큰/초) 최근 72시간 중앙값을 생각 단계별로 평균낸 값입니다."
        ),
        "models": models,
    }
