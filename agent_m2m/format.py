"""
금액 표기. 화면에는 사람이 읽는 AEGIS로만 보여준다.

체인은 소수점을 다루지 못해서 내부 계산은 최소 단위(units) 정수로만 한다.
AEGIS 소수점이 6자리이므로 1 AEGIS = 1,000,000 units 다. 원-전, 달러-센트와 같은 관계다.
"""

import re

UNITS_PER_AEGIS = 1_000_000

_AEGIS_PATTERN = re.compile(r"^(\d+)(?:\.(\d{1,6}))?$")


def to_aegis(units: int) -> str:
    """최소 단위 → AEGIS 문자열. 뒤에 붙는 0은 떼고, 정수면 소수점도 떼어 짧게 보여준다."""
    text = f"{units / UNITS_PER_AEGIS:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def aegis_text(units: int) -> str:
    """표와 문장에서 쓰는 기본 금액 표기."""
    return f"{to_aegis(units)} AEGIS"


def parse_aegis(value: object) -> int | None:
    """
    사람이 적은 AEGIS 금액("0.5", 0.5) → 최소 단위 정수. 소수점 오차가 없도록 문자열 자릿수로 바꾼다.
    0 이상이고 소수점 6자리까지만 받는다. 형식이 틀리면 None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    match = _AEGIS_PATTERN.match(text)
    if match is None:
        return None
    whole, fraction = match.group(1), match.group(2) or ""
    return int(whole) * UNITS_PER_AEGIS + int(fraction.ljust(6, "0"))
