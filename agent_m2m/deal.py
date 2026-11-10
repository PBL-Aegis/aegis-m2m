"""
체인에 남길 합의. 흥정이 끝나면 산 곳과의 합의를 이 모양으로 만들어 결정 기록(decision.deal)에 넣고,
결제(payment.settle_deal)는 이 합의대로 AegisToken.settleDeal 을 부른다.

대화 원문과 결정 근거는 MongoDB 에 두고, 체인에는 그 해시만 남긴다.
해시는 정해진 방식(키 정렬, 공백 없는 JSON)으로 만들어서, 나중에 DB 의 기록으로 다시 계산하면 같은 값이 나와야 한다.
DB 를 고쳤다면 체인의 해시와 맞지 않아 드러난다(provider.verify_deal).

합의 해시(dealHash)는 컨트랙트의 hashDeal 과 같은 방식으로 계산한다. 구매자는 이 해시를 ERC-3009 서명의 nonce 로 쓴다.
"""

import json
from typing import Any

from eth_abi import encode
from web3 import Web3

DEAL_TYPEHASH = Web3.keccak(
    text="Deal(bytes32 requestId,address buyer,address seller,bytes32 modelKey,uint256 askUnits,uint256 agreedUnits,bytes32 transcriptHash,bytes32 decisionHash)"
)
# 결정 근거로 해시에 넣는 칸. 후보 점수, 흥정한 곳 전부, 페르소나, 평가다.
DECISION_FIELDS = ("snapshotHash", "priority", "candidates", "quotes", "persona", "evaluation")


def content_hash(value: Any) -> str:
    """기록 한 덩어리의 해시. 키를 정렬하고 공백 없이 쓴 JSON 의 keccak256 이다."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Web3.to_hex(Web3.keccak(text=text))


def transcript_hash(negotiation: dict[str, Any]) -> str:
    return content_hash(negotiation["transcript"])


def decision_hash(decision: dict[str, Any]) -> str:
    return content_hash({field: decision.get(field) for field in DECISION_FIELDS})


def build_deal(request_hash: str, buyer: str, decision: dict[str, Any]) -> dict[str, Any]:
    """산 곳과의 합의. request_hash 는 체인에 넘기는 요청 번호(payment.request_id_hash). 금액은 units, 해시와 주소는 0x 문자열이다."""
    winner = decision["winner"]
    return {
        "requestId": request_hash,
        "buyer": Web3.to_checksum_address(buyer),
        "seller": Web3.to_checksum_address(winner["recipient"]),
        "modelKey": Web3.to_hex(Web3.keccak(text=winner["key"])),
        "askUnits": winner["listAmountUnits"],
        "agreedUnits": winner["amountUnits"],
        "transcriptHash": transcript_hash(decision["negotiation"]),
        "decisionHash": decision_hash(decision),
    }


def deal_tuple(deal: dict[str, Any]) -> tuple[Any, ...]:
    """컨트랙트의 Deal 구조체 순서대로."""
    return (
        Web3.to_bytes(hexstr=deal["requestId"]),
        Web3.to_checksum_address(deal["buyer"]),
        Web3.to_checksum_address(deal["seller"]),
        Web3.to_bytes(hexstr=deal["modelKey"]),
        deal["askUnits"],
        deal["agreedUnits"],
        Web3.to_bytes(hexstr=deal["transcriptHash"]),
        Web3.to_bytes(hexstr=deal["decisionHash"]),
    )


def hash_deal(deal: dict[str, Any]) -> str:
    """AegisToken.hashDeal 과 같은 값."""
    encoded = encode(
        ["bytes32", "bytes32", "address", "address", "bytes32", "uint256", "uint256", "bytes32", "bytes32"],
        [bytes(DEAL_TYPEHASH), *deal_tuple(deal)],
    )
    return Web3.to_hex(Web3.keccak(encoded))
