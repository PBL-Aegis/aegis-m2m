"""
거래 결과 평가. 흥정이 끝난 뒤 이 구매가 페르소나 목표에 비춰 이득이었는지 손해였는지 사람이 읽을 문장으로 남긴다.

LLM 없이 기록에 있는 숫자(호가·합의가·다른 곳의 값·ECI·예산)만으로 코드가 정한다. 같은 기록이면 평가도 같다.
다른 곳보다 비싸게 샀으면 그 이유를 반드시 한 줄 적는다. 이유를 댈 수 없으면 손해로 판정한다.

최저가 근거: 같은 요청을 최저가형으로 다시 계산한 결과(shopping.lowest_price_baseline)가 있으면, 그보다 얼마를 더 냈는지와
그 대신 무엇을 얻었는지를 한 줄로 적고 lowestPrice 에 숫자로 남긴다. 사용자가 "AI 가 제값에 샀나"를 바로 알 수 있게 하려는 것이다.

  good     페르소나 목표대로 샀다
  partial  목표 일부를 포기했다(품질형이 더 좋은 모델을 값 한도나 결렬 때문에 못 산 경우)
  bad      예산을 넘겼거나 목표와 맞지 않게 샀다
"""

from typing import Any

from agent_m2m.format import aegis_text

VERDICT_TEXT = {"good": "이득", "partial": "일부 이득", "bad": "손해"}


def final_price(quote: dict[str, Any]) -> int | None:
    """그 판매자와 끝난 값. 합의했으면 합의가, 결렬됐으면 판매자가 마지막에 부른 값이다."""
    if "agreedUnits" in quote:
        return quote["agreedUnits"]
    prices = [turn["priceUnits"] for turn in quote["transcript"] if turn["from"] == "seller"]
    return prices[-1] if prices else None


def _price_label(quote: dict[str, Any]) -> str:
    return "합의가" if "agreedUnits" in quote else "마지막에 부른 값"


def _lowest_price(persona: dict[str, Any], chosen: dict[str, Any], base: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """최저가 근거 문장과 숫자. 차이 비율은 최저가형 값 기준이다(최저가형보다 몇 % 더 냈나)."""
    paid, price = chosen["agreedUnits"], base["priceUnits"]
    gap = paid - price
    numbers = {
        "persona": base["persona"],
        "key": base["key"],
        "displayName": base["displayName"],
        "priceUnits": price,
        "paidUnits": paid,
        "gapUnits": gap,
        "gapRatio": round(gap / price, 4) if price > 0 else 0.0,
    }
    if gap == 0 and base["key"] == chosen["key"]:
        return f"최저가 근거: {base['persona']}으로 같은 흥정을 다시 계산해도 {base['displayName']} {aegis_text(price)}로 같습니다.", numbers
    if gap <= 0:
        same = "이번 구매도 같은 값입니다." if gap == 0 else f"이번 구매는 그보다 {aegis_text(-gap)} 싸게 샀습니다."
        return f"최저가 근거: {base['persona']}이었다면 {base['displayName']}를 {aegis_text(price)}에 샀습니다. {same}", numbers
    eci_gap = chosen["eci"] - base["eci"]
    if base["key"] == chosen["key"]:
        why = "같은 모델을 더 비싸게 샀습니다."
    elif eci_gap > 0:
        why = f"대신 ECI가 {eci_gap:.2f} 높은 {chosen['displayName']}를 샀습니다({persona['name']} 선택)."
    else:
        why = f"{chosen['displayName']}의 성능(ECI)이 더 높지도 않습니다."
    return (
        f"최저가 근거: {base['persona']}이었다면 {base['displayName']}를 {aegis_text(price)}에 샀습니다. "
        f"이번 구매는 {aegis_text(gap)}({gap / price:.1%}) 더 냈습니다. {why}",
        numbers,
    )


def evaluate(
    persona: dict[str, Any],
    chosen: dict[str, Any],
    quotes: list[dict[str, Any]],
    budget_units: int,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """base 는 같은 요청을 최저가형으로 다시 계산한 결과(shopping.lowest_price_baseline). 없으면 최저가 근거를 적지 않는다."""
    paid, ask = chosen["agreedUnits"], chosen["askUnits"]
    lines = [f"{chosen['displayName']}: 호가 {aegis_text(ask)}에서 {aegis_text(paid)}로 {(ask - paid) / ask:.0%} 깎아 샀습니다."]
    others = [(quote, final_price(quote)) for quote in quotes if quote is not chosen and final_price(quote) is not None]
    verdict = "good"

    for other, price in others:
        name, label, eci_gap = other["displayName"], _price_label(other), chosen["eci"] - other["eci"]
        if paid < price:
            lines.append(f"{name}의 {label} {aegis_text(price)}보다 {aegis_text(price - paid)} 싸게 샀습니다.")
        elif paid == price:
            tie = f" 값이 같아 ECI가 {eci_gap:.2f} 높은 이곳을 골랐습니다." if eci_gap > 0 else ""
            lines.append(f"{name}의 {label}도 {aegis_text(price)}로 같습니다.{tie}")
        elif eci_gap > 0 and paid <= price * (1 + persona["premiumLimit"]):
            lines.append(
                f"{name}의 {label} {aegis_text(price)}보다 {aegis_text(paid - price)}({(paid - price) / price:.0%}) 비싸게 샀습니다. "
                f"{persona['name']} 기준으로 ECI가 {eci_gap:.2f} 높고, 더 낼 수 있는 한도 {persona['premiumLimit']:.0%} 안이기 때문입니다."
            )
        else:
            lines.append(
                f"{name}의 {label} {aegis_text(price)}보다 {aegis_text(paid - price)} 비싸게 샀습니다. "
                f"{persona['name']} 목표로는 설명할 수 없는 값입니다."
            )
            verdict = "bad"

        if eci_gap < 0:
            # 성능이 더 좋은 곳을 두고 이곳을 산 이유.
            if persona["premiumLimit"] == 0:
                lines.append(f"{name}의 ECI가 {-eci_gap:.2f} 높지만 {persona['name']}은 값만 봅니다.")
            elif other["status"] == "no-deal":
                lines.append(f"{name}의 ECI가 {-eci_gap:.2f} 높지만 흥정이 결렬돼 살 수 없었습니다.")
                verdict = "partial" if verdict == "good" else verdict
            else:
                lines.append(
                    f"{name}의 ECI가 {-eci_gap:.2f} 높지만 {(price - paid) / paid:.0%} 비싸 "
                    f"{persona['name']}의 한도 {persona['premiumLimit']:.0%}를 넘었습니다."
                )
                verdict = "partial" if verdict == "good" else verdict

    if chosen.get("overBudget"):
        lines.append(f"예산 {aegis_text(budget_units)}보다 {aegis_text(paid - budget_units)} 더 내고 샀습니다. 모든 흥정이 결렬돼 판매자가 마지막에 부른 값이 가장 낮은 곳을 골랐습니다.")
        verdict = "bad"

    result = {
        "persona": persona["id"],
        "personaName": persona["name"],
        "goal": persona["goal"],
        "verdict": verdict,
        "headline": f"{persona['name']} 기준 {VERDICT_TEXT[verdict]}",
        "lines": lines,
    }
    if base is not None:
        line, numbers = _lowest_price(persona, chosen, base)
        lines.insert(1, line)
        result["lowestPrice"] = numbers
    return result
