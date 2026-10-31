"""
로컬 체인. anvil 을 띄우고 AEGIS 토큰(contracts/)을 배포한 뒤 구매자 지갑에 발급한다.

  uv run python scripts/local_chain.py     # 켜 둔 채로 다른 창에서 서버·화면을 띄운다

주소는 AEGIS_LOCAL_RPC_URL(기본 http://127.0.0.1:8545)을 따른다. 자동 테스트는 8546 으로 따로 띄운다.

띄울 때마다 빈 체인에서 시작한다. 계정은 anvil 의 공개 테스트 계정이라 실제 자산이 없다.
0번 계정이 운영자(배포·발급), 1번 계정이 구매자다. 결제 거래를 대신 보내는 중개자는 운영자 권한이 없는
따로 된 계정(LOCAL_RELAYER_INDEX)이고, 가스비용 ETH 를 운영자가 보내 준다. agent_m2m/payment.py 의 local 모드가 같은 계정과
같은 토큰 주소(운영자의 첫 거래로 배포한 주소)를 쓴다. Ctrl+C 로 끄면 체인도 사라진다.
"""

import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web3 import Web3  # noqa: E402

from agent_m2m.payment import (  # noqa: E402
    ANVIL_MNEMONIC,
    LOCAL_CHAIN_ID,
    LOCAL_RELAYER_INDEX,
    anvil_account,
    local_rpc_url,
    local_token_address,
)

# 구매자 지갑에 처음 넣는 양. 1000 AEGIS (소수점 6자리).
INITIAL_BUYER_UNITS = 1_000_000_000
# 중개자 지갑에 넣는 가스비용 ETH. 로컬 체인의 가짜 ETH 다.
RELAYER_ETH = Web3.to_wei(100, "ether")
READY = "로컬 체인 준비 완료"

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"


def say(message: str) -> None:
    print(message, flush=True)


def wait_for_chain(w3: Web3, port: str) -> None:
    for _ in range(50):
        try:
            w3.eth.chain_id
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise RuntimeError(f"anvil 이 응답하지 않습니다. {port} 포트를 다른 프로그램이 쓰고 있지 않은지 확인하세요.")


def send(w3: Web3, account, transaction: dict) -> dict:
    signed = account.sign_transaction(transaction)
    return w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction), poll_latency=0.1)


def main() -> None:
    rpc_url = local_rpc_url()
    port = str(urlparse(rpc_url).port or 8545)

    if subprocess.run(["forge", "build"], cwd=CONTRACTS).returncode != 0:
        sys.exit("forge build 에 실패했습니다. Foundry 설치와 contracts/ 를 확인하세요.")
    artifact = json.loads((CONTRACTS / "out" / "AegisToken.sol" / "AegisToken.json").read_text())

    anvil = subprocess.Popen(["anvil", "--host", "127.0.0.1", "--port", port, "--mnemonic", ANVIL_MNEMONIC, "--silent"])

    def stop(signum: int, _frame: object) -> None:
        anvil.send_signal(signum)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        wait_for_chain(w3, port)
        owner, buyer, relayer = anvil_account(0), anvil_account(1), anvil_account(LOCAL_RELAYER_INDEX)
        expected = local_token_address()

        factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
        deploy = factory.constructor(owner.address).build_transaction(
            {"from": owner.address, "nonce": 0, "chainId": LOCAL_CHAIN_ID}
        )
        contract_address = send(w3, owner, deploy)["contractAddress"]
        if contract_address.lower() != expected.lower():
            raise RuntimeError(f"토큰 주소가 예상과 다릅니다: {contract_address} (예상 {expected})")

        token = w3.eth.contract(address=contract_address, abi=artifact["abi"])
        mint = token.functions.mint(buyer.address, INITIAL_BUYER_UNITS).build_transaction(
            {"from": owner.address, "nonce": 1, "chainId": LOCAL_CHAIN_ID}
        )
        send(w3, owner, mint)
        fund = {"to": relayer.address, "value": RELAYER_ETH, "from": owner.address, "nonce": 2, "chainId": LOCAL_CHAIN_ID,
                "gas": 21_000, "gasPrice": w3.eth.gas_price}
        send(w3, owner, fund)

        say(f"{READY} · {rpc_url} (chain {LOCAL_CHAIN_ID})")
        say(f"AEGIS 토큰 {contract_address}")
        say(f"구매자 {buyer.address} · 1000 AEGIS 발급")
        say(f"중개자 {relayer.address} · 가스비용 100 ETH")
        say("끄려면 Ctrl+C")
    except Exception as error:  # noqa: BLE001
        say(str(error))
        anvil.terminate()

    sys.exit(anvil.wait())


if __name__ == "__main__":
    main()
