import Link from "next/link";
import { notFound } from "next/navigation";

import { AlertList, alertTone, STAGE_LABEL } from "@/components/AlertList";
import { CopyButton } from "@/components/CopyButton";
import { EvaluationCard } from "@/components/EvaluationCard";
import { CandidateTables } from "@/components/DecisionView";
import { NegotiationBlock } from "@/components/Negotiation";
import { getPurchase, listAlertsForPurchase } from "@/lib/api";
import { aegisText } from "@/lib/format";
import { PRIORITY_LABEL } from "@/lib/priority-label";
import { chainLabel, failureText, priceDate, purchaseReason, purchaseStatus, purchaseTitle, quotesOf, quoteStatus, shortHash, shortTime } from "@/lib/purchase-view";
import type { AuditAlert, AuditStage } from "@/lib/types";

export const dynamic = "force-dynamic";

const MODE_LABEL = { rule: "규칙형", llm: "LLM형", hybrid: "이중형" } as const;

const STAGES: AuditStage[] = ["on-request", "before-payment", "after-payment"];

function stageBadge(stage: AuditStage, alerts: AuditAlert[], processing: boolean) {
  const found = alerts.filter((alert) => alert.stage === stage);
  if (found.some((alert) => alert.blocked)) return <span className="badge risk">차단</span>;
  if (found.length > 0) return <span className={`badge ${alertTone(stage)}`}>경고</span>;
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
  const failure = failureText(record);
  const quotes = quotesOf(record);

  return (
    <div className="page tight">
      <Link className="textLink" href="/dashboard/purchases">← 전체 기록</Link>

      <div className="detailHead">
        <span className={`badge ${status.tone}`}>{status.label}</span>
        <h1>“{record.prompt}”</h1>
        <span className="muted">
          {shortTime(record.createdAt)} · 우선순위 {PRIORITY_LABEL[decision.priority]}
          {decision.prioritySource === "local-llm" && ` (${decision.priorityModel}이(가) 판단)`}
          {decision.persona !== undefined && ` · ${decision.persona.name}`}
          {decision.negotiationMode !== undefined && ` · ${MODE_LABEL[decision.negotiationMode]}`}
        </span>
      </div>

      <div className="columns">
        <div className="wide">
          <section className="panel">
            <h2>{purchaseTitle(record)}</h2>
            {reason !== null && <p>{reason}</p>}
            {failure !== null && <p>{failure}</p>}
            {decision.evaluation !== undefined && <EvaluationCard evaluation={decision.evaluation} />}
          </section>

          {quotes.length > 0 && (
            <section className="panel">
              <h2>흥정 대화</h2>
              <div className="deals">
                {quotes.map((quote) => (
                  <NegotiationBlock
                    key={quote.key}
                    displayName={quote.displayName}
                    sellerName={quote.sellerName}
                    askUnits={quote.askUnits}
                    turns={quote.transcript}
                    live={false}
                    status={quoteStatus(quote, record)}
                  />
                ))}
              </div>
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
              <div>
                <dt>받은 곳</dt>
                <dd>{payment === null ? "-" : decision.negotiation?.sellerName ?? shortHash(payment.to)}</dd>
              </div>
              <div>
                <dt>체인</dt>
                <dd>{payment === null ? "-" : chainLabel(payment.mode)}</dd>
              </div>
              {decision.snapshotCapturedAt !== undefined && (
                <div>
                  <dt>가격 기준일</dt>
                  <dd>{priceDate(decision.snapshotCapturedAt)}</dd>
                </div>
              )}
              <div className="centered">
                <dt>거래번호</dt>
                {payment === null ? (
                  <dd>-</dd>
                ) : (
                  <dd className="copyable">
                    <code>{shortHash(payment.txHash)}</code>
                    <CopyButton value={payment.txHash} label="거래번호 복사" />
                  </dd>
                )}
              </div>
            </dl>
            <details className="moreFacts">
              <summary>
                자세히
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5f6878" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="m6 9 6 6 6-6" />
                </svg>
              </summary>
              <dl className="facts">
                <div className="stacked">
                  <dt>구매 번호</dt>
                  <dd className="hash">{record.id}</dd>
                </div>
                {record.requestId !== undefined && (
                  <div className="stacked">
                    <dt>요청 번호</dt>
                    <dd className="hash">{record.requestId}</dd>
                  </div>
                )}
                {payment !== null && (
                  <>
                    <div className="stacked">
                      <dt>거래번호 전체</dt>
                      <dd className="hash">{payment.txHash}</dd>
                    </div>
                    <div className="stacked">
                      <dt>받은 주소</dt>
                      <dd className="hash">{payment.to}</dd>
                    </div>
                  </>
                )}
              </dl>
            </details>
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
