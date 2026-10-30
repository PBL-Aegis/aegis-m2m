import { notFound } from "next/navigation";

import { AlertList } from "@/components/AlertList";
import { CandidateTables, PurchaseSummary } from "@/components/DecisionView";
import { getPurchase, listAlertsForPurchase } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PurchaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [record, alerts] = await Promise.all([getPurchase(id), listAlertsForPurchase(id)]);
  if (record === null) notFound();

  return (
    <>
      <h1>구매 상세</h1>
      <p className="muted">
        구매 번호 <code>{record.id}</code> · {new Date(record.createdAt).toLocaleString("ko-KR", { hour12: false })}
      </p>

      <h2>요청 내용</h2>
      <pre className="result">{record.prompt}</pre>

      {alerts.length > 0 && (
        <>
          <h2>이상 거래 알림</h2>
          <AlertList alerts={alerts} linked={new Set()} compact />
        </>
      )}

      <h2>요약</h2>
      <PurchaseSummary record={record} />
      <CandidateTables record={record} />
    </>
  );
}
