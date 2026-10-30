import Link from "next/link";

import { AlertList } from "@/components/AlertList";
import { PurchaseTable } from "@/components/PurchaseTable";
import { aegisText } from "@/lib/format";
import { buyerBalance, countAlerts, listAlerts, listPurchases } from "@/lib/api";

export const dynamic = "force-dynamic";

// 화면 구성은 PBL-aegis 감사 대시보드의 개요 화면(요약 4칸 + 최근 기록 + 이상 거래)을 따른다.

/** 첫 화면 표에 보여줄 최근 기록 수. 나머지는 전체 기록 화면에서 본다. */
const RECENT_COUNT = 6;
/** 오른쪽 패널에 보여줄 최근 알림 수. */
const RECENT_ALERTS = 4;

export default async function DashboardPage() {
  const [records, balance, { alerts, linked }, counts] = await Promise.all([
    listPurchases(),
    buyerBalance(),
    listAlerts(RECENT_ALERTS),
    countAlerts(),
  ]);
  const settled = records.filter((record) => record.status === "SETTLED");
  const spentUnits = settled.reduce((sum, record) => sum + record.decision.winner.amountUnits, 0);

  return (
    <div className="auditMain">
      <section className="auditMetrics" aria-label="구매 요약">
        <article>
          <span>구매 에이전트 토큰 잔액</span>
          <strong>{balance.units === null ? "—" : aegisText(balance.units)}</strong>
          {balance.units === null && <small>{balance.status}</small>}
        </article>
        <article>
          <span>정산 완료 거래</span>
          <strong>{settled.length}</strong>
          <small>전체 요청 {records.length}건 중</small>
        </article>
        <article>
          <span>결제 금액 합계</span>
          <strong>{aegisText(spentUnits)}</strong>
          <small>정산 완료 거래 기준</small>
        </article>
        <article>
          <span>이상 거래</span>
          <strong className={counts.blocked > 0 ? "riskText" : ""}>
            {counts.blocked} 차단 <b>·</b> {counts.warnings} 경고
          </strong>
        </article>
      </section>

      <section className="auditLayout">
        <article className="panel">
          <div className="sectionHead">
            <div>
              <p className="eyebrow">RECENT TRANSACTIONS</p>
              <h2>최근 요청·결제 기록</h2>
            </div>
            <Link href="/dashboard/purchases">전체 기록 →</Link>
          </div>
          <PurchaseTable records={records.slice(0, RECENT_COUNT)} />
        </article>

        <aside className="panel">
          <div className="sectionHead">
            <div>
              <p className="eyebrow">ANOMALY ALERTS</p>
              <h2>이상 거래 감지</h2>
            </div>
            <Link href="/dashboard/alerts">전체 →</Link>
          </div>
          <AlertList alerts={alerts} linked={linked} compact />
        </aside>
      </section>
    </div>
  );
}
