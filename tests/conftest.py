"""
테스트 공통 준비.

- 테스트는 값이 고정된 픽스처(tests/fixtures)만 본다. data/ 의 실제 스냅샷이 갱신돼도 테스트는 흔들리지 않는다.
- 결제는 테스트 전용 로컬 체인(8546)에 진짜로 보낸다. pytest 가 시작할 때 scripts/local_chain.py 로 띄우고 끝나면 끈다.
- 테스트마다 체인을 처음 상태(배포 직후, 구매자 1000 AEGIS, 한도·요청 번호 기록 없음)로 되돌린다.
- MongoDB 는 테스트 파일마다 새 임시 DB 를 쓰고 끝나면 지운다. 한 파일 안의 테스트끼리는 이어진다.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# agent_m2m 을 불러오기 전에 정해야 .env.local 보다 앞선다.
os.environ["AGENT_M2M_DATA_DIR"] = str(ROOT / "tests" / "fixtures")
os.environ["AEGIS_LOCAL_RPC_URL"] = "http://127.0.0.1:8546"
os.environ["AEGIS_PAYMENT_MODE"] = "local"
os.environ["AEGIS_REAL_PAYMENT_APPROVED"] = "no"
os.environ.pop("AA_API_KEY", None)

from agent_m2m import store  # noqa: E402
from tests.helpers import chain_rpc  # noqa: E402

READY = "로컬 체인 준비 완료"
CHAIN_TIMEOUT_SECONDS = 120


@pytest.fixture(scope="session", autouse=True)
def local_chain():
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "local_chain.py")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output: list[str] = []
    ready = threading.Event()

    def collect() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.append(line)
            if READY in line:
                ready.set()

    threading.Thread(target=collect, daemon=True).start()
    deadline = time.time() + CHAIN_TIMEOUT_SECONDS
    while not ready.is_set():
        if process.poll() is not None:
            raise RuntimeError(
                f"테스트용 로컬 체인이 꺼졌습니다(종료 코드 {process.returncode}). "
                f"Foundry(forge, anvil)가 설치돼 있는지 확인하세요.\n{''.join(output)}"
            )
        if time.time() > deadline:
            process.terminate()
            raise RuntimeError(f"테스트용 로컬 체인이 {CHAIN_TIMEOUT_SECONDS}초 안에 준비되지 않았습니다.\n{''.join(output)}")
        time.sleep(0.1)
    yield
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(autouse=True)
def chain_snapshot():
    """체인 규칙(하루 한도, 60초 결제 횟수 등)은 결제 기록을 체인에 쌓으므로, 되돌리지 않으면 앞 테스트가 뒤 테스트를 막는다."""
    snapshot_id = chain_rpc("evm_snapshot")
    yield
    if not chain_rpc("evm_revert", [snapshot_id]):
        raise RuntimeError("테스트용 로컬 체인을 처음 상태로 되돌리지 못했습니다")


@pytest.fixture(scope="module", autouse=True)
def test_database(request):
    """테스트 파일마다 실행 중인 로컬 MongoDB 에 테스트 전용 DB 를 만들고, 끝나면 통째로 지운다."""
    store.close_store()
    os.environ["MONGODB_DB"] = f"agent_m2m_test_{int(time.time() * 1000)}_{request.module.__name__.split('.')[-1]}"
    yield
    if store.is_connected():
        store.drop_test_database()
    store.close_store()
