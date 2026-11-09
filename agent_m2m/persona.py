"""
구매 에이전트의 페르소나. 흥정 방식(첫 제안, 양보 비율)과 어디서 살지를 정한다.

페르소나는 personas/<id>.md 파일 하나다. 맨 위 --- 사이에 숫자 설정을 적고, 본문에 사람이 읽을 목표를 적는다.
  opening_ratio      첫 제안 = 호가 × 이 값
  concede_new_card   판매자가 처음 낸 근거 카드에 값 차이 중 올려 주는 비율
  concede_used_card  판매자가 이미 낸 카드를 다시 냈을 때 비율
  concede_no_card    판매자가 근거 없이 값을 불렀을 때 비율
  premium_limit      가장 싼 합의가보다 이 비율까지 비싼 곳은 성능(ECI)을 보고 고른다. 0 이면 가장 싼 곳만 산다.
판매 에이전트에는 페르소나가 없다. 판매자의 양보 비율은 cards.py 에 있다.

기록에는 파일 내용의 지문(hash)을 남긴다. 나중에 그때 어떤 규칙으로 흥정했는지 확인할 수 있다.
"""

import hashlib
from pathlib import Path
from typing import Any

from agent_m2m.config import ROOT

PERSONA_DIR = ROOT / "personas"
DEFAULT_PERSONA = "thrifty"
RATIO_FIELDS = ("opening_ratio", "concede_new_card", "concede_used_card", "concede_no_card")


class PersonaError(ValueError):
    """페르소나 파일이 없거나 설정이 틀렸다."""


def persona_ids() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in PERSONA_DIR.glob("*.md")))


def _parse(persona_id: str, raw: str) -> dict[str, Any]:
    parts = raw.split("---", 2)
    if len(parts) != 3 or parts[0].strip() != "":
        raise PersonaError(f"{persona_id} 페르소나 파일 맨 위에 --- 로 감싼 설정이 없습니다")
    settings = {}
    for line in parts[1].strip().splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise PersonaError(f"{persona_id} 페르소나 설정 줄을 읽을 수 없습니다: {line}")
        settings[key.strip()] = value.strip()
    body = parts[2].strip()
    goal = next((line.removeprefix("목표:").strip() for line in body.splitlines() if line.startswith("목표:")), "")
    if not settings.get("name") or not goal:
        raise PersonaError(f"{persona_id} 페르소나에 name 설정과 '목표:' 줄이 있어야 합니다")

    numbers = {}
    for field in (*RATIO_FIELDS, "premium_limit"):
        try:
            numbers[field] = float(settings[field])
        except (KeyError, ValueError) as error:
            raise PersonaError(f"{persona_id} 페르소나의 {field} 는 숫자여야 합니다") from error
    if not all(0 < numbers[field] <= 1 for field in RATIO_FIELDS):
        raise PersonaError(f"{persona_id} 페르소나의 비율은 0 초과 1 이하여야 합니다")
    if numbers["premium_limit"] < 0:
        raise PersonaError(f"{persona_id} 페르소나의 premium_limit 는 0 이상이어야 합니다")

    return {
        "id": persona_id,
        "name": settings["name"],
        "goal": goal,
        "openingRatio": numbers["opening_ratio"],
        "concede": {"new": numbers["concede_new_card"], "used": numbers["concede_used_card"], "none": numbers["concede_no_card"]},
        "premiumLimit": numbers["premium_limit"],
        "hash": f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}",
    }


def load_persona(persona_id: str = DEFAULT_PERSONA) -> dict[str, Any]:
    """페르소나 하나. 없거나 설정이 틀리면 PersonaError."""
    path: Path = PERSONA_DIR / f"{persona_id}.md"
    if persona_id not in persona_ids():
        raise PersonaError(f"없는 페르소나입니다: {persona_id}")
    return _parse(persona_id, path.read_text(encoding="utf-8"))


def reason(persona: dict[str, Any], rule: str, text: str, **inputs: Any) -> dict[str, Any]:
    """근거 카드. 구매 에이전트가 이 값을 부르거나 받거나 거절한 이유를 페르소나 기준으로 적는다."""
    return {"persona": persona["id"], "rule": rule, "text": f"{persona['name']}: {text}", "inputs": inputs}
