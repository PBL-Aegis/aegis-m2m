"""
흥정에 넘길 후보와 호가를 만드는 계산. 이 파일에는 LLM이 없다. 같은 입력이면 항상 같은 답이 나온다.

  1) 후보마다 이번 요청의 금액(호가)을 계산한다
  2) 필요 기능이 없는 후보를 떨어뜨린다. 떨어진 후보도 이유와 함께 남긴다
어느 모델을 살지는 여기서 정하지 않는다. 우선순위별 비교 모델과 흥정 결과로 정한다(shopping.py).
"""

import math
import re
from typing import Any

from agent_m2m.benchmark import load_catalog, load_snapshot, pair_entries
from agent_m2m.domain import Decision

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


def decide(request: dict[str, Any], source: dict[str, Any] | None = None) -> Decision:
    """request: prompt·budgetUnits·priority, 선택으로 content·maxOutputTokens·requiredCapabilities."""
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
    input_tokens = estimate_input_tokens(f"{request['prompt']}\n\n{request.get('content') or ''}".strip())
    required = [item.strip().lower() for item in request.get("requiredCapabilities") or []]

    # 1) 금액 계산
    priced = []
    for entry, metrics in paired:
        units = amount_units(input_tokens, max_output_tokens, metrics["inputPricePerMillion"], metrics["outputPricePerMillion"])
        if units <= 0:
            raise SelectionError(f"{entry['key']}: 계산된 금액이 0이라 결제할 수 없습니다")
        eci = _number(metrics.get("eci"))
        if not math.isfinite(eci):
            # 비면 기본값으로 메우지 않고 멈춘다. 흥정과 감사가 모두 이 값으로 성능을 비교한다.
            raise SelectionError(f"{entry['key']}: Epoch ECI 가 없어 성능을 비교할 수 없습니다")
        priced.append(
            {
                "entry": entry,
                "amountUnits": units,
                "eci": eci,
                "eciCiLow": _number(metrics.get("eciCiLow")),
                "eciCiHigh": _number(metrics.get("eciCiHigh")),
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

    candidates = [
        {
            "key": candidate["entry"]["key"],
            "displayName": candidate["entry"]["displayName"],
            "providerId": candidate["entry"]["providerId"],
            "providerModelId": candidate["entry"]["providerModelId"],
            "recipient": candidate["entry"]["recipient"],
            "amountUnits": candidate["amountUnits"],
            "eci": candidate["eci"],
            "eciCiLow": candidate["eciCiLow"],
            "eciCiHigh": candidate["eciCiHigh"],
        }
        for candidate in eligible
    ]
    return {
        "snapshotId": snapshot["snapshotId"],
        "snapshotHash": source["hash"],
        "snapshotCapturedAt": snapshot["capturedAt"],
        "catalogVersion": catalog["catalogVersion"],
        "priority": request["priority"],
        "estimatedInputTokens": input_tokens,
        "maxOutputTokens": max_output_tokens,
        "budgetUnits": request["budgetUnits"],
        "candidates": candidates,
        "rejected": rejected,
    }
