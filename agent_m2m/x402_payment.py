"""
x402 결제. 공식 Python SDK(x402 패키지, exact + ERC-3009)로 판매 창구와 구매 에이전트 사이의 HTTP 402 왕복을 한다.

  1. 구매 에이전트가 결제 없이 판매 창구에 결과를 요청 → 판매 창구가 402 와 PAYMENT-REQUIRED 헤더(얼마를·누구에게)를 준다.
  2. 구매 에이전트가 조건이 합의와 같은지 확인하고 ERC-3009 서명을 PAYMENT-SIGNATURE 헤더에 담아 다시 요청한다.
     서명의 nonce 는 SDK 의 무작위 값 대신 합의 해시(deal.hash_deal)다. 그래서 서명이 합의 내용 전체에 대한 동의가 되고,
     토큰은 이 nonce 로 운영자가 열어 둔 합의(감사 통과)를 찾는다. 32바이트 값이라 x402 표준 형식은 그대로다.
  3. 판매 창구가 정산 서버(facilitator)로 확인·정산한 뒤 결과와 PAYMENT-RESPONSE 헤더(거래 해시)를 준다.

정산 서버는 같은 프로세스 안의 SDK facilitator 이고, 운영자 권한이 없는 정산 지갑(payment.LOCAL_FACILITATOR_INDEX)이
정산 거래와 가스비를 맡는다. 구매자 지갑은 서명만 한다.
"""

import functools
import time
from typing import Any

from eth_account.signers.local import LocalAccount
from web3 import Web3
from x402 import x402ClientSync, x402FacilitatorSync, x402ResourceServerSync
from x402.http import PAYMENT_REQUIRED_HEADER, PAYMENT_RESPONSE_HEADER, PAYMENT_SIGNATURE_HEADER
from x402.mechanisms.evm import FacilitatorWeb3Signer
from x402.mechanisms.evm.exact import ExactEvmServerScheme, register_exact_evm_facilitator
from x402.mechanisms.evm.exact.client import ExactEvmScheme
from x402.mechanisms.evm.types import ExactEIP3009Authorization, ExactEIP3009Payload
from x402.schemas import PaymentPayload, PaymentRequired, PaymentRequirements, SettleError, SettleResponse

from agent_m2m.payment import (
    LOCAL_FACILITATOR_INDEX,
    NETWORK,
    TOKEN_DOMAIN_NAME,
    TOKEN_DOMAIN_VERSION,
    anvil_account,
    local_rpc_url,
    local_token_address,
)

PAYMENT_REQUIRED = PAYMENT_REQUIRED_HEADER
PAYMENT_SIGNATURE = PAYMENT_SIGNATURE_HEADER
PAYMENT_RESPONSE = PAYMENT_RESPONSE_HEADER
# 서명이 유효한 시간(초). 판매 창구가 402 에 적어 보내고, 구매 에이전트는 그만큼만 유효한 서명을 만든다.
MAX_TIMEOUT_SECONDS = 600


class PaymentRejected(Exception):
    """정산하지 않았다. 돈은 나가지 않았다."""


def requirements(amount_units: int, pay_to: str) -> PaymentRequirements:
    """판매 창구가 402 에 적는 결제 조건. 합의가를 판매자 주소로, AEGIS 토큰으로, ERC-3009 방식으로."""
    return PaymentRequirements(
        scheme="exact",
        network=NETWORK,
        asset=local_token_address(),
        amount=str(amount_units),
        pay_to=Web3.to_checksum_address(pay_to),
        max_timeout_seconds=MAX_TIMEOUT_SECONDS,
        extra={"assetTransferMethod": "eip3009", "name": TOKEN_DOMAIN_NAME, "version": TOKEN_DOMAIN_VERSION},
    )


def to_wire(model: Any) -> dict[str, Any]:
    """SDK 모델을 헤더·본문에 쓰는 JSON 모양(camelCase)으로 바꾼다."""
    return model.model_dump(by_alias=True, exclude_none=True)


class DealNonceScheme(ExactEvmScheme):
    """SDK 의 exact 구매자 방식에서 nonce 만 합의 해시로 바꾼 것. 나머지(서명 형식, 유효기간)는 SDK 그대로다."""

    def __init__(self, signer: LocalAccount, deal_hash: str) -> None:
        super().__init__(signer)
        self._deal_hash = deal_hash

    def create_payment_payload(self, requirements: PaymentRequirements, extensions: dict[str, Any] | None = None) -> dict[str, Any]:
        authorization = ExactEIP3009Authorization(
            from_address=self._signer.address,
            to=requirements.pay_to,
            value=requirements.amount,
            valid_after="0",
            valid_before=str(int(time.time()) + (requirements.max_timeout_seconds or MAX_TIMEOUT_SECONDS)),
            nonce=self._deal_hash,
        )
        signature = self._sign_authorization(authorization, requirements)
        return ExactEIP3009Payload(authorization=authorization, signature=signature).to_dict()


def check_requirements(accepts: list[PaymentRequirements], deal: dict[str, Any]) -> PaymentRequirements:
    """402 조건 중 합의와 같은 것(토큰·네트워크·받는 주소·금액) 하나를 고른다. 없으면 PaymentRejected. 서명하지 않는다."""
    for required in accepts:
        if (
            required.scheme == "exact"
            and required.network == NETWORK
            and required.asset.lower() == local_token_address().lower()
            and required.pay_to.lower() == deal["seller"].lower()
            and required.amount == str(deal["agreedUnits"])
        ):
            return required
    amounts = ", ".join(required.amount for required in accepts)
    raise PaymentRejected(f"402 조건이 합의와 다릅니다(합의 {deal['agreedUnits']} units, 요구 {amounts}). 서명하지 않았습니다.")


def build_payment(buyer: LocalAccount, accepted: PaymentRequirements, deal_hash: str) -> PaymentPayload:
    """402 의 조건 그대로, nonce 를 합의 해시로 해서 서명한다. SDK 지출 제한에 이 토큰과 합의가를 적어 그 이상은 서명하지 않는다."""
    client = x402ClientSync().register(NETWORK, DealNonceScheme(buyer, deal_hash))
    client.set_spend_controls(
        {"allowed_assets": [{"network": NETWORK, "asset": local_token_address(), "max_amount_per_payment": accepted.amount}]}
    )
    return client.create_payment_payload(PaymentRequired(accepts=[accepted]))


@functools.cache
def _resource_server(rpc_url: str) -> x402ResourceServerSync:
    key = Web3.to_hex(anvil_account(LOCAL_FACILITATOR_INDEX).key)
    facilitator = register_exact_evm_facilitator(
        x402FacilitatorSync(), FacilitatorWeb3Signer(private_key=key, rpc_url=rpc_url), networks=NETWORK
    )
    server = x402ResourceServerSync(facilitator)
    server.register(NETWORK, ExactEvmServerScheme())
    server.initialize()
    return server


def resource_server() -> x402ResourceServerSync:
    """판매 창구가 쓰는 x402 서버. 정산은 같은 프로세스의 SDK facilitator 가 정산 지갑으로 한다."""
    return _resource_server(local_rpc_url())


def verify(payment: PaymentPayload, required: PaymentRequirements) -> None:
    """서명과 조건을 확인하고 체인에서 미리 돌려 본다. 열린 합의가 없으면 여기서 걸린다."""
    result = resource_server().verify_payment(payment, required)
    if not result.is_valid:
        raise PaymentRejected(f"{result.invalid_reason}: {result.invalid_message or ''}".rstrip(": "))


def settle(payment: PaymentPayload, required: PaymentRequirements) -> SettleResponse:
    """verify 를 통과한 결제를 체인에 올린다. 체인이나 정산 서버가 거절하면 PaymentRejected."""
    try:
        result = resource_server().settle_payment(payment, required)
    except SettleError as error:
        raise PaymentRejected(str(error)) from error
    if not result.success:
        raise PaymentRejected(f"{result.error_reason}: {result.error_message or ''}".rstrip(": "))
    return result
