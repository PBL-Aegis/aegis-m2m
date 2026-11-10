"""
예산 초과 구매 알림. 비교 모델이 모두 결렬돼 예산을 넘는 값에 살 때 경고를 남긴다. 결제는 막지 않는다.
"""

from agent_m2m.audit import BEFORE_PAYMENT_CHECKS, AuditContext
from agent_m2m.format import aegis_text


def check_over_budget(ctx: AuditContext) -> None:
    if ctx.decision.get("negotiation", {}).get("overBudget"):
        amount, budget = ctx.decision["winner"]["amountUnits"], ctx.decision["budgetUnits"]
        ctx.alert("over-budget", f"예산을 넘는 구매입니다: {aegis_text(amount)} / 예산 {aegis_text(budget)}")


BEFORE_PAYMENT_CHECKS.append(check_over_budget)
