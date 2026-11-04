"""
시나리오 3 · 요청 바꿔치기. 구매자의 한 건 예산(설정값)보다 비싼 결제를 송금 직전에 막는다.

해킹된 요청 프로그램이 "싸게"를 "똑똑하게"로 바꿔 보내면 형식은 정상이라 서버가 구분할 수 없다.
그래서 우선순위가 아니라 "이 구매자가 한 건에 얼마까지 쓰는가"로 막는다.
비교 기준은 설정값 AEGIS_BUYER_BUDGET_PER_PAYMENT 다. 요청의 budget 은 해커가 함께 바꿀 수 있어서 쓰지 않는다.
설정값이 없거나 비어 있으면 이 규칙은 적용하지 않는다(알림도 없음).
시나리오 1 의 1건 상한(AUDIT_LIMIT_PER_PAYMENT)은 서비스의 안전장치, 이 값은 구매자 본인의 씀씀이라 더 작게 둔다.
"""

import os

from agent_m2m.audit import BEFORE_PAYMENT_CHECKS, AuditBlockedError, AuditContext
from agent_m2m.format import aegis_text, parse_aegis

RULE = "buyer-budget"


def _budget_units_from_env() -> int | None:
    text = os.environ.get("AEGIS_BUYER_BUDGET_PER_PAYMENT", "").strip()
    if text == "":
        return None
    units = parse_aegis(text)
    if units is None:
        raise ValueError("AEGIS_BUYER_BUDGET_PER_PAYMENT 는 AEGIS 금액이어야 합니다 (예: 0.1). 규칙을 끄려면 비워 두세요")
    return units


# None 이면 규칙을 끈다. 테스트는 monkeypatch.setattr(budget, "BUDGET_PER_PAYMENT_UNITS", ...) 로 바꾼다.
BUDGET_PER_PAYMENT_UNITS = _budget_units_from_env()


def check_buyer_budget(ctx: AuditContext) -> None:
    budget = BUDGET_PER_PAYMENT_UNITS
    if budget is None:
        return
    winner = ctx.decision["winner"]
    amount = winner["amountUnits"]
    if amount > budget:
        raise AuditBlockedError(
            RULE,
            f"구매자 한 건 예산 초과: 결제 {aegis_text(amount)} > 예산 {aegis_text(budget)} "
            f"({winner['displayName']}, 우선순위 {ctx.request.get('priority')})",
        )


BEFORE_PAYMENT_CHECKS.append(check_buyer_budget)
