/**
 * 구매 상세 맨 위의 거래 흐름 한 줄: 사용자 → 구매 에이전트 ⇄ 판매 에이전트 → 감사 → 결제(체인).
 * 협상 구간은 빛이 양쪽으로 오가고, 나머지는 한 방향으로 흐른다. 막았으면 빛이 감사에서 멈추고 결제 구간은 점선으로 끊긴다.
 */

import { aegisText } from "@/lib/format";
import { auditResult, quotesOf, recordRules, ruleName } from "@/lib/purchase-view";
import type { PurchaseRecord } from "@/lib/types";

const ICONS = {
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21a8 8 0 0 1 16 0"],
  buyer: ["M6 7h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z", "M12 3v4", "M9 12h.01", "M15 12h.01", "M9 16h6"],
  seller: ["M3 9l1.5-5h15L21 9", "M4 9v11h16V9", "M3 9h18", "M10 20v-6h4v6"],
  pay: ["M4 6h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z", "M2 10h20", "M6 15h4"],
};
const SHIELD = "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z";
const MARK = { pass: "m9 12 2 2 4-4", alert: "M12 8v4M12 16h.01", block: "M9.5 9.5l5 5M14.5 9.5l-5 5" } as const;
const TONE = { pass: "ok", alert: "warn", block: "risk" } as const;
const RESULT_LABEL = { pass: "통과", alert: "경고", block: "막음" } as const;

function Node({ icon, label, sub, tone }: { icon: string[]; label: string; sub: string; tone?: string }) {
  return (
    <div className={`flowNode${tone === undefined ? "" : ` ${tone}`}`}>
      <span className="flowIcon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {icon.map((d) => (
            <path key={d} d={d} />
          ))}
        </svg>
      </span>
      <strong>{label}</strong>
      <span className="flowSub">{sub}</span>
    </div>
  );
}

function Line({ delay, off = false }: { delay: number; off?: boolean }) {
  return (
    <svg className="flowLine" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
      <path d="M0 20 H100" className={off ? "flowBase off" : "flowBase"} vectorEffect="non-scaling-stroke" />
      {!off && <path d="M0 20 H100" className="beam fwd" pathLength={120} vectorEffect="non-scaling-stroke" style={{ animationDelay: `${-delay}s` }} />}
    </svg>
  );
}

export function DealFlow({ record }: { record: PurchaseRecord }) {
  const { decision } = record;
  const result = record.status === "PROCESSING" ? null : auditResult(record);
  const rules = recordRules(record);
  const paid = record.status === "SETTLED";
  const sellers = [...new Set(quotesOf(record).map((quote) => quote.sellerName.replace(" 판매 에이전트", "")))].join(" · ");
  const auditSub = result === null ? "대기" : rules.length === 0 ? "통과" : `${RESULT_LABEL[result]} · ${ruleName(rules[0])}`;
  return (
    <section className="dealFlow" aria-label="거래 흐름">
      <Node icon={ICONS.user} label="사용자" sub={`예산 ${aegisText(decision.budgetUnits)}`} />
      <Line delay={0.6} />
      <Node icon={ICONS.buyer} label="구매 에이전트" sub={decision.persona?.name ?? "구매 에이전트"} />
      <svg className="flowLine wide" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 15 Q50 4 100 15" className="flowBase" vectorEffect="non-scaling-stroke" />
        <path d="M0 25 Q50 36 100 25" className="flowBase" vectorEffect="non-scaling-stroke" />
        <path d="M0 15 Q50 4 100 15" className="beam fwd" pathLength={120} vectorEffect="non-scaling-stroke" />
        <path d="M0 25 Q50 36 100 25" className="beam back" pathLength={120} vectorEffect="non-scaling-stroke" />
      </svg>
      <Node icon={ICONS.seller} label="판매 에이전트" sub={sellers === "" ? "-" : sellers} />
      <Line delay={1.2} />
      <Node icon={[SHIELD, MARK[result ?? "pass"]]} label="감사" sub={auditSub} tone={result === null ? undefined : TONE[result]} />
      <Line delay={1.8} off={!paid} />
      <Node icon={ICONS.pay} label="결제 (체인)" sub={paid ? aegisText(decision.winner.amountUnits) : "결제 안 함"} tone={paid ? "ok" : "off"} />
    </section>
  );
}
