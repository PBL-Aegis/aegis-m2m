"""
시나리오 ① · 일부러 결렬시켜 예산 초과 구매 유도(holdout).

구매 에이전트는 비교한 곳과의 흥정이 모두 결렬되면 판매자가 마지막에 부른 값이 가장 낮은 곳에서 그 값 그대로 산다
(shopping.py 의 _buy_over_budget). 판매 에이전트가 이걸 알면 예산보다 높은 값에서 버티기만 해도 예산을 넘는 금액을 받아 간다.
구매자는 흥정 중에는 예산을 넘겨 부르지 않으므로(negotiation.py), 예산을 넘는 결제는 이 경로에서만 생긴다.

세 가지를 본다. 모두 송금 직전(BEFORE_PAYMENT_CHECKS)이다.

  holdout             예산을 TOLERANCE_RATIO 보다 더 넘는 결제를 막는다. 예산과 실제 금액, 버틴 판매자를 이유에 남긴다.
  holdout-stall       예산 초과 구매에서, 결렬된 판매자가 마지막 STALL_ROUNDS 번 같은 값을 불렀으면 알린다.
  holdout-seller-rate 판매자별 최근 SELLER_WINDOW 건(이 판매자에게서 사려 한 건) 중 예산 초과 비율이 SELLER_RATIO 이상이면 알린다.
                      SELLER_MIN_DEALS 건이 쌓이기 전에는 알리지 않는다. 막힌 건도 판매자의 시도라 함께 센다.

집계와 알림은 막기 전에 남긴다. 그래서 막힌 결제에도 "누가 버텼는지"가 함께 남는다.
허용 폭 안의 예산 초과는 막지 않고, rules/over_budget.py 의 over-budget 경고가 그대로 남는다(그 규칙은 이 규칙 뒤에 돈다).

체인의 Deal 에는 예산이 없어 체인은 예산 초과를 알 수 없다. 이 시나리오는 서버에서만 막는다.
"""

import os

from pymongo import ReturnDocument

from agent_m2m import store
from agent_m2m.audit import BEFORE_PAYMENT_CHECKS, AuditBlockedError, AuditContext
from agent_m2m.domain import now_iso
from agent_m2m.format import aegis_text

RULE = "holdout"
STALL_RULE = "holdout-stall"
SELLER_RULE = "holdout-seller-rate"
COLLECTION = "holdout_sellers"


def _float(name: str, default: str) -> float:
    value = float(os.environ.get(name, default))
    if value < 0:
        raise ValueError(f"{name} 는 0 이상이어야 합니다: {value}")
    return value


def _count(name: str, default: str) -> int:
    value = int(os.environ.get(name, default))
    if value < 1:
        raise ValueError(f"{name} 는 1 이상이어야 합니다: {value}")
    return value


# 테스트는 monkeypatch.setattr(holdout, "상수이름", ...) 로 바꾼다.
# 예산을 이 비율까지는 넘어도 막지 않는다. 0 이면 예산 초과는 모두 막는다.
TOLERANCE_RATIO = _float("AUDIT_HOLDOUT_TOLERANCE_RATIO", "0")
# 결렬된 판매자의 마지막 몇 번 제안이 같으면 "값을 안 내림"으로 본다.
STALL_ROUNDS = _count("AUDIT_HOLDOUT_STALL_ROUNDS", "3")
# 판매자별로 최근 몇 건을 보고, 그중 예산 초과 비율이 얼마 이상이면 알릴지.
SELLER_WINDOW = _count("AUDIT_HOLDOUT_SELLER_WINDOW", "10")
SELLER_MIN_DEALS = _count("AUDIT_HOLDOUT_SELLER_MIN_DEALS", "3")
SELLER_RATIO = _float("AUDIT_HOLDOUT_SELLER_RATIO", "0.3")


def _seller_counters(quote: dict) -> list[int]:
    """판매자가 부른 값(counter)만. 합의할 때의 accept 는 구매자 값을 받은 것이라 뺀다."""
    return [turn["priceUnits"] for turn in quote.get("transcript", []) if turn["from"] == "seller" and turn["action"] == "counter"]


def stalled_quotes(quotes: list[dict], rounds: int) -> list[tuple[dict, int, bool]]:
    """결렬된 흥정 중 판매자의 마지막 rounds 번 값이 같았던 곳. (흥정, 버틴 값, 호가에서 한 번도 안 내렸는지)."""
    stalled = []
    for quote in quotes:
        if quote.get("status") != "no-deal" and not quote.get("overBudget"):
            continue
        counters = _seller_counters(quote)
        if len(counters) >= rounds and len(set(counters[-rounds:])) == 1:
            stalled.append((quote, counters[-1], all(price >= quote.get("askUnits", price) for price in counters)))
    return stalled


def _over_text(amount: int, budget: int) -> str:
    gap = amount - budget
    if budget <= 0:
        return f"예산 {aegis_text(budget)}보다 {aegis_text(gap)} 더 냄"
    return f"예산 {aegis_text(budget)}보다 {aegis_text(gap)}({gap / budget:.0%}) 더 냄"


def _alert_stalls(ctx: AuditContext, budget: int) -> list[str]:
    lines = []
    for quote, price, never_moved in stalled_quotes(ctx.decision.get("quotes", []), STALL_ROUNDS):
        how = "호가에서 한 번도 내리지 않았습니다" if never_moved else f"마지막 {STALL_ROUNDS}번 같은 값을 불렀습니다"
        line = f"{quote['sellerName']}({quote['displayName']})가 {aegis_text(price)}에서 버텨 {how}. 예산 {aegis_text(budget)}"
        ctx.alert(STALL_RULE, f"판매자가 값을 내리지 않아 흥정이 결렬됐습니다: {line}")
        lines.append(line)
    return lines


def _record_seller(ctx: AuditContext, over_budget: bool) -> None:
    """이 판매자의 최근 SELLER_WINDOW 건에 이번 건을 더하고, 더한 뒤의 목록으로 비율을 본다. 더하기와 읽기를 한 명령으로 한다."""
    winner = ctx.decision["winner"]
    seller = ctx.decision["negotiation"].get("sellerName") or winner["providerId"]
    doc = store.database()[COLLECTION].find_one_and_update(
        {"_id": winner["providerId"]},
        {
            "$set": {"sellerName": seller},
            "$push": {
                "recent": {
                    "$each": [{"purchaseId": ctx.purchase_id, "overBudget": over_budget, "at": now_iso()}],
                    "$slice": -SELLER_WINDOW,
                }
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    recent = doc["recent"][-SELLER_WINDOW:]
    over = sum(1 for item in recent if item["overBudget"])
    if over_budget and len(recent) >= SELLER_MIN_DEALS and over / len(recent) >= SELLER_RATIO:
        ctx.alert(
            SELLER_RULE,
            f"{seller}에게서 산 최근 {len(recent)}건 중 {over}건({over / len(recent):.0%})이 모두 결렬 뒤 예산 초과 구매입니다. "
            f"기준 {SELLER_RATIO:.0%}. 판매자가 일부러 값을 버티는지 확인하세요.",
        )


def check_holdout(ctx: AuditContext) -> None:
    winner = ctx.decision["winner"]
    negotiation = ctx.decision.get("negotiation", {})
    amount, budget = winner["amountUnits"], ctx.decision["budgetUnits"]
    over_budget = bool(negotiation.get("overBudget")) or amount > budget

    _record_seller(ctx, over_budget)
    if not over_budget:
        return
    stalls = _alert_stalls(ctx, budget)

    if amount <= budget * (1 + TOLERANCE_RATIO):
        return
    held = f" 버틴 판매자: {'; '.join(stalls)}." if stalls else ""
    raise AuditBlockedError(
        RULE,
        f"비교한 곳과의 흥정이 모두 결렬된 뒤 {negotiation.get('sellerName', winner['providerId'])}의 {winner['displayName']}를 "
        f"{aegis_text(amount)}에 사려 해서 막았습니다({_over_text(amount, budget)}, 허용 폭 {TOLERANCE_RATIO:.0%}).{held} "
        "판매자가 예산보다 높은 값에서 버티면 결렬 뒤 그 값에 사게 되는 경로입니다. 이 값에 사려면 예산을 올려 다시 보내 주세요.",
    )


BEFORE_PAYMENT_CHECKS.append(check_holdout)
