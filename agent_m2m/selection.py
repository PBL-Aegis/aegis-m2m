"""
모델을 고르는 계산. 이 파일에는 LLM이 없다. 같은 입력이면 항상 같은 답이 나온다.

순서가 중요하다.
  1) 후보마다 이번 요청의 금액을 계산한다
  2) 조건에 안 맞는 후보를 먼저 떨어뜨린다 (하드 필터)
  3) 살아남은 후보끼리만 점수를 낸다
  4) 총점과 고정된 동점 규칙으로 1등을 정한다
필터를 점수보다 먼저 거는 이유는, 못 쓸 후보가 점수의 기준선을 흔들지 않게 하기 위해서다.

세 점수는 각각 한 출처에서 오고, 모두 후보 중 가장 나쁜 값 0점·가장 좋은 값 100점으로 편다.
  가격 점수 = (log 최고 금액 − log 내 금액) ÷ (log 최고 − log 최저) × 100   (OpenRouter 판매 단가)
  속도 점수 = (log 내 출력 속도 − log 최저) ÷ (log 최고 − log 최저) × 100   (AA 출력 속도, 토큰/초)
  성능 점수 = (내 ECI − 최저 ECI) ÷ (최고 − 최저) × 100                    (Epoch ECI)
가격과 속도는 후보끼리 몇 배~수십 배 차이 나서 로그로 편다. 그러면 2배 싼 것은 어느 가격대에서든 같은
만큼 점수가 오르고, 아주 싼 모델 하나가 나머지를 0점 가까이로 누르거나(비율 방식) 아주 비싼 모델 하나에
나머지가 끌려가는(직선 방식) 일이 줄어든다.
ECI 는 여러 벤치마크를 난이도까지 고려해 합친 지수라 0 이 "능력 없음"이 아니고 차이 자체가 의미를
가지므로 그대로 편다. 후보가 하나뿐이거나 값이 모두 같으면 100점이다.
"""

import functools
import math
import re
from typing import Any

from agent_m2m.benchmark import load_catalog, load_snapshot, pair_entries
from agent_m2m.domain import PRIORITY_WEIGHTS, Decision

DEFAULT_MAX_OUTPUT_TOKENS = 8_000

_DECIMAL = re.compile(r"^\d+(\.\d+)?$")


class SelectionError(Exception):
    pass


def _parse_decimal(text: str) -> tuple[int, int]:
    """소수점 문자열을 오차 없이 다루기 위해 정수와 자릿수로 쪼갠다."""
    if _DECIMAL.match(text) is None:
        raise SelectionError(f"숫자 형식이 아닙니다: {text}")
    whole, _, fraction = text.partition(".")
    return int(whole + fraction), len(fraction)


def amount_units(input_tokens: int, max_output_tokens: int, input_price_per_million: str, output_price_per_million: str) -> int:
    """
    이번 요청에 낼 금액(토큰 최소 단위 개수).

      금액 = 올림(입력토큰 × 입력단가 + 최대출력토큰 × 출력단가)

    출력이 실제로 얼마나 나올지는 만들기 전에 알 수 없으므로 **한도**로 계산한다.
    그래서 파는 쪽과 사는 쪽이 실행 전에 같은 금액을 얻을 수 있다.
    """
    input_value, input_scale = _parse_decimal(input_price_per_million)
    output_value, output_scale = _parse_decimal(output_price_per_million)
    scale = max(input_scale, output_scale)
    total = input_tokens * input_value * 10 ** (scale - input_scale) + max_output_tokens * output_value * 10 ** (scale - output_scale)
    divisor = 10**scale
    return (total + divisor - 1) // divisor


def estimate_input_tokens(prompt: str) -> int:
    """글자 수로 입력 토큰을 어림잡는다. 토크나이저는 모델마다 달라 양쪽 값이 어긋나므로 쓰지 않는다."""
    return max(1, math.ceil(len(prompt.encode("utf-8")) / 4))


def eci_score(eci: float, min_eci: float, max_eci: float) -> float:
    """ECI 를 후보 중 최저 0점·최고 100점으로 편다."""
    return 100 if max_eci == min_eci else (eci - min_eci) / (max_eci - min_eci) * 100


def log_lower_is_better_score(value: float, minimum: float, maximum: float) -> float:
    """작을수록 좋은 값(금액)을 로그로 바꿔 후보 중 최대 0점·최소 100점으로 편다."""
    if maximum == minimum:
        return 100
    return (math.log(maximum) - math.log(value)) / (math.log(maximum) - math.log(minimum)) * 100


def log_higher_is_better_score(value: float, minimum: float, maximum: float) -> float:
    """클수록 좋은 값(출력 속도)을 로그로 바꿔 후보 중 최소 0점·최대 100점으로 편다."""
    if maximum == minimum:
        return 100
    return (math.log(value) - math.log(minimum)) / (math.log(maximum) - math.log(minimum)) * 100


def _round(value: float) -> float:
    """소수점 6자리 반올림(.5 는 위로)."""
    return math.floor(value * 1e6 + 0.5) / 1e6


def _number(value: object) -> float:
    """숫자 칸을 읽는다. 비었거나 숫자가 아니면 nan."""
    if isinstance(value, bool) or value is None:
        return math.nan
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan


def _is_positive_int(value: object, allow_zero: bool = False) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and (value >= 0 if allow_zero else value > 0)


def _compare(left: dict[str, Any], right: dict[str, Any]) -> int:
    """총점이 같으면 금액, 출력 속도, Provider 이름, 모델 id 순. 무작위는 없다."""
    if left["totalScore"] != right["totalScore"]:
        return -1 if left["totalScore"] > right["totalScore"] else 1
    if left["amountUnits"] != right["amountUnits"]:
        return -1 if left["amountUnits"] < right["amountUnits"] else 1
    if left["outputTokensPerSecond"] != right["outputTokensPerSecond"]:
        return -1 if left["outputTokensPerSecond"] > right["outputTokensPerSecond"] else 1
    if left["providerId"] != right["providerId"]:
        return -1 if left["providerId"] < right["providerId"] else 1
    return -1 if left["providerModelId"] < right["providerModelId"] else 1


def decide(request: dict[str, Any], source: dict[str, Any] | None = None) -> Decision:
    """request: prompt·budgetUnits·priority, 선택으로 maxOutputTokens·requiredCapabilities."""
    max_output_tokens = request.get("maxOutputTokens")
    if max_output_tokens is None:
        max_output_tokens = DEFAULT_MAX_OUTPUT_TOKENS
    if not _is_positive_int(max_output_tokens):
        raise SelectionError("최대 출력 토큰은 1 이상의 정수여야 합니다")
    if not _is_positive_int(request.get("budgetUnits"), allow_zero=True):
        raise SelectionError("예산은 0 이상의 정수여야 합니다")
    if request["prompt"].strip() == "":
        raise SelectionError("요청 내용이 비어 있습니다")

    catalog = load_catalog()
    source = source or load_snapshot()
    snapshot = source["snapshot"]
    paired = pair_entries(catalog, snapshot)
    input_tokens = estimate_input_tokens(request["prompt"])
    required = [item.strip().lower() for item in request.get("requiredCapabilities") or []]

    # 1) 금액 계산
    priced = []
    for entry, metrics in paired:
        units = amount_units(input_tokens, max_output_tokens, metrics["inputPricePerMillion"], metrics["outputPricePerMillion"])
        if units <= 0:
            raise SelectionError(f"{entry['key']}: 계산된 금액이 0이라 결제할 수 없습니다")
        eci = _number(metrics.get("eci"))
        if not math.isfinite(eci):
            # 한 출처라도 비면 기본값으로 메우지 않고 멈춘다. 빈칸을 채우면 점수가 조작된다.
            raise SelectionError(f"{entry['key']}: Epoch ECI 가 없어 성능 점수를 만들 수 없습니다")
        speed = _number(metrics.get("outputTokensPerSecond"))
        if not math.isfinite(speed) or speed <= 0:
            raise SelectionError(f"{entry['key']}: AA 출력 속도가 없어 속도 점수를 만들 수 없습니다")
        priced.append(
            {
                "entry": entry,
                "amountUnits": units,
                "outputTokensPerSecond": speed,
                "eci": eci,
                "eciCiLow": _number(metrics.get("eciCiLow")),
                "eciCiHigh": _number(metrics.get("eciCiHigh")),
                "aaModelNames": metrics.get("aaModelNames"),
            }
        )

    # 2) 하드 필터 — 떨어진 후보도 이유와 함께 남긴다
    eligible = []
    rejected = []
    for candidate in priced:
        has = [item.lower() for item in candidate["entry"]["capabilities"]]
        missing = [item for item in required if item not in has]
        reasons = [f"필요 기능 없음: {', '.join(missing)}"] if missing else []
        if reasons:
            rejected.append(
                {
                    "key": candidate["entry"]["key"],
                    "displayName": candidate["entry"]["displayName"],
                    "amountUnits": candidate["amountUnits"],
                    "reasons": reasons,
                }
            )
            continue
        eligible.append(candidate)
    if not eligible:
        raise SelectionError("조건을 통과한 후보가 하나도 없습니다")

    # 3) 점수 — 기준값은 살아남은 후보에서만 뽑는다
    min_amount = min(item["amountUnits"] for item in eligible)
    max_amount = max(item["amountUnits"] for item in eligible)
    min_speed = min(item["outputTokensPerSecond"] for item in eligible)
    max_speed = max(item["outputTokensPerSecond"] for item in eligible)
    min_eci = min(item["eci"] for item in eligible)
    max_eci = max(item["eci"] for item in eligible)
    weights = PRIORITY_WEIGHTS[request["priority"]]

    scored = []
    for candidate in eligible:
        entry = candidate["entry"]
        price_score = _round(log_lower_is_better_score(candidate["amountUnits"], min_amount, max_amount))
        time_score = _round(log_higher_is_better_score(candidate["outputTokensPerSecond"], min_speed, max_speed))
        intelligence_score = _round(eci_score(candidate["eci"], min_eci, max_eci))
        total_score = _round(
            (price_score * weights["price"] + time_score * weights["time"] + intelligence_score * weights["intelligence"]) / 100
        )
        scored.append(
            {
                "key": entry["key"],
                "displayName": entry["displayName"],
                "providerId": entry["providerId"],
                "providerModelId": entry["providerModelId"],
                "recipient": entry["recipient"],
                "amountUnits": candidate["amountUnits"],
                "outputTokensPerSecond": candidate["outputTokensPerSecond"],
                "eci": candidate["eci"],
                "eciCiLow": candidate["eciCiLow"],
                "eciCiHigh": candidate["eciCiHigh"],
                "aaModelNames": candidate["aaModelNames"],
                "priceScore": price_score,
                "timeScore": time_score,
                "intelligenceScore": intelligence_score,
                "totalScore": total_score,
                "rank": 0,
            }
        )

    # 4) 순위
    scored.sort(key=functools.cmp_to_key(_compare))
    for index, candidate in enumerate(scored):
        candidate["rank"] = index + 1

    return {
        "snapshotId": snapshot["snapshotId"],
        "snapshotHash": source["hash"],
        "snapshotCapturedAt": snapshot["capturedAt"],
        "catalogVersion": catalog["catalogVersion"],
        "priority": request["priority"],
        "weights": weights,
        "estimatedInputTokens": input_tokens,
        "maxOutputTokens": max_output_tokens,
        "budgetUnits": request["budgetUnits"],
        "references": {
            "minAmountUnits": min_amount,
            "maxAmountUnits": max_amount,
            "minOutputTokensPerSecond": min_speed,
            "maxOutputTokensPerSecond": max_speed,
            "minEci": min_eci,
            "maxEci": max_eci,
        },
        "performanceSources": {
            "performance": "Epoch Capabilities Index (95% 신뢰구간)",
            "price": "OpenRouter 판매 단가",
            "speed": "Artificial Analysis 출력 속도(토큰/초), 최근 72시간 중앙값의 생각 단계별 평균",
            "combine": "가격·속도는 로그로, 성능(ECI)은 그대로 후보 중 가장 나쁜 값 0점·가장 좋은 값 100점으로 폄",
        },
        "candidates": scored,
        "rejected": rejected,
        "winner": scored[0],
    }
