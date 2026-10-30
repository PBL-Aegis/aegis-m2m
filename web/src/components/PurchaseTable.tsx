/**
 * 구매 기록 표. 대시보드(최근 몇 건)와 전체 기록 화면이 같은 모양으로 보여주기 위해 공유한다.
 */

import Link from "next/link";

import { aegisText } from "@/lib/format";
import { PRIORITY_LABEL } from "@/lib/priority-label";
import type { PurchaseRecord } from "@/lib/types";

function when(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { hour12: false });
}

export function PurchaseTable({ records }: { records: PurchaseRecord[] }) {
  if (records.length === 0) return <p className="empty">아직 기록이 없습니다.</p>;
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>요청·Purchase ID</th>
            <th>처리 상태</th>
            <th>결제 금액</th>
            <th>선택된 모델</th>
            <th>결제 모드</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <td className="requestCell">
                <Link href={`/dashboard/${record.id}`} title={record.prompt}>
                  {record.prompt}
                </Link>
                <small>
                  {record.id.slice(0, 8)} · {when(record.createdAt)}
                </small>
              </td>
              <td>
                <span className={`badge ${record.status === "SETTLED" ? "ok" : "risk"}`}>{record.status}</span>
              </td>
              <td>
                <strong className="amount">{aegisText(record.decision.winner.amountUnits)}</strong>
              </td>
              <td>
                {record.decision.winner.displayName}
                <small>{PRIORITY_LABEL[record.decision.priority]}</small>
              </td>
              <td>{record.payment?.mode ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
