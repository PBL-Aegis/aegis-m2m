/**
 * 전체 기록 표. 호가·합의·아낀 금액·예산과 감사에 걸린 규칙을 한 줄에 보여준다.
 * 막은 구매는 돈이 나가지 않았으므로 합의 칸에 "결제 안 함"을 쓴다.
 */

import Link from "next/link";

import { toAegis } from "@/lib/format";
import { auditResult, purchaseStatus, recordRules, ruleName, shortTime } from "@/lib/purchase-view";
import type { PurchaseRecord } from "@/lib/types";

const AUDIT_TONE = { pass: "ok", alert: "warn", block: "risk" } as const;

export function PurchaseTable({ records }: { records: PurchaseRecord[] }) {
  if (records.length === 0) return <p className="empty">아직 기록이 없어요</p>;
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>요청</th>
            <th>구매 모델</th>
            <th className="num">호가</th>
            <th className="num">합의</th>
            <th className="num">아낀 금액</th>
            <th className="num">예산</th>
            <th>감사</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const { winner, budgetUnits } = record.decision;
            const paid = record.status === "SETTLED";
            const list = winner.listAmountUnits;
            const status = purchaseStatus(record);
            const rules = recordRules(record);
            return (
              <tr key={record.id}>
                <td className="requestCell">
                  <Link href={`/dashboard/${record.id}`} title={record.prompt}>
                    {record.prompt}
                  </Link>
                  <small>{shortTime(record.createdAt)}</small>
                </td>
                <td className="nowrap">{winner.displayName}</td>
                <td className="num">{list === undefined ? "-" : toAegis(list)}</td>
                <td className="num strong">{paid ? toAegis(winner.amountUnits) : "결제 안 함"}</td>
                <td className="num saved">{paid && list !== undefined ? toAegis(Math.max(list - winner.amountUnits, 0)) : "—"}</td>
                <td className="num">{toAegis(budgetUnits)}</td>
                <td>
                  <span className={`dotLabel ${AUDIT_TONE[auditResult(record)]}`}>{rules.length === 0 ? "통과" : rules.map(ruleName).join(" · ")}</span>
                </td>
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
