/** 이 프로젝트에서 쓰는 값의 모양만 모아둔 곳. */

/** 요청이 무엇을 중요하게 보는지. 이 네 값이 가중치 한 줄을 고른다. */
export type Priority = "default" | "price" | "speed" | "intelligence";

export const PRIORITIES: readonly Priority[] = [
  "default",
  "price",
  "speed",
  "intelligence",
];

/** 가격·시간·지능에 몇 점씩 줄지. 세 값의 합은 항상 100. */
export interface Weights {
  price: number;
  time: number;
  intelligence: number;
}

/** 우선순위마다 고정된 배점표. 코드 밖에서 바꿀 수 없다. */
export const PRIORITY_WEIGHTS: Record<Priority, Weights> = {
  default: { price: 34, time: 33, intelligence: 33 },
  price: { price: 80, time: 10, intelligence: 10 },
  speed: { price: 10, time: 80, intelligence: 10 },
  intelligence: { price: 10, time: 10, intelligence: 80 },
};

/**
 * 팔고 있는 모델 하나. data/catalog.json 은 scripts/capture-benchmark.mjs 가 세 출처를 짝지어 만든다.
 * 수신자 주소는 회사별 판매자 주소(data/sellers.json)다.
 */
export interface CatalogEntry {
  /** OpenRouter 모델 id. 예: anthropic/claude-opus-5.5 */
  key: string;
  providerId: string;
  providerModelId: string;
  displayName: string;
  /** Epoch ECI 표의 모델 이름. */
  epochModel: string;
  openRouterId: string;
  /** 속도를 가져온 Artificial Analysis 항목들. 같은 모델의 생각 단계별 항목이다. */
  aaSlugs: string[];
  recipient: string;
  /** OpenRouter 가 알려 준 기능: reasoning, tools, vision */
  capabilities: string[];
}

export interface Catalog {
  catalogVersion: string;
  /** 짝짓기 규칙. */
  matching?: string;
  entries: CatalogEntry[];
  /** 짝을 찾지 못해 팔지 않는 모델과 그 이유. */
  excluded?: { name: string; reason: string }[];
}

/** 벤치마크 표의 한 줄. 숫자는 문자열로 둔다(소수점 오차를 만들지 않기 위해). */
export interface BenchmarkModel {
  key: string;
  epochModel: string;
  /** Epoch 가 이 모델의 ECI 를 낸 기준 날짜. */
  epochDate?: string;
  /** Epoch Capabilities Index 와 95% 신뢰구간. */
  eci: string;
  eciCiLow: string;
  eciCiHigh: string;
  /** OpenRouter 판매 단가(1M 토큰당 달러). */
  inputPricePerMillion: string;
  outputPricePerMillion: string;
  /** AA 가 잰 출력 속도(토큰/초) 최근 72시간 중앙값을 생각 단계별로 평균낸 값. */
  outputTokensPerSecond: string;
  openRouterId: string;
  aaSlugs: string[];
  aaModelNames: string[];
}

export interface BenchmarkSnapshot {
  snapshotId: string;
  capturedAt: string;
  source: string;
  sources?: { epoch: string; openRouter: string; aa: string };
  note: string;
  models: BenchmarkModel[];
}

/** 사용자가 보낸 요청. */
export interface PurchaseRequest {
  /** 요청을 보낸 프로그램이 붙인 요청 번호. 같은 요청을 다시 보내면 같은 번호가 온다. */
  requestId: string;
  /** 요청한 사용자. 사용자 확인 방식은 아직 정하지 않았다. */
  userId: string | null;
  prompt: string;
  budgetUnits: number;
  priority: Priority;
  maxOutputTokens?: number;
  requiredCapabilities?: string[];
}

/**
 * API 로 들어온 요청. 우선순위가 비어 있으면 로컬 Qwen 이 요청 문장을 보고 채운다.
 * 요청 번호가 비어 있으면 서버가 새로 만들고, 사용자가 비어 있으면 null 로 둔다.
 */
export type PurchaseInput = Omit<PurchaseRequest, "priority" | "requestId" | "userId"> & {
  priority?: Priority;
  requestId?: string;
  userId?: string;
};

/** 결정에 쓰인 우선순위가 어디서 왔는지. */
export type PrioritySource = "request" | "local-llm";

/** 필터에서 떨어진 후보와 그 이유. */
export interface RejectedCandidate {
  key: string;
  displayName: string;
  amountUnits: number;
  reasons: string[];
}

/** 점수까지 매겨진 후보. */
export interface ScoredCandidate {
  key: string;
  displayName: string;
  providerId: string;
  providerModelId: string;
  recipient: string;
  amountUnits: number;
  /** 출력 속도(토큰/초). 이 칸이 생기기 전 기록에는 없다. */
  outputTokensPerSecond?: number;
  /** 옛 기록(끝까지 걸린 시간으로 속도를 매기던 때)에만 있다. */
  completionMs?: number;
  /** Epoch ECI 와 95% 신뢰구간. 이 칸들이 생기기 전 기록에는 없다. */
  eci?: number;
  eciCiLow?: number;
  eciCiHigh?: number;
  /** 속도를 가져온 AA 항목 이름들(생각 단계 포함). */
  aaModelNames?: string[];
  /** 옛 기록에만 있다. 속도를 가져온 AA 항목 하나. */
  aaModelName?: string;
  /** 옛 기록(AA 지능 지수 + LMArena)에만 있는 칸. */
  intelligenceIndex?: number;
  arenaModel?: string;
  arenaRating?: number;
  effortPairing?: string;
  aaScore?: number;
  arenaScore?: number;
  priceScore: number;
  timeScore: number;
  /** 성능 점수. 새 기록은 ECI 를 후보 중 최저 0점·최고 100점으로 편 값이다. 가중치의 "성능" 칸에 들어간다. */
  intelligenceScore: number;
  totalScore: number;
  rank: number;
}

/** 선택이 끝난 뒤 남는 기록 전체. */
export interface Decision {
  snapshotId: string;
  snapshotHash: string;
  /** 이 결정이 본 숫자를 받아 온 시각. 이 칸이 생기기 전 기록에는 없다. */
  snapshotCapturedAt?: string;
  /** 새 값을 받으려다 실패해 마지막 값으로 고른 경우 그 사유. */
  snapshotRefreshError?: string;
  catalogVersion: string;
  priority: Priority;
  /** 우선순위를 요청이 정했는지 LLM이 추론했는지. 이 칸이 생기기 전 기록에는 없다. */
  prioritySource?: PrioritySource;
  /** LLM이 추론했을 때 쓴 모델 이름. */
  priorityModel?: string;
  weights: Weights;
  estimatedInputTokens: number;
  maxOutputTokens: number;
  budgetUnits: number;
  references: {
    minAmountUnits: number;
    /** 가격·속도를 로그로 펴기 시작한 뒤의 기록에만 있다. */
    maxAmountUnits?: number;
    /** 출력 속도로 바꾼 뒤의 기록에만 있다. */
    minOutputTokensPerSecond?: number;
    maxOutputTokensPerSecond?: number;
    /** 옛 기록에만 있다. */
    minCompletionMs?: number;
    maxCompletionMs?: number;
    minEci?: number;
    maxEci?: number;
    /** 옛 기록에만 있다. */
    maxIntelligenceIndex?: number;
    maxArenaRating?: number;
  };
  /** 점수를 만든 출처와 계산 방법. 옛 기록은 aa·arena 칸을 쓴다. */
  performanceSources?: {
    performance?: string;
    price?: string;
    speed?: string;
    aa?: string;
    arena?: string;
    arenaPublishDate?: string | null;
    combine: string;
  };
  candidates: ScoredCandidate[];
  rejected: RejectedCandidate[];
  winner: ScoredCandidate;
}

/** local 은 이 컴퓨터의 anvil(자동 테스트 포함), live 는 Base Sepolia. 예전 기록에는 체인 없이 흐름만 잇던 "mock" 이 남아 있을 수 있다. */
export type PaymentMode = "local" | "live";

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
  /** 체인에 보냈을 때(local·live)만 채워진다. */
  blockNumber?: string;
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
  status: PurchaseStatus;
  decision: Decision;
  payment: PaymentResult | null;
  resultText: string | null;
  failureReason: string | null;
  /** FAILED 일 때만 채워진다. 이 칸이 생기기 전 기록에는 없다. */
  failureStage?: FailureStage;
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
