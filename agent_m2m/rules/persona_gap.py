"""
시나리오 ② · 페르소나 차이로 생긴 설명 없는 손해(persona-gap). 구매 에이전트의 페르소나 때문에 같은 요청을
기본 페르소나(최저가형)보다 비싸게 산 경우를 찾아, 그 차이와 이유를 사람이 읽을 문장으로 남긴다.

판매 에이전트는 구매자가 양보를 빨리 하는 페르소나인 걸 알면 값을 끌어올릴 수 있다. 사용자는 "AI 가 알아서 했겠지" 하고 넘어간다.
흥정 값은 코드가 계산해 입력이 같으면 결과도 같으므로(strategy.py), 송금 직전에 같은 입력으로 기본 페르소나 흥정을 다시 돌려
실제 합의가와 비교할 수 있다. 다시 돌릴 때는 대사를 쓰지 않아(write_line 없음) Gemma 가 필요 없고 값은 같다.

  기본 페르소나 요청            검사하지 않는다(다시 돌려도 자기 자신이다).
  차이 < AUDIT_PERSONA_GAP_RATIO   조용히 통과한다.
  차이 >= GAP_RATIO              알림(결제는 진행). 품질형이 성능 때문에 일부러 더 낸 정상 거래도 여기서 사람이 읽을 이유와 함께 남는다.
  차이 >= GAP_RATIO 이고 평가(evaluation)가 bad   설명할 수 없는 손해라 송금 직전에 막는다. AUDIT_PERSONA_BLOCK_BAD=false 면 알림만 한다.
  차이 >= AUDIT_PERSONA_BLOCK_RATIO              페르소나가 어떻게 설명하든 너무 비싸므로 막는다.

차이 비율 = (실제 합의가 - 기본 페르소나로 다시 돌린 값) / 실제 합의가. 다시 돌린 값이 더 비싸면 손해가 아니라 통과한다.
체인은 페르소나를 모르므로 체인 규칙은 두지 않는다. 여러 건을 모아 보는 분포 검사는 하지 않는다(단건 검사만).
"""

import os
from typing import Any

from agent_m2m.audit import BEFORE_PAYMENT_CHECKS, AuditBlockedError, AuditContext
from agent_m2m.cards import buyer_cards, seller_cards
from agent_m2m.evaluation import final_price
from agent_m2m.format import aegis_text
from agent_m2m.negotiation import NegotiationError, negotiate
from agent_m2m.persona import DEFAULT_PERSONA, load_persona
from agent_m2m.seller import find_seller
from agent_m2m.shopping import choose, compared_models

RULE = "persona-gap"


def _ratio(name: str, default: str) -> float:
    text = os.environ.get(name, default)
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{name} 는 0 초과 1 이하의 숫자여야 합니다 (예: {default}): {text}") from None
    if not 0 < value <= 1:
        raise ValueError(f"{name} 는 0 초과 1 이하의 숫자여야 합니다 (예: {default}): {text}")
    return value


def _flag(name: str, default: str) -> bool:
    text = os.environ.get(name, default).strip().lower()
    if text not in ("true", "false"):
        raise ValueError(f"{name} 는 true 나 false 여야 합니다 (예: {default}): {text}")
    return text == "true"


# 숫자는 코드에 박지 않고 설정값으로 둔다. 테스트는 monkeypatch.setattr(persona_gap, "GAP_RATIO", ...) 로 바꾼다.
GAP_RATIO = _ratio("AUDIT_PERSONA_GAP_RATIO", "0.05")
BLOCK_RATIO = _ratio("AUDIT_PERSONA_BLOCK_RATIO", "0.2")
BLOCK_BAD = _flag("AUDIT_PERSONA_BLOCK_BAD", "true")


def _last_seller_price(quote: dict[str, Any]) -> int | None:
    return next((turn["priceUnits"] for turn in reversed(quote["transcript"]) if turn["from"] == "seller"), None)


def baseline(ctx: AuditContext) -> dict[str, Any] | None:
    """같은 입력(후보·우선순위·예산)으로 기본 페르소나가 흥정했다면 어떻게 샀을지. 판매자 값을 하나도 못 받으면 None.
    대사 없이 값만 계산하므로 몇 번을 돌려도 같은 결과다."""
    persona = load_persona(DEFAULT_PERSONA)
    budget = ctx.decision["budgetUnits"]
    compared = compared_models(ctx.decision["candidates"], ctx.request["priority"])
    quotes: list[dict[str, Any]] = []
    for candidate in compared:
        rival = next((other for other in compared if other is not candidate), None)
        quote = {"key": candidate["key"], "displayName": candidate["displayName"], "eci": candidate["eci"]}
        try:
            quote.update(
                negotiate(
                    candidate["amountUnits"],
                    budget,
                    find_seller(candidate["providerId"])["floorRatio"],
                    buyer_cards=buyer_cards(candidate, rival),
                    seller_cards=seller_cards(candidate, rival),
                    persona=persona,
                )
            )
        except NegotiationError as error:
            quote.update(error.negotiation)
        quotes.append(quote)

    agreed = [quote for quote in quotes if quote["status"] == "agreed"]
    if agreed:
        chosen = choose(agreed, persona)
        price = chosen["agreedUnits"]
    else:
        # 모두 결렬이면 shopping.py 와 같이 판매자가 마지막에 부른 값이 가장 낮은 곳(값이 같으면 성능이 높은 곳)을 그 값에 산다.
        priced = [quote for quote in quotes if _last_seller_price(quote) is not None]
        if not priced:
            return None
        chosen = min(priced, key=lambda quote: (_last_seller_price(quote), -quote["eci"]))
        price = _last_seller_price(chosen)
    return {
        "persona": persona["name"],
        "key": chosen["key"],
        "displayName": chosen["displayName"],
        "eci": chosen["eci"],
        "priceUnits": price,
        "askUnits": chosen["askUnits"],
        "transcript": chosen["transcript"],
    }


def _pace_text(who: str, transcript: list[dict[str, Any]], paid: int, ask: int) -> str | None:
    """구매자의 흥정 속도: 호가 대비 첫 제안, 라운드마다 판매자 값과의 차이의 몇 %를 올렸나(양보 비율), 어떻게 합의했나.
    양보 비율과 끝맺음은 구매자가 값을 부를 때마다 남긴 reason(negotiation.py)에서 읽는다. 구매자가 제안한 적이 없으면 None."""
    buyer = [turn for turn in transcript if turn["from"] == "buyer"]
    offers = [turn["priceUnits"] for turn in buyer if turn["action"] == "offer"]
    if not offers:
        return None
    rules = [turn.get("reason", {}).get("rule") for turn in buyer]
    ratios = [turn["reason"]["inputs"]["ratio"] for turn in buyer if turn.get("reason", {}).get("rule") in ("concede", "accept")]
    share = f"호가의 {paid / ask:.0%}"
    # 합의가 어떻게 났는지. 비율로 올리다 판매자 값에 닿았는지, 제안을 다 쓰고 마지막에 판매자 값을 받았는지, 전부 결렬이었는지.
    ending = {
        "accept": f"판매자 값에 닿아 {share}에 합의했습니다.",
        "last-round": f"마지막에는 판매자 값을 그대로 받아 {share}에 합의했습니다.",
        "over-budget": f"모든 흥정이 결렬돼 예산을 넘겨 판매자의 마지막 값 {share}에 샀습니다.",
        "over-max": f"모든 흥정이 결렬돼, 판매자가 마지막에 부른 {share}가 기준입니다.",
    }.get(rules[-1], f"{share}에 합의했습니다.")
    if not ratios:
        raised = ""
    elif len(set(ratios)) == 1:
        raised = f" 판매자 값과의 차이의 {ratios[0]:.0%}씩 {len(ratios)}번 올렸고,"
    else:
        raised = f" 판매자 값과의 차이의 {'·'.join(f'{ratio:.0%}' for ratio in ratios)}를 차례로 올렸고,"
    return f"{who} 페르소나는 호가의 {offers[0] / ask:.0%}에서 시작해{raised} {ending}"


def explain(ctx: AuditContext, base: dict[str, Any], gap: int, ratio: float) -> str:
    """차이와 이유를 한 덩어리 문장으로. 알림에도 차단 이유에도 같은 글이 들어간다."""
    winner, negotiation = ctx.decision["winner"], ctx.decision["negotiation"]
    persona, evaluation = ctx.decision["persona"], ctx.decision["evaluation"]
    paid = winner["amountUnits"]

    parts = [
        f"{persona['name']} 페르소나로 산 값 {aegis_text(paid)}({winner['displayName']})이 "
        f"기본 페르소나({base['persona']})로 같은 흥정을 다시 돌린 값 {aegis_text(base['priceUnits'])}({base['displayName']})보다 "
        f"{aegis_text(gap)}({ratio:.1%}) 비쌉니다."
    ]

    eci_gap = winner["eci"] - base["eci"]
    if eci_gap > 0:
        parts.append(f"산 모델의 성능(ECI)이 {eci_gap:.2f} 높습니다.")
    elif winner["key"] == base["key"]:
        parts.append("같은 모델을 더 비싸게 샀습니다.")

    cheaper = [
        quote
        for quote in ctx.decision["quotes"]
        if quote["key"] != winner["key"] and (price := final_price(quote)) is not None and price < paid
    ]
    for quote in cheaper:
        label = "합의가" if "agreedUnits" in quote else "마지막에 부른 값"
        parts.append(f"비교한 {quote['displayName']}의 {label}는 {aegis_text(final_price(quote))}로 더 쌌습니다.")

    for text in (
        _pace_text(persona["name"], negotiation["transcript"], paid, negotiation["askUnits"]),
        _pace_text(base["persona"], base["transcript"], base["priceUnits"], base["askUnits"]),
    ):
        if text:
            parts.append(text)

    parts.append(f"거래 평가: {evaluation['headline']}.")
    return " ".join(parts)


def check_persona_gap(ctx: AuditContext) -> None:
    if ctx.decision["persona"]["id"] == DEFAULT_PERSONA:
        return
    base = baseline(ctx)
    if base is None:
        return
    paid = ctx.decision["winner"]["amountUnits"]
    gap = paid - base["priceUnits"]
    if gap <= 0:
        return
    ratio = gap / paid
    if ratio < GAP_RATIO:
        return

    message = explain(ctx, base, gap, ratio)
    if ratio >= BLOCK_RATIO:
        raise AuditBlockedError(RULE, f"기본 페르소나보다 {BLOCK_RATIO:.0%} 이상 비싸 멈췄습니다. {message}")
    if BLOCK_BAD and ctx.decision["evaluation"]["verdict"] == "bad":
        raise AuditBlockedError(RULE, f"설명할 수 없는 값이라 멈췄습니다. {message}")
    ctx.alert(RULE, message)


BEFORE_PAYMENT_CHECKS.append(check_persona_gap)
