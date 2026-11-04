"use client";

/**
 * 판매 에이전트 한 곳과의 흥정. 채팅에서는 진행 중에 펼쳐 두고, 끝나면 접는다.
 * 막대는 구매자 값과 판매자 값 사이의 간격이다. 흥정이 진행될수록 좁아진다.
 */

import { useState } from "react";

import { aegisText } from "@/lib/format";
import type { StatusView } from "@/lib/purchase-view";
import type { NegotiationTurn } from "@/lib/types";

/** 막대가 안 보일 만큼 좁아지지 않게 하는 최소 폭(%). */
const MIN_GAP_PERCENT = 1.5;

export function BuyerAvatar() {
  return (
    <span className="avatar buyer" aria-hidden="true">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 5h2l2 11h10l2-8H7" />
        <circle cx="9.5" cy="20" r="1" />
        <circle cx="17" cy="20" r="1" />
      </svg>
    </span>
  );
}

function gap(turns: NegotiationTurn[], askUnits: number) {
  const buyerTurns = turns.filter((turn) => turn.from === "buyer" && turn.action !== "reject");
  const sellerTurns = turns.filter((turn) => turn.from === "seller");
  const opening = buyerTurns[0]?.priceUnits ?? askUnits;
  const buyer = buyerTurns[buyerTurns.length - 1]?.priceUnits ?? opening;
  const seller = sellerTurns[sellerTurns.length - 1]?.priceUnits ?? askUnits;
  const span = askUnits - opening;
  const left = span > 0 ? ((buyer - opening) / span) * 100 : 0;
  const right = span > 0 ? ((seller - opening) / span) * 100 : 100;
  return { buyer, seller, left, width: Math.max(right - left, MIN_GAP_PERCENT) };
}

export function NegotiationBlock({
  displayName,
  sellerName,
  askUnits,
  turns,
  live,
  status,
}: {
  displayName: string;
  sellerName: string;
  askUnits: number;
  turns: NegotiationTurn[];
  live: boolean;
  status: StatusView;
}) {
  const [picked, setPicked] = useState<boolean | null>(null);
  const expanded = picked ?? live;
  const mark = sellerName.charAt(0);
  const { buyer, seller, left, width } = gap(turns, askUnits);

  return (
    <section className="deal" aria-label={`${sellerName}와 흥정`}>
      <button
        type="button"
        className={`dealHead${live ? " live" : ""}`}
        aria-expanded={expanded}
        onClick={() => setPicked(!expanded)}
      >
        <span className="dealTitle">
          <span className="avatar" aria-hidden="true">{mark}</span>
          <span className="dealName">
            <strong>{displayName}</strong>
            <span>{sellerName} · 호가 {aegisText(askUnits)}</span>
          </span>
          <span className={`badge ${status.tone}`}>{status.label}</span>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5f6878" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
        <span className="dealBar">
          <i style={{ left: `${left}%`, width: `${width}%` }} />
        </span>
        <span className="dealPrices">
          <span>구매 {aegisText(buyer)}</span>
          <span>판매 {aegisText(seller)}</span>
        </span>
      </button>

      {expanded && (
        <div className="dealTurns">
          {turns.map((turn, index) =>
            turn.from === "buyer" ? (
              <div className="msg" key={index}>
                <BuyerAvatar />
                <div className="msgBody">
                  {index < 2 && <span className="msgName">구매 에이전트</span>}
                  <div className="bubble buyer">{turn.text}</div>
                </div>
              </div>
            ) : (
              <div className="msg right" key={index}>
                <div className="msgBody">
                  {index < 2 && <span className="msgName">{sellerName}</span>}
                  <div className="bubble seller">{turn.text}</div>
                </div>
                <span className="avatar" aria-hidden="true">{mark}</span>
              </div>
            ),
          )}
        </div>
      )}
    </section>
  );
}
