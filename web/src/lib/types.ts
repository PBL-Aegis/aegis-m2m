/** 이 프로젝트에서 쓰는 값의 모양만 모아둔 곳. */

/** 요청이 무엇을 중요하게 보는지. speed 는 옛 기록에만 있고 새 요청에서는 받지 않는다. */
export type Priority = "default" | "price" | "speed" | "intelligence";

/** 필터에서 떨어진 후보와 그 이유. */
export interface RejectedCandidate {
  key: string;
  displayName: string;
  amountUnits: number;
  reasons: string[];
}

/** 필요 기능을 통과해 흥정에 넘어간 후보와 그 호가. */
export interface Candidate {
  key: string;
  displayName: string;
  providerId: string;
  providerModelId: string;
  recipient: string;
  amountUnits: number;
  /** Epoch ECI 와 95% 신뢰구간. 이 칸들이 생기기 전 기록에는 없다. */
  eci?: number;
  eciCiLow?: number;
  eciCiHigh?: number;
}

/** 구매 에이전트가 이 값을 부르거나 받거나 거절한 이유. 페르소나 규칙과 그때의 숫자다. */
export interface NegotiationReason {
  persona: string;
  /** opening·concede·accept·last-round·over-max·cancel·over-budget */
  rule: string;
  text: string;
  inputs: Record<string, string | number>;
}

/** 흥정 대화 한 줄. */
export interface NegotiationTurn {
  from: "buyer" | "seller";
  action: "offer" | "counter" | "accept" | "reject";
  priceUnits: number;
  text: string;
  /** 이 말을 하며 낸 근거 카드(성능 우위 등). */
  card?: string;
  /** 구매 에이전트의 말에만 있다. 페르소나가 생기기 전 기록에는 없다. */
  reason?: NegotiationReason;
}

/** 구매 에이전트의 페르소나(personas/*.md). hash 는 그때 쓴 파일의 지문이다. */
export interface PersonaRef {
  id: string;
  name: string;
  goal: string;
  hash?: string;
}

/** 운영자가 openDeal 로 체인에 여는 합의. 금액은 units, 해시와 주소는 0x 문자열이다. */
export interface Deal {
  requestId: string;
  buyer: string;
  seller: string;
  modelKey: string;
  askUnits: number;
  agreedUnits: number;
  transcriptHash: string;
  decisionHash: string;
}

/** 흥정이 끝난 뒤 페르소나 관점에서 이 구매가 이득이었는지. 코드가 기록의 숫자로 정한다. */
export interface Evaluation {
  persona: string;
  personaName: string;
  goal: string;
  verdict: "good" | "partial" | "bad";
  headline: string;
  lines: string[];
  /** 같은 요청을 최저가형으로 다시 계산한 값과의 비교. lines 의 "최저가 근거" 줄과 같은 숫자다. 이 칸이 생기기 전 기록에는 없다. */
  lowestPrice?: LowestPrice;
}

export interface LowestPrice {
  /** 다시 계산한 페르소나 이름(최저가형). */
  persona: string;
  key: string;
  displayName: string;
  priceUnits: number;
  paidUnits: number;
  gapUnits: number;
  /** gapUnits / priceUnits. */
  gapRatio: number;
}

/** 구매 에이전트와 판매 에이전트의 흥정 결과. 판매자의 최저가는 담기지 않는다. */
export interface Negotiation {
  key: string;
  displayName: string;
  sellerName: string;
  /** 값이 같을 때 고르는 기준인 성능. 이 칸이 생기기 전 기록에는 없다. */
  eci?: number;
  /** agreed 는 산 곳, cancelled 는 합의했지만 더 싼 곳이 있어 취소한 곳, no-deal 은 결렬된 곳이다. */
  status: "agreed" | "cancelled" | "no-deal" | "blocked";
  askUnits: number;
  maxUnits: number;
  /** 결렬된 곳에는 없다. */
  agreedUnits?: number;
  /** 비교 모델이 모두 결렬돼 예산을 넘겨 산 경우에만 있다. */
  overBudget?: boolean;
  transcript: NegotiationTurn[];
}

/** 흥정할 모델 한 곳. /api/purchase/stream 의 plan 에 담긴다. */
export interface StreamModel {
  key: string;
  displayName: string;
  sellerName: string;
  askUnits: number;
}

/** /api/purchase/stream 이 한 줄씩 보내는 진행 소식. */
export type PurchaseStreamEvent =
  | { type: "plan"; priority: Priority; persona?: { id: string; name: string }; models: StreamModel[] }
  | { type: "turn"; key: string; turn: NegotiationTurn }
  | { type: "done"; record: PurchaseRecord }
  | { type: "error"; error: string };

/** 선택이 끝난 뒤 남는 기록 전체. */
export interface Decision {
  snapshotId: string;
  snapshotHash: string;
  /** 이 결정이 본 숫자를 받아 온 시각. 이 칸이 생기기 전 기록에는 없다. */
  snapshotCapturedAt?: string;
  catalogVersion: string;
  priority: Priority;
  /** 우선순위를 정한 로컬 LLM 모델 이름. 사용자가 우선순위를 직접 고르던 때의 기록에는 없다. */
  priorityModel?: string;
  estimatedInputTokens: number;
  maxOutputTokens: number;
  budgetUnits: number;
  candidates: Candidate[];
  rejected: RejectedCandidate[];
  /** amountUnits 는 합의가, listAmountUnits 는 호가다. 흥정이 생기기 전 기록에는 listAmountUnits 가 없다. */
  winner: Candidate & { listAmountUnits?: number };
  /** 산 곳과의 흥정. 이 칸이 생기기 전 기록에는 없다. */
  negotiation?: Negotiation;
  /** 후보로 남아 흥정한 곳 전부. 이 칸이 생기기 전 기록에는 없다. */
  quotes?: Negotiation[];
  /** 흥정한 페르소나와 그 관점의 평가. 페르소나가 생기기 전 기록에는 없다. */
  persona?: PersonaRef;
  /** 체인에 저장한 합의. 대화와 결정 근거는 해시만 담는다. 이 칸이 생기기 전 기록에는 없다. */
  deal?: Deal;
  evaluation?: Evaluation;
}

/** local 은 이 컴퓨터의 anvil(자동 테스트 포함). 예전 기록에는 체인 없이 흐름만 잇던 "mock" 이 남아 있을 수 있다. */
export type PaymentMode = "local";

export interface PaymentResult {
  mode: PaymentMode;
  txHash: string;
  from: string;
  to: string;
  amountUnits: number;
  tokenAddress: string;
  chainId: number;
  /** 체인에 넘긴 요청 번호(keccak256). 이 칸이 생기기 전 기록에는 없다. */
  requestIdHash?: string;
  /** 체인에 저장한 합의의 해시. x402 서명의 nonce 이기도 하다. 흥정한 구매에만 있다. */
  dealHash?: string;
  /** 결제 방식. x402 로 바뀐 뒤의 기록에만 있다. */
  protocol?: "x402";
  /** x402 네트워크 이름(예: eip155:31337). */
  network?: string;
  /** x402 정산 거래를 보낸 정산 서버 지갑. */
  facilitator?: string;
  /** 체인에 보냈을 때(local·live)만 채워진다. */
  blockNumber?: string;
}

/** 감사 보고서. 원문은 DB 에 있고 결과·걸린 규칙·해시는 체인에 남는다. */
export interface AuditReport {
  stage: "before-send" | "after-send";
  result: "pass" | "alert" | "block";
  checked: string[];
  findings: { rule: string; outcome: "alert" | "block"; message: string }[];
}

export interface AuditEntry {
  report: AuditReport;
  /** 보고서 원문의 해시. 체인에 남은 값과 같아야 한다. */
  hash: string;
  /** 체인에 올린 거래. 올리지 못했으면 null 이고 chainError 에 사유가 있다. */
  txHash: string | null;
  chainError?: string;
}

/** PROCESSING 은 결제 직전에 저장되고, 끝나면 SETTLED 나 FAILED 로 바뀐다. */
export type PurchaseStatus = "PROCESSING" | "SETTLED" | "FAILED";

/** 실패가 송금 전인지 후인지. 송금 후 실패는 돈이 나갔을 수 있으므로 다시 결제하면 안 된다. */
export type FailureStage = "before-send" | "after-send";

export interface PurchaseRecord {
  id: string;
  /** 이 칸들이 생기기 전 기록에는 없다. */
  requestId?: string;
  userId?: string | null;
  createdAt: string;
  /** 상태가 마지막으로 바뀐 시각. 이 칸이 생기기 전 기록에는 없다. */
  updatedAt?: string;
  prompt: string;
  /** 처리할 내용. 이 칸이 생기기 전 기록과 내용 없이 보낸 요청에는 없다. */
  content?: string | null;
  /** 송금 직전·뒤 감사 보고서. 체인에 감사를 남기기 전 기록에는 없다. */
  audit?: { beforeSend?: AuditEntry; afterSend?: AuditEntry };
  status: PurchaseStatus;
  decision: Decision;
  payment: PaymentResult | null;
  resultText: string | null;
  failureReason: string | null;
  /** FAILED 일 때만 채워진다. 이 칸이 생기기 전 기록에는 없다. */
  failureStage?: FailureStage;
  /** 감사 규칙이 결제를 막았을 때 그 규칙 이름. */
  blockedRule?: string;
}

/** 감사 규칙이 어느 자리에서 돌았는지. */
export type AuditStage = "on-request" | "before-payment" | "after-payment";

/**
 * 감사 규칙이 남긴 알림. 대시보드의 "이상 거래"가 이 목록을 보여준다.
 * 규칙이 결제를 막으면 blocked 가 true 인 알림이 자동으로 남고, ctx.alert 로 남긴 경고는 false 다.
 */
export interface AuditAlert {
  id: string;
  createdAt: string;
  /** 요청 직후에 막힌 경우에는 이 번호의 구매 기록이 없다. */
  purchaseId: string;
  userId: string | null;
  /** 이 칸들이 생기기 전 알림에는 없다. */
  requestId?: string;
  stage?: AuditStage;
  blocked?: boolean;
  /** 알림을 남긴 규칙 이름. */
  rule: string;
  message: string;
}
