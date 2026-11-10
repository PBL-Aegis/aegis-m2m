"use client";

/** 이상 거래 화면. 경고와 차단을 탭으로 나눠 본다. */

import { useState } from "react";

import { AlertList } from "@/components/AlertList";
import type { AuditAlert } from "@/lib/types";

const TABS: { id: string; label: string; emptyText: string; match: (alert: AuditAlert) => boolean }[] = [
  { id: "all", label: "전체", emptyText: "감지된 이상 거래가 없어요", match: () => true },
  { id: "warn", label: "경고", emptyText: "경고한 거래가 없어요", match: (alert) => !alert.blocked },
  { id: "blocked", label: "차단", emptyText: "차단된 거래가 없어요", match: (alert) => alert.blocked === true },
];

export function AlertTabs({ alerts, linked }: { alerts: AuditAlert[]; linked: string[] }) {
  const [tab, setTab] = useState(TABS[0]);
  return (
    <>
      <div className="tabs">
        {TABS.map((item) => (
          <button key={item.id} type="button" aria-pressed={item.id === tab.id} onClick={() => setTab(item)}>
            {item.label}
          </button>
        ))}
      </div>
      <AlertList alerts={alerts.filter(tab.match)} linked={linked} emptyText={tab.emptyText} />
    </>
  );
}
