"""
결제와 체인 기록. AEGIS 토큰(contracts/src/AegisToken.sol)에 보내는 거래를 모은다.

구매 한 건의 결제는 두 단계다.
  1. open_deal: 운영자 지갑이 흥정 합의와 송금 직전 감사 결과(감사 보고서 해시)를 체인에 올린다.
     감사가 막았으면 합의는 열리지 않고 "막음" 기록만 남는다.
  2. x402 결제(x402_payment.py): 구매자가 합의 해시를 nonce 로 ERC-3009 서명을 하고, 판매 창구가 x402 정산 서버로
     그 서명을 체인에 올린다. 토큰은 열린 합의와 같은 결제만 받는다. 정산 거래와 가스비는 정산 서버 지갑이 낸다.
결제가 끝나면 record_after_audit 로 송금 뒤 감사 결과도 운영자 지갑이 체인에 남긴다.

정산 서버 지갑은 토큰 발급·규칙 설정 권한이 없는 따로 된 지갑이다. 운영자 지갑은 합의 열기·감사 기록에도 쓴다.
로컬 데모라서 운영자 키를 서버가 쓴다. 실제 서비스라면 감사 기록용 키를 따로 나눠야 한다.

결제는 이 컴퓨터의 로컬 체인(anvil, scripts/local_chain.py)에만 보낸다. 실제 자산은 오가지 않는다.
자동 테스트(pytest)도 테스트 전용 anvil(AEGIS_LOCAL_RPC_URL)을 띄워 같은 경로로 진짜 결제한다.
계정은 anvil 공개 테스트 계정이라 개인키를 환경변수로 받지 않는다. 화면과 기록에는 주소만 남는다.
"""

import functools
import os
import threading
from typing import Any
from urllib.parse import urlparse

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.utils.address import get_create_address

from agent_m2m.deal import deal_tuple
from agent_m2m.domain import PaymentResult

AEGIS_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "transferWithAuthorization",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "openDeal",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "deal",
                "type": "tuple",
                "components": [
                    {"name": "requestId", "type": "bytes32"},
                    {"name": "buyer", "type": "address"},
                    {"name": "seller", "type": "address"},
                    {"name": "modelKey", "type": "bytes32"},
                    {"name": "askUnits", "type": "uint256"},
                    {"name": "agreedUnits", "type": "uint256"},
                    {"name": "transcriptHash", "type": "bytes32"},
                    {"name": "decisionHash", "type": "bytes32"},
                ],
            },
            {"name": "result", "type": "uint8"},
            {"name": "rules", "type": "string"},
            {"name": "reportHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "recordAudit",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "requestId", "type": "bytes32"},
            {"name": "result", "type": "uint8"},
            {"name": "rules", "type": "string"},
            {"name": "reportHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "audits",
        "stateMutability": "view",
        "inputs": [{"name": "requestId", "type": "bytes32"}, {"name": "stage", "type": "uint8"}],
        "outputs": [{"name": "result", "type": "uint8"}, {"name": "reportHash", "type": "bytes32"}],
    },
    {
        "type": "function",
        "name": "dealStatus",
        "stateMutability": "view",
        "inputs": [{"name": "requestId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "type": "function",
        "name": "authorizationState",
        "stateMutability": "view",
        "inputs": [{"name": "authorizer", "type": "address"}, {"name": "nonce", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "transfer",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "decimals",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        "type": "event",
        "name": "Transfer",
        "anonymous": False,
        "inputs": [
            {"name": "from", "type": "address", "indexed": True},
            {"name": "to", "type": "address", "indexed": True},
            {"name": "value", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "Paid",
        "anonymous": False,
        "inputs": [
            {"name": "requestId", "type": "bytes32", "indexed": True},
            {"name": "from", "type": "address", "indexed": True},
            {"name": "to", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
        ],
    },
]

# anvil 이 띄울 때마다 똑같이 만드는 공개 테스트 계정. 로컬 체인에서만 쓰고, 실제 자산은 없다.
ANVIL_MNEMONIC = "test test test test test test test test test test test junk"
DEFAULT_LOCAL_RPC_URL = "http://127.0.0.1:8545"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
LOCAL_CHAIN_ID = 31337
# 로컬 체인은 거래를 바로 블록에 넣으므로 결과를 짧은 간격으로 확인한다.
LOCAL_POLL_SECONDS = 0.1
# x402 정산 서버(facilitator) 지갑. 운영자 권한이 없는 지갑이다. 판매자 번호(2번부터 차례로 붙음)와 겹치지 않게 멀리 둔다.
# anvil 이 처음부터 ETH 를 주는 계정이 아니라서 scripts/local_chain.py 가 운영자 ETH 를 보내 준다.
LOCAL_FACILITATOR_INDEX = 100
# x402 네트워크 이름(CAIP-2).
NETWORK = f"eip155:{LOCAL_CHAIN_ID}"
# 토큰의 EIP712("AEGIS", "1") 과 같아야 서명이 맞는다. x402 정산 서버가 name()·version() 으로 확인한다.
TOKEN_DOMAIN_NAME = "AEGIS"
TOKEN_DOMAIN_VERSION = "1"
# 체인의 감사 단계·결과 번호. AegisToken 의 STAGE_*·RESULT_* 와 같다.
STAGE_BEFORE_SEND, STAGE_AFTER_SEND = 1, 2
AUDIT_RESULT_CODE = {"pass": 1, "alert": 2, "block": 3}
# 가스 추정치에 더하는 여유(비율). 추정치를 그대로 쓰면 상태가 조금 달라질 때 OutOfGas 로 송금 뒤 실패가 난다.
GAS_MARGIN = 0.25

Account.enable_unaudited_hdwallet_features()


class PaymentError(Exception):
    """sent 가 True 면 거래를 체인에 보낸 뒤 실패한 것이다. 돈이 나갔을 수 있다."""

    def __init__(self, message: str, sent: bool = False) -> None:
        super().__init__(message)
        self.sent = sent


def local_rpc_url() -> str:
    """로컬 체인 주소. 자동 테스트는 개발용 체인과 부딪치지 않게 다른 포트를 쓴다. 이 컴퓨터 주소만 받는다."""
    value = (os.environ.get("AEGIS_LOCAL_RPC_URL") or DEFAULT_LOCAL_RPC_URL).strip()
    if urlparse(value).hostname not in LOOPBACK_HOSTS:
        raise PaymentError(f"AEGIS_LOCAL_RPC_URL 은 이 컴퓨터 주소(127.0.0.1)여야 합니다: {value}")
    return value


@functools.cache
def anvil_account(index: int) -> LocalAccount:
    """anvil 공개 테스트 계정. 0번은 운영자(토큰 배포·발급·합의 열기·감사 기록), 1번은 구매자, 2번부터 판매자,
    LOCAL_FACILITATOR_INDEX 번은 x402 정산 서버다."""
    return Account.from_mnemonic(ANVIL_MNEMONIC, account_path=f"m/44'/60'/0'/0/{index}")


def local_accounts() -> dict[str, LocalAccount]:
    return {"owner": anvil_account(0), "buyer": anvil_account(1), "facilitator": anvil_account(LOCAL_FACILITATOR_INDEX)}


def local_token_address() -> str:
    """새로 띄운 anvil 에서 운영자의 첫 거래로 배포한 토큰 주소. scripts/local_chain.py 가 이 순서로 배포한다."""
    return get_create_address(anvil_account(0).address, 0)


def request_id_hash(request_id: str) -> str:
    """체인에 넘기는 요청 번호. 요청 번호 문자열의 keccak256 이다."""
    return Web3.to_hex(Web3.keccak(text=request_id))


def payment_config() -> dict[str, Any]:
    """화면에 보여줄 수 있는 설정만 모은다. 개인키는 여기에 들어가지 않는다."""
    return {
        "mode": "local",
        "tokenAddress": local_token_address(),
        "chainId": LOCAL_CHAIN_ID,
        "rpcUrl": local_rpc_url(),
        "buyerAddress": anvil_account(1).address,
    }


def web3_for(config: dict[str, Any]) -> Web3:
    return Web3(Web3.HTTPProvider(config["rpcUrl"]))


def token_contract(w3: Web3, address: str):
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=AEGIS_ABI)


def buyer_balance() -> dict[str, Any]:
    """대시보드에 보여줄 구매 에이전트 지갑의 AEGIS 잔액. 조회하지 못하면 units는 None이고 사유를 남긴다."""
    config = payment_config()
    try:
        token = token_contract(web3_for(config), config["tokenAddress"])
        balance = token.functions.balanceOf(Web3.to_checksum_address(config["buyerAddress"])).call()
    except Exception:  # noqa: BLE001
        return {"units": None, "status": "잔액 조회 실패 · RPC 응답 없음"}
    return {"units": int(balance), "status": "로컬 체인 온체인 잔액 조회 완료"}


# 한 지갑으로 거의 동시에 보내면 거래 순번(nonce)이 겹쳐 뒤의 거래가 거절된다.
# 이 프로세스 안에서는 운영자 거래를 한 줄로 세워, 앞 거래가 체인에 들어간 뒤 다음 거래가 순번을 받게 한다.
_sending = threading.Lock()


def _token():
    config = payment_config()
    w3 = web3_for(config)
    return config, w3, token_contract(w3, config["tokenAddress"])


def open_deal(deal: dict[str, Any], audit: dict[str, Any]) -> str:
    """운영자가 합의와 송금 직전 감사 결과를 체인에 올린다. audit 은 {result, rules, hash}. 거래 해시를 돌려준다.
    결과가 block 이면 체인은 합의를 열지 않고 감사 기록만 남긴다."""
    config, w3, token = _token()
    function = token.functions.openDeal(
        deal_tuple(deal), AUDIT_RESULT_CODE[audit["result"]], ",".join(audit["rules"]), Web3.to_bytes(hexstr=audit["hash"])
    )
    _, tx_hash = _send(w3, function, anvil_account(0), config["chainId"])
    return tx_hash


def record_after_audit(request_hash: str, audit: dict[str, Any]) -> str:
    """운영자가 송금 뒤 감사 결과를 체인에 남긴다. 결제된 합의에만 한 번 받는다. 거래 해시를 돌려준다."""
    config, w3, token = _token()
    function = token.functions.recordAudit(
        Web3.to_bytes(hexstr=request_hash), AUDIT_RESULT_CODE[audit["result"]], ",".join(audit["rules"]), Web3.to_bytes(hexstr=audit["hash"])
    )
    _, tx_hash = _send(w3, function, anvil_account(0), config["chainId"])
    return tx_hash


def chain_audit(request_hash: str, stage: int) -> dict[str, Any]:
    """체인에 남은 감사 결과 {result(번호), hash}. 기록이 없으면 result 0."""
    _, _, token = _token()
    result, report_hash = token.functions.audits(Web3.to_bytes(hexstr=request_hash), stage).call()
    return {"result": int(result), "hash": Web3.to_hex(report_hash)}


def _send(w3: Web3, function: Any, sender: LocalAccount, chain_id: int) -> tuple[Any, str]:
    """sender 가 거래를 보내고 영수증을 기다린다. (영수증, 거래 해시)."""
    # 여기서 나는 오류(체인 규칙의 revert 포함)는 거래를 보내기 전이다. 가스 추정에서 먼저 걸린다.
    with _sending:
        transaction = function.build_transaction(
            {
                "from": sender.address,
                "nonce": w3.eth.get_transaction_count(sender.address, "pending"),
                "chainId": chain_id,
            }
        )
        transaction["gas"] = int(transaction["gas"] * (1 + GAS_MARGIN))
        signed = sender.sign_transaction(transaction)
        tx_hash = Web3.to_hex(w3.eth.send_raw_transaction(signed.raw_transaction))

    # 여기부터는 거래가 체인에 나간 뒤다. 어떤 실패든 보낸 뒤 실패로 알린다.
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=LOCAL_POLL_SECONDS)
    except Exception as error:  # noqa: BLE001
        raise PaymentError(f"전송 결과를 확인하지 못했습니다: {tx_hash} ({error})", sent=True) from error
    if receipt["status"] != 1:
        raise PaymentError(f"전송이 실패했습니다: {tx_hash}", sent=True)
    return receipt, tx_hash
