import Link from "next/link";

import { AuditRing } from "@/components/AuditRing";
import { BalanceRoll } from "@/components/BalanceRoll";
import { aegisText, toAegis } from "@/lib/format";
import { buyerBalance, listPurchases } from "@/lib/api";
import { auditResult, shortTime, type AuditResult } from "@/lib/purchase-view";

export const dynamic = "force-dynamic";

/** 최근 결제에 보여줄 수. 나머지는 전체 기록 화면에서 본다. */
const RECENT_COUNT = 6;

const DOT: Record<AuditResult, string> = { pass: "var(--green)", alert: "var(--amber)", block: "var(--red)" };
const RESULT_LABEL: Record<AuditResult, string> = { pass: "통과", alert: "경고", block: "막음" };

export default async function DashboardPage() {
  const [records, balance] = await Promise.all([listPurchases(), buyerBalance()]);
  const settled = records.filter((record) => record.status === "SETTLED");
  const spentUnits = settled.reduce((sum, record) => sum + record.decision.winner.amountUnits, 0);
  // 협상이 생기기 전 기록에는 호가가 없어 아낀 금액 계산에서 뺀다.
  const negotiated = settled.filter((record) => record.decision.winner.listAmountUnits !== undefined);
  const savedUnits = negotiated.reduce((sum, record) => sum + (record.decision.winner.listAmountUnits ?? 0) - record.decision.winner.amountUnits, 0);
  const counts: Record<AuditResult, number> = { pass: 0, alert: 0, block: 0 };
  for (const record of records) {
    if (record.status !== "PROCESSING") counts[auditResult(record)] += 1;
  }
  // 막은 구매가 보내려던 금액의 합. 감사가 지킨 돈이다.
  const guardedUnits = records.filter((record) => record.blockedRule !== undefined).reduce((sum, record) => sum + record.decision.winner.amountUnits, 0);

  return (
    <div className="page dashboard">
      <h1>대시보드</h1>

      <section className="balance" aria-label="구매 에이전트 잔액">
        <span>구매 에이전트 잔액</span>
        {balance.units === null ? <strong className="balanceValue">—</strong> : <BalanceRoll units={balance.units} />}
        <small>{balance.units === null ? balance.status : "로컬 체인에서 조회"}</small>
      </section>

      <section className="metrics two" aria-label="결제 요약">
        <article>
          <span>결제 합계</span>
          <strong>{aegisText(spentUnits)}</strong>
          <small>정산 {settled.length}건</small>
        </article>
        <article>
          <span>협상으로 아낀 금액</span>
          <strong className="saved">{aegisText(savedUnits)}</strong>
          <small>호가 대비</small>
        </article>
      </section>

      <div className="dashGrid">
        <section className="card recent">
          <div className="sectionHead">
            <h2>최근 결제</h2>
            <Link className="textLink" href="/dashboard/purchases">전체 기록 →</Link>
          </div>
          {settled.length === 0 ? (
            <p className="empty">아직 결제가 없어요</p>
          ) : (
            <ul className="recentList">
              {settled.slice(0, RECENT_COUNT).map((record) => {
                const result = auditResult(record);
                return (
                  <li key={record.id}>
                    <Link href={`/dashboard/${record.id}`}>
                      <i role="img" style={{ background: DOT[result] }} aria-label={RESULT_LABEL[result]} />
                      <span className="recentText">
                        <b>{record.prompt}</b>
                        <small>
                          {shortTime(record.createdAt)} · {record.decision.winner.displayName}
                        </small>
                      </span>
                      <span className="num">{toAegis(record.decision.winner.amountUnits)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="card">
          <div className="sectionHead">
            <h2>감사 결과</h2>
            <Link className="textLink" href="/dashboard/alerts">이상 거래 →</Link>
          </div>
          <div className="ringWrap">
            <AuditRing counts={counts} size={148} />
          </div>
          <div className="guarded">
            <span>막아서 지킨 금액</span>
            <strong>{aegisText(guardedUnits)}</strong>
          </div>
        </section>
      </div>
    </div>
  );
}
