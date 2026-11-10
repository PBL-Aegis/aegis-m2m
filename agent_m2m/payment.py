"""
결제. AEGIS 토큰(ERC-20)의 ERC-3009 서명으로 선택된 모델의 수신자 주소에 보낸다.
흥정한 구매는 settle_deal 로 AegisToken.settleDeal 을 부른다. 합의(deal.py)를 체인에 저장하고 그 합의가만큼 보낸다.
이때 서명의 nonce 는 요청 번호가 아니라 합의 해시라서, 구매자 서명이 합의 내용 전체에 대한 동의가 된다.
pay 는 합의 없이 transferWithAuthorization 으로 바로 보내는 경로다.
구매자 지갑은 "이 수신자에게 이 금액을, 이 요청 번호로, 10분 안에만"이라는 내용에 서명만 한다.
거래는 중개자 지갑이 보내고 가스비도 중개자가 낸다. 그래서 구매자 지갑에는 AEGIS 만 있으면 된다.
중개자 키는 결제 서버에 있어야 하므로 운영자(토큰 발급·규칙 설정 권한)와 다른, 권한 없는 지갑을 쓴다.
같은 지갑이면 서버가 뚫렸을 때 토큰 발급과 체인 한도 변경 권한까지 함께 넘어간다.
토큰은 서명을 확인하고 체인의 감사 규칙(contracts/)을 돌린 뒤 구매자 지갑에서 송금한다.

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

from agent_m2m.deal import deal_tuple, hash_deal
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
        "name": "settleDeal",
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
            {"name": "validBefore", "type": "uint256"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "outputs": [],
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
# local 중개자. 운영자 권한이 없는 지갑이다. 판매자 번호(2번부터 차례로 붙음)와 겹치지 않게 멀리 둔다.
# anvil 이 처음부터 ETH 를 주는 계정이 아니라서 scripts/local_chain.py 가 운영자 ETH 를 보내 준다.
LOCAL_RELAYER_INDEX = 100
# 구매자 서명이 유효한 시간. 체인 시각 기준이라 테스트가 체인 시각을 앞당겨도 어긋나지 않는다.
AUTHORIZATION_SECONDS = 600
# 토큰의 EIP712("AEGIS", "1") 과 같아야 서명이 맞는다.
TOKEN_DOMAIN_NAME = "AEGIS"
TOKEN_DOMAIN_VERSION = "1"
TRANSFER_WITH_AUTHORIZATION_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}

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
    """anvil 공개 테스트 계정. 0번은 운영자(토큰 배포·발급), 1번은 구매자, 2번부터 판매자, LOCAL_RELAYER_INDEX 번은 중개자다."""
    return Account.from_mnemonic(ANVIL_MNEMONIC, account_path=f"m/44'/60'/0'/0/{index}")


def local_accounts() -> dict[str, LocalAccount]:
    return {"owner": anvil_account(0), "buyer": anvil_account(1), "relayer": anvil_account(LOCAL_RELAYER_INDEX)}


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


# 중개자 지갑 하나로 거의 동시에 보내면 거래 순번(nonce)이 겹쳐 뒤의 거래가 거절된다.
# 이 프로세스 안에서는 보내기를 한 줄로 세워, 앞 거래가 체인에 들어간 뒤 다음 거래가 순번을 받게 한다.
_sending = threading.Lock()


def sign_authorization(
    buyer: LocalAccount, token_address: str, chain_id: int, to: str, amount_units: int, request_hash: str, valid_before: int
) -> Any:
    """구매자가 ERC-3009 결제 내용에 서명한다. request_hash 가 서명의 일회용 번호(nonce)다. 체인에 보내지 않는다.
    pay 는 요청 번호를, settle_deal 은 합의 해시를 넘긴다."""
    return buyer.sign_typed_data(
        domain_data={
            "name": TOKEN_DOMAIN_NAME,
            "version": TOKEN_DOMAIN_VERSION,
            "chainId": chain_id,
            "verifyingContract": token_address,
        },
        message_types=TRANSFER_WITH_AUTHORIZATION_TYPES,
        message_data={
            "from": buyer.address,
            "to": to,
            "value": amount_units,
            "validAfter": 0,
            "validBefore": valid_before,
            "nonce": Web3.to_bytes(hexstr=request_hash),
        },
    )


def pay(amount_units: int, recipient: str, purchase_id: str, request_id: str) -> PaymentResult:
    config = payment_config()
    to = Web3.to_checksum_address(recipient)
    request_hash = request_id_hash(request_id)

    token_address = Web3.to_checksum_address(config["tokenAddress"])
    buyer, relayer = anvil_account(1), anvil_account(LOCAL_RELAYER_INDEX)
    w3 = web3_for(config)
    token = token_contract(w3, token_address)

    balance = token.functions.balanceOf(buyer.address).call()
    if balance < amount_units:
        raise PaymentError(f"지갑 잔액이 부족합니다: 보유 {balance} / 필요 {amount_units}")

    valid_before = int(w3.eth.get_block("latest")["timestamp"]) + AUTHORIZATION_SECONDS
    signature = sign_authorization(buyer, token_address, config["chainId"], to, amount_units, request_hash, valid_before)

    function = token.functions.transferWithAuthorization(
        buyer.address,
        to,
        amount_units,
        0,
        valid_before,
        request_hash,
        signature.v,
        signature.r.to_bytes(32, "big"),
        signature.s.to_bytes(32, "big"),
    )
    receipt, tx_hash = _send(w3, function, relayer, config["chainId"])
    return {
        "mode": config["mode"],
        "txHash": tx_hash,
        "from": buyer.address,
        "relayer": relayer.address,
        "to": to,
        "amountUnits": amount_units,
        "tokenAddress": token_address,
        "chainId": config["chainId"],
        "requestIdHash": request_hash,
        "blockNumber": str(receipt["blockNumber"]),
    }


def settle_deal(deal: dict[str, Any], purchase_id: str) -> PaymentResult:
    """합의(deal.build_deal)대로 settleDeal 을 부른다. 구매자는 합의 해시를 nonce 로 서명한다. 결과에 dealHash 를 더 담는다."""
    config = payment_config()
    token_address = Web3.to_checksum_address(config["tokenAddress"])
    buyer, relayer = anvil_account(1), anvil_account(LOCAL_RELAYER_INDEX)
    if Web3.to_checksum_address(deal["buyer"]) != buyer.address:
        raise PaymentError("합의의 구매자가 이 구매 에이전트 지갑이 아닙니다")
    w3 = web3_for(config)
    token = token_contract(w3, token_address)
    to, amount_units = Web3.to_checksum_address(deal["seller"]), deal["agreedUnits"]

    balance = token.functions.balanceOf(buyer.address).call()
    if balance < amount_units:
        raise PaymentError(f"지갑 잔액이 부족합니다: 보유 {balance} / 필요 {amount_units}")

    deal_hash = hash_deal(deal)
    valid_before = int(w3.eth.get_block("latest")["timestamp"]) + AUTHORIZATION_SECONDS
    signature = sign_authorization(buyer, token_address, config["chainId"], to, amount_units, deal_hash, valid_before)
    function = token.functions.settleDeal(
        deal_tuple(deal), valid_before, signature.v, signature.r.to_bytes(32, "big"), signature.s.to_bytes(32, "big")
    )
    receipt, tx_hash = _send(w3, function, relayer, config["chainId"])
    return {
        "mode": config["mode"],
        "txHash": tx_hash,
        "from": buyer.address,
        "relayer": relayer.address,
        "to": to,
        "amountUnits": amount_units,
        "tokenAddress": token_address,
        "chainId": config["chainId"],
        "requestIdHash": deal["requestId"],
        "dealHash": deal_hash,
        "blockNumber": str(receipt["blockNumber"]),
    }


def _send(w3: Web3, function: Any, relayer: LocalAccount, chain_id: int) -> tuple[Any, str]:
    """중개자가 거래를 보내고 영수증을 기다린다. (영수증, 거래 해시)."""
    # 여기서 나는 오류(서명·유효기간·체인 규칙의 revert 포함)는 거래를 보내기 전이다. 가스 추정에서 먼저 걸린다.
    with _sending:
        transaction = function.build_transaction(
            {
                "from": relayer.address,
                "nonce": w3.eth.get_transaction_count(relayer.address, "pending"),
                "chainId": chain_id,
            }
        )
        signed = relayer.sign_transaction(transaction)
        tx_hash = Web3.to_hex(w3.eth.send_raw_transaction(signed.raw_transaction))

    # 여기부터는 거래가 체인에 나간 뒤다. 어떤 실패든 송금 후 실패로 알린다.
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, poll_latency=LOCAL_POLL_SECONDS)
    except Exception as error:  # noqa: BLE001
        raise PaymentError(f"전송 결과를 확인하지 못했습니다: {tx_hash} ({error})", sent=True) from error
    if receipt["status"] != 1:
        raise PaymentError(f"전송이 실패했습니다: {tx_hash}", sent=True)
    return receipt, tx_hash
