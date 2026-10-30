# agent-M2M (Python 서버판)

AI 구매 에이전트가 벤치마크 표로 모델을 고르고 AEGIS 토큰으로 결제하는 데모입니다. 모델 선택은 고정 규칙이 하고, 모델 응답은 Mock 문장입니다.

[agent-M2M](https://github.com/PBL-Aegis/agent-M2M)(TypeScript)과 기능이 같고, **서버를 Python(FastAPI)으로 옮긴 판**입니다. 화면은 같은 Next.js 화면을 그대로 쓰고, 화면은 Python 서버의 API 만 부릅니다. 스마트 컨트랙트(Solidity)도 그대로입니다.

## 흐름

요청 → 감사(요청 직후) → 선택 → 기록(처리 중) → 감사(송금 직전) → 결제 → 확인 → 결과 → 기록(성공·실패) → 감사(결제 후)

1. **요청**: 요청 내용, 예산(AEGIS), 우선순위(싸게·빠르게·똑똑하게), 필요 기능, 요청 번호(`requestId`), 사용자(`userId`). 요청 번호를 비우면 서버가 만듭니다. 우선순위를 비우면 로컬 Qwen이 요청 문장을 읽고 정하고, Qwen이 응답하지 않으면 결제 전에 멈춥니다(503).
2. **선택**: 후보마다 금액 계산 → 필요 기능으로 거르기 → 가격·속도·성능 점수 → 우선순위별 비중으로 합산 → 고정 규칙으로 동점 처리(`agent_m2m/selection.py`).
3. **기록(처리 중)**: 결제 직전에 `PROCESSING` 상태로 MongoDB에 먼저 남깁니다.
4. **감사**: `agent_m2m/rules/` 에 등록한 규칙을 세 자리에서 돌립니다. 막으면 "차단", 알리기만 하면 "경고" 알림이 대시보드의 이상 거래에 뜹니다.
5. **결제**: 선택된 모델의 판매자 주소로 AEGIS `pay(수신자, 금액, 요청 번호)`. 요청 번호는 문자열의 keccak256 으로 넘깁니다. 이때 체인의 감사 규칙(`contracts/src/rules/`)이 한 번 더 검사합니다.
6. **확인**: 판매창구가 체인의 `Paid` 기록에서 요청 번호·수신자·금액을 대조합니다.
7. **결과**: Mock 응답 문장.
8. **기록(성공·실패)**: 상태를 `SETTLED` 또는 `FAILED` 로 바꿉니다. 실패는 송금 전(`before-send`)·송금 후(`after-send`)를 구분합니다.

## 구성

| 위치 | 무엇 | 언어 |
| --- | --- | --- |
| `agent_m2m/` | 서버: 선택·결제·감사·기록·API | Python |
| `agent_m2m/rules/` | 서버 감사 규칙 | Python |
| `tests/` | 서버 자동 테스트 (pytest) | Python |
| `scripts/` | 로컬 체인 띄우기, 판매 목록 만들기 | Python |
| `contracts/` | AEGIS 토큰과 체인 감사 규칙, 컨트랙트 테스트 | Solidity |
| `web/` | 화면(채팅·대시보드). Python 서버 API 만 부름 | TypeScript |
| `data/` | 판매 목록·벤치마크 시작값·판매자 주소 | JSON |

## 처음 시작하기

### 1. 설치할 것

| 도구 | 쓰는 곳 | 꼭 필요한가 |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Python 3.12와 패키지 설치, 서버·테스트 실행 | 필요 |
| MongoDB | 구매 기록 저장. 자동 테스트도 임시 DB를 만들어 씀 | 필요 |
| [Foundry](https://getfoundry.sh) (`forge`, `anvil`) | 컨트랙트 빌드·테스트, 로컬 체인(pytest 도 씀) | 필요 |
| Node.js 22 | 화면 실행 | 화면을 볼 때만 |
| [Ollama](https://ollama.com) + `qwen3.5:4b` | 우선순위를 비운 요청에서 요청 문장을 읽고 우선순위를 정함 | 선택 |

### 2. 받고 준비하기

```bash
git clone git@github.com:PBL-Aegis/agent-M2M-py.git
cd agent-M2M-py
git submodule update --init --recursive   # 컨트랙트 라이브러리(OpenZeppelin, forge-std)
uv sync                                    # Python 3.12 와 패키지 설치 (.venv)
cp .env.example .env.local                 # 값은 .env.local 에만 넣는다
cd web && npm install && cd ..             # 화면을 볼 때만
```

### 3. 실행하기

창 세 개를 띄웁니다.

```bash
uv run python scripts/local_chain.py                         # 창 1: 로컬 체인 + 토큰 배포 + 구매자 1000 AEGIS. 켜 둔다
```

```bash
uv run uvicorn agent_m2m.api:app --port 8000 --reload        # 창 2: 서버 http://127.0.0.1:8000
```

```bash
cd web && npm run dev                                         # 창 3: 화면 http://localhost:3100
```

화면은 `http://127.0.0.1:8000` 의 서버를 부릅니다. 서버 주소가 다르면 `AGENT_M2M_API_URL` 을 화면 쪽 환경변수로 줍니다. 브라우저의 `/api/*` 요청을 서버로 넘기는 설정은 **빌드할 때** 정해지므로, `npm run build` 할 때도 같은 값을 줍니다.

### 4. 확인 명령

```bash
uv run pytest                        # 서버 자동 테스트. 테스트용 로컬 체인을 스스로 켜고 끈다
cd contracts && forge test           # 컨트랙트 테스트
cd web && npm run typecheck && npm run build   # 화면 타입 검사·빌드
```

## 요청 보내기

화면 대신 에이전트처럼 API 로 보낼 수 있습니다. 금액(`budget`)은 AEGIS 로 적습니다(1 AEGIS = 1달러). 코드와 체인 안에서는 units(1 AEGIS = 1,000,000 units)로 바꿔 계산합니다. 블록체인이 소수점을 저장할 수 없어서, 은행이 달러를 센트로 다루듯 정수로 세는 것입니다.

```bash
curl -s -X POST localhost:8000/api/purchase -H 'content-type: application/json' \
  -d '{"prompt":"이 글 요약해 줘","budget":"0.5","priority":"price","requestId":"req-001","userId":"user-a"}'
```

| 필드 | 필수 | 뜻 |
| --- | --- | --- |
| `prompt` | 예 | 요청 문장 |
| `budget` | 예 | 예산(AEGIS). 예: `"0.5"` |
| `priority` | 아니오 | `price`·`speed`·`intelligence`·`default`. 비우면 Qwen 이 정함 |
| `requestId` | 아니오 | 요청 번호. 같은 요청을 다시 보낼 때 같은 값. 비우면 서버가 만듦 |
| `userId` | 아니오 | 사용자 |
| `maxOutputTokens` | 아니오 | 최대 출력 토큰(금액 계산에 씀). 기본 8000 |
| `requiredCapabilities` | 아니오 | 필요 기능 `reasoning`·`tools`·`vision` |

화면이 쓰는 조회 API: `GET /api/purchases`, `/api/purchases/{id}`, `/api/purchases/{id}/alerts`, `/api/alerts`, `/api/alerts/summary`, `/api/wallet`, `/api/mode`. 서버를 켠 뒤 `http://127.0.0.1:8000/docs` 에서 모두 볼 수 있습니다.

## 감사 규칙 추가하기

같은 이상행위를 서버와 체인 두 곳에서 막습니다. 서버는 빨리 거르고 알림을 남기고, 체인은 서버가 뚫려도 마지막에 막습니다. 각자 **새 파일**을 만들고, 함께 쓰는 파일에는 등록 한 줄만 더합니다.

### 서버 규칙 (Python)

1. `agent_m2m/rules/<규칙이름>.py` 를 만들고, 맞는 자리에 함수를 append 합니다.

```python
# agent_m2m/rules/max_amount.py — 예시: 한 건 0.5 AEGIS 를 넘으면 막고, 80% 이상이면 알림만 남긴다
import os

from agent_m2m.audit import BEFORE_PAYMENT_CHECKS, AuditBlockedError, AuditContext
from agent_m2m.format import parse_aegis

# 숫자는 코드에 박지 않고 설정값으로 둔다. 사람이 적는 값은 AEGIS, 비교는 units 로.
MAX_UNITS = parse_aegis(os.environ.get("AUDIT_MAX_AMOUNT", "0.5"))
if MAX_UNITS is None:
    raise ValueError("AUDIT_MAX_AMOUNT 는 AEGIS 금액이어야 합니다 (예: 0.5)")
WARN_RATIO = float(os.environ.get("AUDIT_MAX_AMOUNT_WARN_RATIO", "0.8"))


def check_max_amount(ctx: AuditContext) -> None:
    amount = ctx.decision["winner"]["amountUnits"]
    if amount > MAX_UNITS:
        raise AuditBlockedError("max-amount", f"한 건 상한 초과: {amount} units")
    if amount >= MAX_UNITS * WARN_RATIO:
        ctx.alert("max-amount", f"한 건 상한의 {WARN_RATIO * 100:.0f}% 이상: {amount} units")


BEFORE_PAYMENT_CHECKS.append(check_max_amount)
```

2. `agent_m2m/rules/__init__.py` 에 `from agent_m2m.rules import max_amount  # noqa: F401` 한 줄을 더합니다. 적은 순서대로 돕니다.

| 자리 | 언제 | 쓸 수 있는 값 | 막으면 |
| --- | --- | --- | --- |
| `ON_REQUEST_CHECKS` | 요청 직후, 모델을 고르기 전 | `ctx.request`(요청 번호·사용자·문장) | 기록 없이 409. 이전 기록을 `return` 하면 새로 처리하지 않고 그 기록을 응답 |
| `BEFORE_PAYMENT_CHECKS` | 모델을 고르고 처리 중 기록을 남긴 뒤, 송금 직전 | `ctx.request`, `ctx.decision`(고른 모델·금액·점수) | 송금하지 않고 `FAILED`·`before-send` 로 기록 |
| `AFTER_PAYMENT_CHECKS` | 결과가 기록된 뒤 | 위 값 + 두 번째 인자 `record`(최종 상태) | 막을 수 없음. 오류는 알림으로 남고 결과는 그대로 |

- 기록(`ctx.request`, `ctx.decision`, `record`)은 dict 이고 키는 camelCase 입니다(예: `ctx.request["requestId"]`, `record["failureStage"]`). 화면·DB·API 가 같은 이름을 씁니다.
- 알림(`ctx.alert(규칙 이름, 메시지)`)은 MongoDB `alerts` 컬렉션에 "경고"로 쌓입니다. 규칙이 막으면(`AuditBlockedError`) "차단" 알림이 자동으로 남습니다.
- 규칙이 자기 컬렉션이 필요하면 `agent_m2m.store.database()` 로 같은 DB 를 받아 씁니다.
- 요청은 여러 개가 동시에(스레드) 처리됩니다. 둘 다 "아직 한도 안 넘었네"라고 보고 통과하지 않도록, "확인"과 "기록"을 MongoDB 명령 하나로 같이 합니다. 예: `find_one_and_update`(조건이 맞을 때만 바꾸기), unique index(같은 값 두 번 저장 금지). 파이썬 변수에 잠금(`threading.Lock`)을 거는 방식은 서버가 여러 대면 통하지 않습니다.

### 체인 규칙 (Solidity)

1. `contracts/src/rules/<규칙이름>Rule.sol` 에 `PaymentRules` 를 상속한 abstract contract 를 만듭니다. 먼저 `super._checkPayment(...)` 를 불러 다른 규칙도 돌게 하고, 막을 때 revert 합니다. 체인에서는 구매자 지갑 하나(`from`)를 사용자 한 명으로 봅니다.

```solidity
// contracts/src/rules/MaxAmountRule.sol — 예시
pragma solidity ^0.8.24;

import {PaymentRules} from "./PaymentRules.sol";

abstract contract MaxAmountRule is PaymentRules {
    uint256 public constant MAX_AMOUNT = 500_000; // 0.5 AEGIS
    error OverMaxAmount(uint256 amount);

    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId) internal virtual override {
        super._checkPayment(from, to, amount, requestId);
        if (amount > MAX_AMOUNT) revert OverMaxAmount(amount);
    }
}
```

2. `contracts/src/AegisToken.sol` 에서 상속 목록과 `_checkPayment` 의 override 목록에 이름을 더합니다.

```solidity
contract AegisToken is ERC20, Ownable, PaymentRules, MaxAmountRule {
    // ...
    function _checkPayment(address from, address to, uint256 amount, bytes32 requestId)
        internal virtual override(PaymentRules, MaxAmountRule)
    {
        super._checkPayment(from, to, amount, requestId);
    }
}
```

로컬 체인을 다시 켜면 규칙이 담긴 토큰이 올라가고, 화면에서 막힌 결제는 송금 전 실패로 보입니다.

### 테스트로 증명하기

공격을 재현하는 테스트가 통과하면 "막힌다"가 증명됩니다. 서버는 `tests/`, 체인은 `contracts/test/` 에 둡니다.

- `tests/test_purchase.py` 처럼 `run_purchase` 를 불러 기록의 `status`·`failureStage`·알림을 확인합니다. 결제는 테스트용 로컬 체인(8546)에 진짜로 나가고, 모든 체인 규칙이 들어간 진짜 토큰을 거칩니다.
- **테스트마다 체인이 처음 상태로 돌아갑니다**(배포 직후, 구매자 1000 AEGIS, 한도·요청 번호 기록 없음). `tests/conftest.py` 가 자동으로 합니다.
- 체인 시계를 앞으로 돌려야 하면 `tests/helpers.py` 의 `increase_chain_time(초)` 를 씁니다.
- 서버 쪽 기록(MongoDB)은 테스트 파일마다 새 임시 DB 를 쓰고, 한 파일 안의 테스트끼리는 이어집니다. 테스트마다 다른 `userId`·`requestId` 를 쓰면 섞이지 않습니다.
- 동시 요청은 `concurrent.futures.ThreadPoolExecutor` 로 보냅니다(`tests/test_payment.py` 참고).
- 설정값을 바꿔 가며 시험할 때는 규칙 파일의 상수를 pytest 의 `monkeypatch.setattr(규칙모듈, "상수이름", 값)` 으로 바꿉니다. 규칙 파일을 다시 불러오면(`importlib.reload`) 규칙이 두 번 등록되니 쓰지 않습니다.

## 테스트가 확인하는 것

| 명령 | 확인하는 것 | 가짜로 두는 것 | 확인하지 않는 것 |
| --- | --- | --- | --- |
| `uv run pytest` | 선택 계산, 기록, 감사 흐름, API, 로컬 체인 결제(서버 규칙 + 체인 규칙) | 벤치마크 숫자(고정 픽스처), Ollama 응답, 판매창구 일부 | Base Sepolia 결제 |
| `forge test` | 컨트랙트(발급, `pay`, 규칙이 `pay` 를 막는지) | 없음(메모리 안의 체인) | 서버와 이어진 흐름 |
| 로컬 체인 + 서버 + 화면 | 전체 흐름: 서버 규칙, 로컬 체인 결제·체인 규칙, 판매창구 확인 | 모델 응답(Mock 문장) | Base Sepolia 결제 |

## 환경변수

`.env.example` 을 `.env.local` 로 복사해서 씁니다. 값은 `.env.local` 에만 넣습니다. 서버는 시작할 때 저장소 맨 위의 `.env.local` 을 읽습니다.

| 이름 | 기본값 | 뜻 |
| --- | --- | --- |
| `AEGIS_PAYMENT_MODE` | `local` | `local`: 로컬 체인 · `live`: Base Sepolia 전송을 요청 |
| `AEGIS_LOCAL_RPC_URL` | `http://127.0.0.1:8545` | 로컬 체인 주소. 이 컴퓨터 주소만 받음. 자동 테스트는 `8546` 을 씀 |
| `AEGIS_REAL_PAYMENT_APPROVED` | `no` | `yes`여야 live가 실제로 켜짐 |
| `AEGIS_TOKEN_ADDRESS` | `0xE208…142b` | live 에서 쓰는 Base Sepolia AEGIS 토큰. 지금 값은 `pay` 가 없는 이전 토큰 |
| `AEGIS_CHAIN_ID` | `84532` | Base Sepolia |
| `AEGIS_RPC_URL` | `https://sepolia.base.org` | RPC |
| `AEGIS_BUYER_PRIVATE_KEY` | (비움) | 구매자 지갑 개인키. live에서만 필요 |
| `AA_API_KEY` | (비움) | Artificial Analysis API 키. 속도 값의 자동 갱신·판매 목록 생성에 필요. 없으면 저장된 숫자로 계속 돔 |
| `MONGODB_URI` | `mongodb://127.0.0.1:27017` | MongoDB 접속 주소 |
| `MONGODB_DB` | `agent_m2m` | 기록을 담을 데이터베이스 이름 |
| `AEGIS_OLLAMA_URL` | `http://127.0.0.1:11434` | 우선순위 추론용 Ollama. 루프백 주소만 받음 |
| `AEGIS_OLLAMA_MODEL` | `qwen3.5:4b` | 우선순위 추론 모델 |
| `AEGIS_OLLAMA_TIMEOUT_SECONDS` | `30` | 추론 대기 시간(초, 최대 60) |
| `AGENT_M2M_API_URL` | `http://127.0.0.1:8000` | 화면이 부르는 서버 주소(화면 쪽에서만 읽음) |

## 결제 모드

| 모드 | 어디로 | 필요한 것 |
| --- | --- | --- |
| `local` (기본) | 이 컴퓨터의 anvil | `scripts/local_chain.py` 를 켜 둠 |
| `live` | Base Sepolia | 아래 두 변수, 개인키, `pay` 가 있는 토큰 주소 |

`local` 은 감사 규칙이 담긴 컨트랙트를 그대로 올려 쓰므로, 체인에서 막히는 것까지 화면에서 확인할 수 있습니다. 로컬 체인을 끄면 체인과 그 위의 잔액도 사라지고, 다시 켜면 빈 체인에 같은 주소로 새로 배포합니다. 계정은 anvil 의 공개 테스트 계정(0번 운영자, 1번 구매자)이라 실제 자산이 없습니다.

> **경고** — 실제 토큰 전송은 기본적으로 일어나지 않습니다(local). `AEGIS_PAYMENT_MODE=live` **와** `AEGIS_REAL_PAYMENT_APPROVED=yes` 두 변수가 모두 켜져 있고 개인키가 있을 때만 Base Sepolia에서 실제 `pay`가 실행됩니다. 1건당 금액 상한은 없으므로 live로 켤 때는 예산과 잔액을 직접 확인하세요. 개인키는 절대 커밋하지 마세요.

## 벤치마크와 판매 모델

판매 모델(`data/catalog.json`)과 점수의 시작값(`data/benchmark.json`)은 세 출처에서 떠온 실제 값입니다. 성능은 [Epoch AI](https://epoch.ai/benchmarks) ECI, 가격은 [OpenRouter](https://openrouter.ai/api/v1/models) 판매 단가, 속도는 [Artificial Analysis](https://artificialanalysis.ai/methodology/performance-benchmarking) 출력 속도입니다. 세 점수 모두 후보 중 가장 나쁜 값 0점·가장 좋은 값 100점이고, 가격과 속도는 로그로 폅니다. 계산식과 짝짓기 규칙은 `agent_m2m/selection.py`, `agent_m2m/benchmark_sources.py` 맨 위에 있습니다.

| 우선순위 | 가격 | 속도 | 성능 |
|---|---|---|---|
| 싸게 (`price`) | 80 | 10 | 10 |
| 빠르게 (`speed`) | 10 | 80 | 10 |
| 똑똑하게 (`intelligence`) | 10 | 10 | 80 |
| 기본 (`default`) | 34 | 33 | 33 |

구매 요청이 들어왔을 때 가장 최근 값이 1시간보다 오래됐으면 세 출처에서 판매 목록에 있는 모델의 숫자만 새로 받습니다. 받다가 실패하면 마지막 값으로 계속하고 실패 사유를 결정 기록에 남깁니다.

```bash
uv run python scripts/capture_benchmark.py --list   # 저장하지 않고 짝지어진 모델과 뺀 모델만 보기
uv run python scripts/capture_benchmark.py          # data/catalog.json · benchmark.json · sellers.json 갱신
```

## 기록 저장소

기록은 MongoDB 의 `MONGODB_DB`(기본 `agent_m2m`) 데이터베이스에 저장합니다. 실행 전에 MongoDB 가 켜져 있어야 합니다.

| 컬렉션 | 담는 것 |
| --- | --- |
| `purchases` | 구매 기록(요청, 결정 근거, 결제, 결과, 상태) |
| `alerts` | 이상 거래 알림(차단·경고) |
| `snapshots` | 1시간마다 받아 온 벤치마크 숫자 |

테스트는 `agent_m2m_test_...` 이름의 임시 데이터베이스를 만들고 끝나면 지웁니다.
