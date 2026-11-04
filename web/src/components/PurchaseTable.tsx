/**
 * 구매 기록 표. 대시보드(최근 몇 건)와 전체 기록 화면이 같은 모양으로 보여주기 위해 공유한다.
 */

import Link from "next/link";

import { toAegis } from "@/lib/format";
import { PRIORITY_LABEL } from "@/lib/priority-label";
import { purchaseStatus, shortTime } from "@/lib/purchase-view";
import type { PurchaseRecord } from "@/lib/types";

export function PurchaseTable({ records, detailed = false }: { records: PurchaseRecord[]; detailed?: boolean }) {
  if (records.length === 0) return <p className="empty">아직 기록이 없어요</p>;
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>요청</th>
            <th>구매 모델</th>
            {detailed ? (
              <>
                <th className="num">호가 (AEGIS)</th>
                <th className="num">합의 (AEGIS)</th>
                <th className="num">예산 (AEGIS)</th>
              </>
            ) : (
              <th className="num">호가 → 합의 (AEGIS)</th>
            )}
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const { winner, priority, budgetUnits } = record.decision;
            const list = winner.listAmountUnits === undefined ? "-" : toAegis(winner.listAmountUnits);
            const status = purchaseStatus(record);
            return (
              <tr key={record.id}>
                <td className="requestCell">
                  <Link href={`/dashboard/${record.id}`} title={record.prompt}>
                    {record.prompt}
                  </Link>
                  <small>
                    {shortTime(record.createdAt)} · {PRIORITY_LABEL[priority]}
                  </small>
                </td>
                <td className="nowrap">{winner.displayName}</td>
                {detailed ? (
                  <>
                    <td className="num">{list}</td>
                    <td className="num strong">{toAegis(winner.amountUnits)}</td>
                    <td className="num">{toAegis(budgetUnits)}</td>
                  </>
                ) : (
                  <td className="num nowrap">
                    {list} → {toAegis(winner.amountUnits)}
                  </td>
                )}
                <td>
                  <span className={`badge ${status.tone}`}>{status.label}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
