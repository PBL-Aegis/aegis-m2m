"""테스트에서 로컬 체인(anvil)을 직접 다루는 도구. 주소는 conftest.py 가 정한 AEGIS_LOCAL_RPC_URL 이다."""

import os
from typing import Any

import httpx


def chain_rpc(method: str, params: list[Any] | None = None) -> Any:
    url = os.environ["AEGIS_LOCAL_RPC_URL"]
    body = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).json()
    if "error" in body:
        raise RuntimeError(f"{method} 실패: {body['error']['message']}")
    return body["result"]


def increase_chain_time(seconds: int) -> None:
    """체인 시계를 앞으로 돌린다. "60초 지나면 다시 결제", "하루 지나면 한도 초기화" 같은 테스트에 쓴다."""
    chain_rpc("evm_increaseTime", [seconds])
    chain_rpc("evm_mine")
