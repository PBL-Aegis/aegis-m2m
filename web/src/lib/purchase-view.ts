/**
 * 구매 기록을 화면에 보여줄 말로 바꾼다. 채팅·기록·상세가 같은 말을 쓰게 한곳에 둔다.
 */

import { aegisText } from "@/lib/format";
import type { Negotiation, NegotiationTurn, PurchaseRecord } from "@/lib/types";

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
  if (record.blockedRule !== undefined) return { label: "차단", tone: "risk" };
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
  if (last === undefined || !endsDeal(last)) return { label: "흥정 중", tone: "live" };
  return last.action === "accept" ? { label: `합의 ${aegisText(last.priceUnits)}`, tone: "live" } : { label: "결렬", tone: "mute" };
}

export function quoteStatus(quote: Negotiation, record: PurchaseRecord): StatusView {
  if (quote.status === "agreed") {
    const price = aegisText(quote.agreedUnits ?? 0);
    if (record.blockedRule !== undefined) return { label: `차단 ${price}`, tone: "risk" };
    if (record.status === "FAILED") return { label: `합의 ${price}`, tone: "risk" };
    return quote.overBudget ? { label: "예산 초과 구매", tone: "warn" } : { label: `구매 ${price}`, tone: "win" };
  }
  if (quote.status === "cancelled") return { label: "취소", tone: "mute" };
  if (quote.status === "blocked") return { label: "중단", tone: "risk" };
  return { label: "결렬", tone: "mute" };
}

function lastSellerPrice(quote: Negotiation): number {
  const prices = quote.transcript.filter((turn) => turn.from === "seller").map((turn) => turn.priceUnits);
  return prices[prices.length - 1] ?? quote.askUnits;
}

export function purchaseTitle(record: PurchaseRecord): string {
  const name = record.decision.winner.displayName;
  if (record.blockedRule !== undefined) return "결제를 막았어요";
  if (record.status === "FAILED") return `${name} 결제에 실패했어요`;
  return isOverBudget(record) ? `예산을 넘겨 ${name}로 샀어요` : `${name}로 샀어요`;
}

/** 결제가 안 된 까닭. 돈이 나갔을 수 있는지를 먼저 말한다. 성공한 기록에는 없다. */
export function failureText(record: PurchaseRecord): string | null {
  if (record.failureReason === null) return null;
  if (record.blockedRule !== undefined) return `감사 규칙이 송금 직전에 막아서 돈은 나가지 않았어요. ${record.failureReason}`;
  const stage = record.failureStage === "after-send" ? "송금 뒤에 실패했어요. 돈이 나갔을 수 있어요." : "송금 전에 실패했어요.";
  return `${stage} ${record.failureReason}`;
}

/** 왜 이곳에서 샀는지. 흥정이 생기기 전 기록에는 없다. */
export function purchaseReason(record: PurchaseRecord): string | null {
  const { decision } = record;
  const chosen = decision.negotiation;
  if (chosen === undefined) return null;

  const { winner, budgetUnits } = decision;
  const name = winner.displayName;
  const paid = winner.amountUnits;
  const others = quotesOf(record).filter((quote) => quote.key !== chosen.key);

  if (chosen.overBudget) {
    const lasts = quotesOf(record)
      .map((quote) => `${quote.displayName} ${aegisText(lastSellerPrice(quote))}`)
      .join(", ");
    const pick = others.length > 0 ? `더 낮은 ${name}` : name;
    return `예산 ${aegisText(budgetUnits)}까지 내려오지 않아 흥정이 결렬됐어요. 판매자가 마지막에 부른 값이 ${lasts}라서 ${pick}로 샀어요. 예산을 ${aegisText(paid - budgetUnits)} 넘었어요.`;
  }

  const cancelled = others.find((quote) => quote.status === "cancelled");
  const failed = others.find((quote) => quote.status !== "cancelled");
  const sentences: string[] = [];
  if (cancelled !== undefined && cancelled.agreedUnits === paid) {
    sentences.push(`두 곳 모두 ${aegisText(paid)}에 합의했어요. 값이 같아 성능(ECI)이 더 높은 ${name}(${chosen.eci}, ${cancelled.displayName} ${cancelled.eci})로 골랐어요.`);
  } else if (cancelled !== undefined) {
    sentences.push(`두 곳 모두 합의했는데, ${name} 쪽이 ${aegisText(paid)}로 ${cancelled.displayName}(${aegisText(cancelled.agreedUnits ?? 0)})보다 쌌어요.`);
  } else if (failed !== undefined) {
    sentences.push(`${failed.displayName} 쪽은 결렬됐고 ${name} 쪽과 ${aegisText(paid)}에 합의했어요.`);
  } else {
    sentences.push(`${name} 쪽과 ${aegisText(paid)}에 합의했어요.`);
  }
  if (winner.listAmountUnits !== undefined && winner.listAmountUnits > paid) {
    sentences.push(`호가보다 ${aegisText(winner.listAmountUnits - paid)} 깎았어요.`);
  }
  if (cancelled !== undefined) sentences.push(`${cancelled.sellerName}와의 합의는 취소했어요.`);
  return sentences.join(" ");
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
