import Link from "next/link";
import { notFound } from "next/navigation";

import { AlertList, STAGE_LABEL } from "@/components/AlertList";
import { CandidateTables } from "@/components/DecisionView";
import { NegotiationBlock } from "@/components/Negotiation";
import { getPurchase, listAlertsForPurchase } from "@/lib/api";
import { aegisText } from "@/lib/format";
import { PRIORITY_LABEL } from "@/lib/priority-label";
import { purchaseReason, purchaseStatus, purchaseTitle, quotesOf, quoteStatus, shortTime } from "@/lib/purchase-view";
import type { AuditAlert, AuditStage } from "@/lib/types";

export const dynamic = "force-dynamic";

const STAGES: AuditStage[] = ["on-request", "before-payment", "after-payment"];

function stageBadge(stage: AuditStage, alerts: AuditAlert[], processing: boolean) {
  const found = alerts.filter((alert) => alert.stage === stage);
  if (found.some((alert) => alert.blocked)) return <span className="badge risk">차단</span>;
  if (found.length > 0) return <span className="badge warn">경고</span>;
  if (processing && stage !== "on-request") return <span className="badge">대기</span>;
  return <span className="badge ok">통과</span>;
}

export default async function PurchaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [record, alerts] = await Promise.all([getPurchase(id), listAlertsForPurchase(id)]);
  if (record === null) notFound();

  const { decision, payment } = record;
  const status = purchaseStatus(record);
  const reason = purchaseReason(record);
  const quotes = quotesOf(record);

  return (
    <div className="page tight">
      <Link className="textLink" href="/dashboard/purchases">← 전체 기록</Link>

      <div className="detailHead">
        <span className={`badge ${status.tone}`}>{status.label}</span>
        <h1>{record.prompt}</h1>
        <span className="muted">
          {shortTime(record.createdAt)} · 우선순위 {PRIORITY_LABEL[decision.priority]}
          {decision.prioritySource === "local-llm" && ` (${decision.priorityModel}이(가) 판단)`}
        </span>
      </div>

      <div className="columns">
        <div className="wide">
          <section className="panel">
            <h2>{purchaseTitle(record)}</h2>
            {reason !== null && <p>{reason}</p>}
            {record.failureReason !== null && (
              <p>
                {record.failureStage === "after-send" ? "송금 뒤에 실패했어요. 돈이 나갔을 수 있어요. " : "송금 전에 실패했어요. "}
                {record.failureReason}
              </p>
            )}
          </section>

          {quotes.length > 0 && (
            <section className="panel">
              <h2>흥정 대화</h2>
              {quotes.map((quote) => (
                <NegotiationBlock
                  key={quote.key}
                  displayName={quote.displayName}
                  sellerName={quote.sellerName}
                  askUnits={quote.askUnits}
                  turns={quote.transcript}
                  live={false}
                  status={quoteStatus(quote)}
                />
              ))}
            </section>
          )}

          <section className="panel">
            <h2>받아온 결과</h2>
            {record.resultText === null ? (
              <p className="muted">결제가 확인되지 않아 결과가 없어요</p>
            ) : (
              <pre className="resultBox">{record.resultText}</pre>
            )}
          </section>

          <CandidateTables record={record} />
        </div>

        <aside className="side">
          <section className="panel">
            <h2>결제</h2>
            <strong className="paidBig">{aegisText(decision.winner.amountUnits)}</strong>
            <dl className="facts">
              {decision.winner.listAmountUnits !== undefined && (
                <div>
                  <dt>호가</dt>
                  <dd>{aegisText(decision.winner.listAmountUnits)}</dd>
                </div>
              )}
              <div>
                <dt>예산</dt>
                <dd>{aegisText(decision.budgetUnits)}</dd>
              </div>
              <div className="stacked">
                <dt>거래번호 (tx)</dt>
                <dd className="hash">{payment?.txHash ?? "-"}</dd>
              </div>
              <div className="stacked">
                <dt>받은 주소</dt>
                <dd className="hash">{payment?.to ?? "-"}</dd>
              </div>
              <div className="stacked">
                <dt>벤치마크 스냅샷</dt>
                <dd className="hash">{decision.snapshotHash}</dd>
              </div>
            </dl>
          </section>

          <section className="panel">
            <h2>감사</h2>
            <ol className="stages">
              {STAGES.map((stage) => (
                <li key={stage}>
                  <span>{STAGE_LABEL[stage]}</span>
                  {stageBadge(stage, alerts, record.status === "PROCESSING")}
                </li>
              ))}
            </ol>
            {alerts.length > 0 && <AlertList alerts={alerts} linked={[]} compact />}
          </section>
        </aside>
      </div>
    </div>
  );
}
