"""
벤치마크 표와 판매 목록을 읽어오는 곳.

표는 고른 순간의 값으로 고정되어야 한다. 그래서 파일을 읽은 뒤 내용 전체의 지문(해시)을
같이 만들어 두고, 결정 기록에 그 지문을 남긴다. 나중에 같은 계산을 다시 해볼 때
"그때 본 숫자"가 무엇이었는지 확인할 수 있다.

구매 때는 data/benchmark.json 에 고정한 값을 쓴다. 모델을 바꿀 때만 scripts/capture_benchmark.py 로 다시 뜬다.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from agent_m2m.config import ROOT


def _data_dir() -> Path:
    """테스트는 값이 고정된 픽스처 폴더를 가리킨다. 실제 실행은 data/ 를 쓴다."""
    return Path(os.environ.get("AGENT_M2M_DATA_DIR") or ROOT / "data")


def _read_json(file_name: str) -> tuple[Any, str]:
    raw = (_data_dir() / file_name).read_bytes()
    return json.loads(raw), f"sha256:{hashlib.sha256(raw).hexdigest()}"


def load_sellers() -> dict[str, dict[str, Any]]:
    """회사 → 판매 에이전트 설정(이름·주소·floorRatio)."""
    return _read_json("sellers.json")[0]["sellers"]


def load_priority_models() -> dict[str, list[str]]:
    """우선순위 → 비교할 모델 key 목록."""
    return _read_json("sellers.json")[0]["priorityModels"]


def load_snapshot() -> dict[str, Any]:
    """저장된 값 {snapshot, hash}. 구매 때는 이 값을 쓴다."""
    snapshot, digest = _read_json("benchmark.json")
    return {"snapshot": snapshot, "hash": digest}


def load_catalog() -> dict[str, Any]:
    return _read_json("catalog.json")[0]


def pair_entries(catalog: dict[str, Any], snapshot: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """카탈로그의 모델과 벤치마크 줄을 키로 짝지어 준다. 짝이 없으면 구매를 멈춘다."""
    pairs = []
    for entry in catalog["entries"]:
        metrics = next((model for model in snapshot["models"] if model["key"] == entry["key"]), None)
        if metrics is None:
            raise RuntimeError(f"벤치마크 표에 {entry['key']} 의 숫자가 없습니다")
        pairs.append((entry, metrics))
    return pairs
