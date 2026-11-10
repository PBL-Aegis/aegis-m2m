"""
거래 결과 평가. 흥정이 끝난 뒤 이 구매가 페르소나 목표에 비춰 이득이었는지 손해였는지 사람이 읽을 문장으로 남긴다.

LLM 없이 기록에 있는 숫자(호가·합의가·다른 곳의 값·ECI·예산)만으로 코드가 정한다. 같은 기록이면 평가도 같다.
다른 곳보다 비싸게 샀으면 그 이유를 반드시 한 줄 적는다. 이유를 댈 수 없으면 손해로 판정한다.

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


def evaluate(persona: dict[str, Any], chosen: dict[str, Any], quotes: list[dict[str, Any]], budget_units: int) -> dict[str, Any]:
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

    return {
        "persona": persona["id"],
        "personaName": persona["name"],
        "goal": persona["goal"],
        "verdict": verdict,
        "headline": f"{persona['name']} 기준 {VERDICT_TEXT[verdict]}",
        "lines": lines,
    }
