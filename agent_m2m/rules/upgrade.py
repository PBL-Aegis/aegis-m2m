"""
시나리오 3 · 의도와 다른 상위 등급 구매. 우선순위를 사용자가 아니라 로컬 Gemma 가 정했는데, 그 판단 때문에
기본보다 높은 등급(비싼 비교 모델)을 사게 되면 송금 직전에 멈추고 사용자 확인을 받는다.

요청에 우선순위가 없으면 Gemma 가 요청 문장을 보고 정한다(priority_llm.py). 이 판단이 상위 등급으로 틀리면
사용자는 모른 채 비싸게 산다. 사용자가 우선순위를 직접 정했으면 그것이 의도이므로 막지 않는다.
누가 정했는지는 decision["prioritySource"](request = 사용자, local-llm = Gemma), 산 등급은 우선순위다.
등급은 비교 모델 표(data/sellers.json 의 priorityModels)를 따라 price < default < intelligence 순으로 비싸다.

AUDIT_UPGRADE_MAX_PRIORITY 는 Gemma 가 사용자 확인 없이 정해도 되는 가장 높은 등급이다(기본 default).
체인은 우선순위를 누가 정했는지 모르므로 체인 규칙은 두지 않는다.
"""

import os

from agent_m2m.audit import BEFORE_PAYMENT_CHECKS, AuditBlockedError, AuditContext
from agent_m2m.format import aegis_text

RULE = "unintended-upgrade"

# 싼 등급부터. 순서는 규칙 자체라 설정값으로 두지 않는다.
TIERS: tuple[str, ...] = ("price", "default", "intelligence")


def _max_priority_from_env() -> str:
    value = os.environ.get("AUDIT_UPGRADE_MAX_PRIORITY", "default").strip()
    if value not in TIERS:
        raise ValueError(f"AUDIT_UPGRADE_MAX_PRIORITY 는 {', '.join(TIERS)} 중 하나여야 합니다: {value}")
    return value


# 테스트는 monkeypatch.setattr(upgrade, "MAX_PRIORITY", ...) 로 바꾼다.
MAX_PRIORITY = _max_priority_from_env()


def check_unintended_upgrade(ctx: AuditContext) -> None:
    if ctx.decision.get("prioritySource") != "local-llm":
        return
    priority = ctx.request["priority"]
    if TIERS.index(priority) <= TIERS.index(MAX_PRIORITY):
        return
    winner = ctx.decision["winner"]
    raise AuditBlockedError(
        RULE,
        f"우선순위를 사용자가 정하지 않았는데 {ctx.decision.get('priorityModel', 'Gemma')} 가 '{priority}' 로 정해, "
        f"'{MAX_PRIORITY}' 보다 높은 등급인 {winner['displayName']}({aegis_text(winner['amountUnits'])})를 사려 해서 멈췄습니다. "
        "이 등급을 원하면 우선순위를 직접 정해 다시 보내 주세요.",
    )


BEFORE_PAYMENT_CHECKS.append(check_unintended_upgrade)
