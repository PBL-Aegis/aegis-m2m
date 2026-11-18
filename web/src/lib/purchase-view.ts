/**
 * 구매 기록을 화면에 보여줄 말로 바꾼다. 채팅·기록·상세가 같은 말을 쓰게 한곳에 둔다.
 */

import { aegisText } from "@/lib/format";
import type { AuditReport, Evaluation, Negotiation, NegotiationTurn, PurchaseRecord } from "@/lib/types";

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
  "persona-gap": "구매 성향 차이",
  "seller-collusion": "담합 의심",
  "over-budget": "예산 초과",
  limit: "결제 한도",
  "duplicate-purchase": "반복 구매",
  "after-payment": "결제 후 감사 오류",
};

export function ruleName(rule: string): string {
  return RULE_NAME[rule] ?? rule;
}

/** 송금 전후 감사에 걸린 것. 막음을 알림보다 먼저 둔다. */
export function auditFindings(record: PurchaseRecord): AuditReport["findings"] {
  const findings = [record.audit?.beforeSend, record.audit?.afterSend].flatMap((entry) => entry?.report.findings ?? []);
  return [...findings.filter((finding) => finding.outcome === "block"), ...findings.filter((finding) => finding.outcome !== "block")];
}

/** 규칙 문장을 결과 카드에 넣을 한 줄로 줄인다. 모양이 다르면 첫 문장을 쓴다. 전체 문장은 이상 거래 화면에 있다. */
export function shortReason(finding: AuditReport["findings"][number]): string {
  const { rule, message } = finding;
  const match = (pattern: RegExp) => message.match(pattern);
  if (rule === "intent-swap") {
    const quoted = match(/지시처럼 보이는 문장: “(.+?)”/);
    if (quoted) return `문서 속 "${quoted[1]}"`;
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
  if (record.blockedRule !== undefined) return `감사 규칙이 송금 직전에 막아서 돈은 나가지 않았어요. ${record.failureReason}`;
  const stage = record.failureStage === "after-send" ? "송금 뒤에 실패했어요. 돈이 나갔을 수 있어요." : "송금 전에 실패했어요.";
  return `${stage} ${record.failureReason}`;
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
