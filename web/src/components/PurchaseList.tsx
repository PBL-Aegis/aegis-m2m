"use client";

/** 전체 기록 화면. 상태 탭으로 기록을 거른다. */

import { useState } from "react";

import { PurchaseTable } from "@/components/PurchaseTable";
import { isOverBudget } from "@/lib/purchase-view";
import type { PurchaseRecord } from "@/lib/types";

const TABS: { id: string; label: string; match: (record: PurchaseRecord) => boolean }[] = [
  { id: "all", label: "전체", match: () => true },
  { id: "settled", label: "정산 완료", match: (record) => record.status === "SETTLED" && !isOverBudget(record) },
  { id: "over", label: "예산 초과", match: (record) => record.status === "SETTLED" && isOverBudget(record) },
  { id: "blocked", label: "차단", match: (record) => record.blockedRule !== undefined },
  { id: "failed", label: "결제 실패", match: (record) => record.status === "FAILED" && record.blockedRule === undefined },
];

export function PurchaseList({ records }: { records: PurchaseRecord[] }) {
  const [tab, setTab] = useState(TABS[0]);
  const shown = records.filter(tab.match);
  return (
    <>
      <div className="tabs">
        {TABS.map((item) => (
          <button key={item.id} type="button" aria-pressed={item.id === tab.id} onClick={() => setTab(item)}>
            {item.label}
          </button>
        ))}
      </div>
      <section className="panel">
        <PurchaseTable records={shown} detailed />
      </section>
    </>
  );
}
