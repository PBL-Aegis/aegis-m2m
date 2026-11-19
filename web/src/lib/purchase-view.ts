/**
 * 구매 기록을 화면에 보여줄 말로 바꾼다. 채팅·기록·상세가 같은 말을 쓰게 한곳에 둔다.
 */

import { aegisText } from "@/lib/format";
import type { AuditReport, Evaluation, Negotiation, NegotiationReason, NegotiationTurn, PurchaseRecord } from "@/lib/types";

export type Tone = "live" | "win" | "ok" | "warn" | "risk" | "mute";

export interface StatusView {
  label: string;
  tone: Tone;
}

/** 흥정한 곳 전부. quotes 가 생기기 전 기록은 산 곳 하나, 흥정이 생기기 전 기록은 빈 목록이다. */
export function quotesOf(record: PurchaseRecord): Negotiation[] {
  const { quotes, negotiation } = record.decision;
  return quotes ?? (negotiation === undefined ? [] : [negotiation]);
}

export function isOverBudget(record: PurchaseRecord): boolean {
  return record.decision.negotiation?.overBudget === true;
}

export function purchaseStatus(record: PurchaseRecord): StatusView {
  if (record.status === "PROCESSING") return { label: "처리 중", tone: "live" };
  if (record.blockedRule !== undefined) return { label: "막음", tone: "risk" };
  if (record.status === "FAILED") return { label: "결제 실패", tone: "risk" };
  if (isOverBudget(record)) return { label: "예산 초과", tone: "warn" };
  return { label: "정산 완료", tone: "ok" };
}

/** 이 줄로 흥정이 끝난다. 판매자가 받았거나 구매자가 거절했을 때다. */
export function endsDeal(turn: NegotiationTurn): boolean {
  return (turn.from === "seller" && turn.action === "accept") || (turn.from === "buyer" && turn.action === "reject");
}

/** 대화만 보고 정하는 흥정 결과. 어디서 살지 정해지기 전에 쓴다. */
export function dealStatus(turns: NegotiationTurn[]): StatusView {
  const last = turns[turns.length - 1];
  if (last === undefined) return { label: "대기 중", tone: "mute" };
  if (!endsDeal(last)) return { label: "흥정 중", tone: "live" };
  return last.action === "accept" ? { label: `합의 ${aegisText(last.priceUnits)}`, tone: "live" } : { label: "결렬", tone: "mute" };
}

export function quoteStatus(quote: Negotiation, record: PurchaseRecord): StatusView {
  if (quote.status === "agreed") {
    // 금액은 카드 아래 "구매 …" 줄에 있다. 배지에 또 넣으면 폭을 차지해 판매자 이름이 꺾인다.
    if (record.blockedRule !== undefined) return { label: "막음", tone: "risk" };
    if (record.status === "FAILED") return { label: "합의", tone: "risk" };
    return quote.overBudget ? { label: "예산 초과 구매", tone: "warn" } : { label: "구매", tone: "win" };
  }
  if (quote.status === "cancelled") return { label: "취소", tone: "mute" };
  if (quote.status === "blocked") return { label: "중단", tone: "risk" };
  return { label: "결렬", tone: "mute" };
}

export function purchaseTitle(record: PurchaseRecord): string {
  const name = record.decision.winner.displayName;
  if (record.blockedRule !== undefined) return "결제를 막았어요";
  if (record.status === "FAILED") return `${name} 결제에 실패했어요`;
  return isOverBudget(record) ? `예산을 넘겨 ${name}로 샀어요` : `${name}로 샀어요`;
}

/** 결제가 안 된 까닭. 돈이 나갔을 수 있는지를 먼저 말한다. 성공한 기록에는 없다. */
/** 감사 규칙 이름을 화면에 보일 말로. 모르는 규칙은 이름 그대로 둔다. */
const RULE_NAME: Record<string, string> = {
  "intent-swap": "숨긴 지시",
  holdout: "협상 깨기",
  "holdout-stall": "판매자 버티기",
  "holdout-seller-rate": "자주 버티는 판매자",
  "persona-gap": "품질형 추가 비용",
  "seller-collusion": "담합 의심",
  "over-budget": "예산 초과",
  limit: "결제 한도",
  "duplicate-purchase": "반복 구매",
  "after-payment": "결제 후 감사 오류",
};

export function ruleName(rule: string): string {
  return RULE_NAME[rule] ?? rule;
}

/** 협상 깨기 규칙이 함께 남기는 보조 알림. 화면에서는 따로 세지 않고 협상 깨기의 근거로 보여 준다. */
export const HOLDOUT_EXTRAS = new Set(["holdout-stall", "holdout-seller-rate"]);

/** 화면에 보일 규칙 이름. 보조 알림은 협상 깨기로 묶는다. */
export function scenarioRule(rule: string): string {
  return HOLDOUT_EXTRAS.has(rule) ? "holdout" : rule;
}

export type AuditResult = "pass" | "alert" | "block";

/** 이 구매의 감사 결과 하나. 막음이 있으면 막음, 알림이 있으면 알림, 없으면 통과다. */
export function auditResult(record: PurchaseRecord): AuditResult {
  if (record.blockedRule !== undefined) return "block";
  const findings = auditFindings(record);
  if (findings.some((finding) => finding.outcome === "block")) return "block";
  return findings.length > 0 ? "alert" : "pass";
}

/** 이 구매에 걸린 규칙 이름들. 보조 알림은 협상 깨기로 묶고 겹치면 한 번만 쓴다. 막음이 앞에 온다. */
export function recordRules(record: PurchaseRecord): string[] {
  const rules = auditFindings(record).map((finding) => scenarioRule(finding.rule));
  if (record.blockedRule !== undefined) rules.unshift(scenarioRule(record.blockedRule));
  return [...new Set(rules)];
}

/** 송금 전후 감사에 걸린 것. 막음을 알림보다 먼저 둔다. */
export function auditFindings(record: PurchaseRecord): AuditReport["findings"] {
  const findings = [record.audit?.beforeSend, record.audit?.afterSend].flatMap((entry) => entry?.report.findings ?? []);
  return [...findings.filter((finding) => finding.outcome === "block"), ...findings.filter((finding) => finding.outcome !== "block")];
}

/** 규칙 문장을 결과 카드에 넣을 한 줄로 줄인다. 모양이 다르면 첫 문장을 쓴다. 전체 문장은 이상 거래 화면에 있다. */
export function shortReason(finding: { rule: string; message: string }): string {
  const { rule, message } = finding;
  const match = (pattern: RegExp) => message.match(pattern);
  if (rule === "intent-swap") {
    const tier = match(/가 '(.+?)'로 정해/);
    if (tier) return `문서 속 숨은 지시가 등급을 '${tier[1]}'로 바꿔 결제 직전에 멈췄어요`;
  } else if (rule === "persona-gap") {
    const percent = match(/\(([\d.]+%)\) 비쌉니다/);
    if (percent) return `최저가형이었다면 ${percent[1]} 덜 냈어요`;
  } else if (rule === "holdout") {
    const percent = match(/\((\d+%)\) 더 냄/);
    if (percent) return `판매자가 값을 버텨 예산보다 ${percent[1]} 더 내야 했어요`;
  } else if (rule === "holdout-stall") {
    const count = match(/마지막 (\d+)번 같은 값/);
    if (count) return `판매자가 값을 내리지 않고 마지막 ${count[1]}번 같은 값을 불렀어요`;
  } else if (rule === "holdout-seller-rate") {
    const rate = match(/최근 (\d+)건 중 (\d+)건/);
    if (rate) return `이 판매자에게서 산 최근 ${rate[1]}건 중 ${rate[2]}건이 결렬 뒤 예산 초과 구매예요`;
  } else if (rule === "seller-collusion") {
    return "여러 판매자가 함께 값을 덜 깎아 평소보다 비싸게 샀어요";
  }
  return message.split(/(?<=[.다])\s/)[0];
}

export function failureText(record: PurchaseRecord): string | null {
  if (record.failureReason === null) return null;
  if (record.blockedRule !== undefined) {
    // 규칙의 긴 원문은 이상 거래 화면의 자세히에 있다. 여기서는 한 줄 요약만 붙인다.
    const finding = auditFindings(record).find((item) => item.outcome === "block");
    return `감사 규칙이 송금 직전에 막아서 돈은 나가지 않았어요. ${finding === undefined ? record.failureReason : shortReason(finding)}`;
  }
  const stage = record.failureStage === "after-send" ? "송금 뒤에 실패했어요. 돈이 나갔을 수 있어요." : "송금 전에 실패했어요.";
  return `${stage} ${record.failureReason}`;
}

/** 퍼센트 한 자리 표기. 0.15 → "15%". */
function percent(ratio: unknown): string {
  return typeof ratio === "number" ? `${Math.round(ratio * 100)}%` : "";
}

/**
 * 구매 에이전트가 그 값을 부른 이유를 한 줄로. 서버 문장에는 계산에 쓴 금액이 모두 들어 있어 길다.
 * 규칙과 입력값으로 줄이고, 모르는 규칙은 페르소나 이름만 떼고 원문을 쓴다. 원문은 마우스를 올리면 보인다.
 */
export function reasonShort(reason: NegotiationReason): string {
  const { rule, inputs } = reason;
  if (rule === "opening") return `호가의 ${percent(inputs.openingRatio)}에서 시작`;
  if (rule === "concede") {
    if (inputs.freshness === "new") return `판매자의 새 근거 '${inputs.card}'를 듣고 차이의 ${percent(inputs.ratio)} 올림`;
    if (inputs.freshness === "used") return `이미 들은 근거 '${inputs.card}'라 차이의 ${percent(inputs.ratio)}만 올림`;
    return `판매자가 근거 없이 버텨 차이의 ${percent(inputs.ratio)}만 올림`;
  }
  if (rule === "accept") return "조금만 올리면 판매자 값에 닿아 그 값에 삼";
  if (rule === "last-round") return "제안 5번을 다 해서 최대가 안의 판매자 값을 받음";
  if (rule === "over-max") return "판매자 값이 최대가를 넘어 거절";
  if (rule === "over-budget") return "모두 결렬돼 가장 낮게 부른 곳에서 예산을 넘겨 삼";
  return reason.text.replace(/^[^:]+:\s*/, "");
}

/**
 * 거래 평가 줄을 읽기 쉽게 다듬는다. 서버 문장은 기록에 남은 그대로라, 이미 쌓인 기록도 같은 모양으로 보이게 화면에서 고친다.
 * "최저가 근거" 줄은 숫자(lowestPrice)로 다시 쓰고, 최저가형끼리 같은 값이면 뺀다. 0% 깎은 줄은 "호가 그대로"로 쓴다.
 */
export function evaluationLines(evaluation: Evaluation): string[] {
  return evaluation.lines.flatMap((line) => {
    if (line.startsWith("최저가 근거:")) {
      const low = evaluation.lowestPrice;
      if (low === undefined) return [line.replace(/^최저가 근거:\s*/, "")];
      if (low.gapUnits <= 0) return [];
      return [`${low.persona}이었다면 ${low.displayName}를 ${aegisText(low.priceUnits)}에 샀어요 (${percent(low.gapRatio)} 덜 냄)`];
    }
    return [line.replace(/호가 (\S+ AEGIS)에서 \S+ AEGIS로 0% 깎아 샀습니다\./, "호가 $1 그대로 샀습니다.")];
  });
}

export const VERDICT_VIEW: Record<Evaluation["verdict"], StatusView> = {
  good: { label: "이득", tone: "ok" },
  partial: { label: "일부 이득", tone: "warn" },
  bad: { label: "손해", tone: "risk" },
};

/** 긴 해시를 앞뒤만 남겨 줄인다. */
export function shortHash(hash: string): string {
  return `${hash.slice(0, 6)}…${hash.slice(-4)}`;
}

/** 가격·성능표를 받은 날. 시간대는 아래 shortTime 과 같이 고정한다. */
export function priceDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric" });
}

/** 서버와 브라우저가 같은 글자를 그리도록 시간대를 고정한다. */
export function shortTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
