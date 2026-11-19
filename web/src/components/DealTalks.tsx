"use client";

/**
 * 구매 상세의 협상 대화. 판매자마다 한 줄로 호가→합의를 보여주고, 누르면 실제 주고받은 말이 펼쳐진다.
 * 산 곳이 먼저 온다. 산 곳·취소·막음은 칩 대신 색 글자로 구분한다.
 */

import { useState } from "react";

import { aegisText } from "@/lib/format";
import type { Negotiation, PurchaseRecord } from "@/lib/types";

function label(quote: Negotiation, record: PurchaseRecord): { text: string; tone: string } {
  if (quote.status === "agreed") {
    if (record.blockedRule !== undefined) return { text: "결제 직전 막음", tone: "risk" };
    if (record.status === "FAILED") return { text: "결제 실패", tone: "risk" };
    return { text: "산 곳", tone: "win" };
  }
  if (quote.status === "cancelled") return { text: "취소", tone: "mute" };
  if (quote.status === "blocked") return { text: "중단", tone: "risk" };
  return { text: "결렬", tone: "mute" };
}

export function DealTalks({ quotes, record }: { quotes: Negotiation[]; record: PurchaseRecord }) {
  const ordered = [...quotes].sort((a, b) => Number(b.status === "agreed") - Number(a.status === "agreed"));
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="talks">
      {ordered.map((quote) => {
        const view = label(quote, record);
        const expanded = open.has(quote.key);
        const offers = quote.transcript.filter((turn) => turn.from === "buyer" && turn.action === "offer").length;
        return (
          <div className="talk" key={quote.key}>
            <button type="button" className="talkHead" aria-expanded={expanded} onClick={() => toggle(quote.key)}>
              <i className={`talkDot ${view.tone}`} aria-hidden="true" />
              <span className="talkName">
                <strong>
                  {quote.displayName} <span>· {quote.sellerName}</span>
                </strong>
                <small>
                  호가 {aegisText(quote.askUnits)} → {quote.agreedUnits === undefined ? "합의 없음" : `합의 ${aegisText(quote.agreedUnits)}`} · 구매 에이전트 제안 {offers}번
                </small>
              </span>
              <span className={`talkLabel ${view.tone}`}>{view.text}</span>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5f6878" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
            {expanded && (
              <div className="talkTurns">
                {quote.transcript.map((turn, index) => (
                  <div className={`talkTurn ${turn.from}`} key={index}>
                    <span>{turn.from === "buyer" ? "구매 에이전트" : quote.sellerName}</span>
                    <p>{turn.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
