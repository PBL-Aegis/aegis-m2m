"""
벤치마크 표와 판매 목록을 읽어오는 곳.

표는 고른 순간의 값으로 고정되어야 한다. 그래서 파일을 읽은 뒤 내용 전체의 지문(해시)을
같이 만들어 두고, 결정 기록에 그 지문을 남긴다. 나중에 같은 계산을 다시 해볼 때
"그때 본 숫자"가 무엇이었는지 확인할 수 있다.

구매 때는 load_fresh_snapshot 을 쓴다. 가장 최근 값이 1시간보다 오래됐으면 세 출처(Epoch·OpenRouter·AA)에서 새로 받아
MongoDB 에 쌓고, 받다가 실패하면 마지막 값으로 계속하면서 실패 사유를 결정 기록에 남긴다.
data/benchmark.json 은 한 번도 받지 않았을 때 쓰는 시작값이다.
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from agent_m2m import store
from agent_m2m.benchmark_sources import build_snapshot, fetch_aa, fetch_epoch, fetch_openrouter
from agent_m2m.config import ROOT
from agent_m2m.domain import parse_iso_ms

MAX_AGE_MS = 60 * 60 * 1000


def _data_dir() -> Path:
    """테스트는 값이 고정된 픽스처 폴더를 가리킨다. 실제 실행은 data/ 를 쓴다."""
    return Path(os.environ.get("AGENT_M2M_DATA_DIR") or ROOT / "data")


def _read_json(file_name: str) -> tuple[Any, str]:
    raw = (_data_dir() / file_name).read_bytes()
    return json.loads(raw), f"sha256:{hashlib.sha256(raw).hexdigest()}"


def load_snapshot() -> dict[str, Any]:
    """시작값 {snapshot, hash}."""
    snapshot, digest = _read_json("benchmark.json")
    return {"snapshot": snapshot, "hash": digest}


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    """data/benchmark.json 과 같은 모양으로 직렬화한 내용의 지문. 파일에서 읽은 해시와 맞아떨어진다."""
    raw = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


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


# 동시에 여러 구매가 들어와도 외부 호출은 한 번만 한다.
_refreshing = threading.Lock()


def _refresh() -> dict[str, Any]:
    key = (os.environ.get("AA_API_KEY") or "").strip()
    if key == "":
        raise RuntimeError("AA_API_KEY 가 없습니다")
    epoch_rows = fetch_epoch()
    openrouter_models = fetch_openrouter()
    aa_models = fetch_aa(key)
    snapshot = build_snapshot(load_catalog(), epoch_rows, openrouter_models, aa_models)
    digest = snapshot_hash(snapshot)
    store.save_snapshot(digest, snapshot)
    return {"snapshot": snapshot, "hash": digest}


def _is_fresh(current: dict[str, Any], now_ms: float) -> bool:
    return now_ms - parse_iso_ms(current["snapshot"]["capturedAt"]) < MAX_AGE_MS


def load_fresh_snapshot(now_ms: float | None = None) -> dict[str, Any]:
    """
    {snapshot, hash, refreshError}. refreshError 는 새로 받으려다 실패했을 때만 채워지고,
    이때 snapshot 은 마지막으로 받은 값이다.
    """
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    current = store.latest_snapshot() or load_snapshot()
    if _is_fresh(current, now_ms):
        return {**current, "refreshError": None}
    with _refreshing:
        # 기다리는 동안 다른 요청이 새로 받아 두었으면 그 값을 쓴다.
        latest = store.latest_snapshot()
        if latest is not None and _is_fresh(latest, now_ms):
            return {**latest, "refreshError": None}
        try:
            return {**_refresh(), "refreshError": None}
        except Exception as error:  # noqa: BLE001 — 어떤 실패든 마지막 값으로 계속한다.
            return {**current, "refreshError": str(error) or "알 수 없는 오류"}
