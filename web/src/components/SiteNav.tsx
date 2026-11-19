"use client";

/**
 * 왼쪽 아이콘 메뉴. 아이콘에 마우스를 올리거나 키보드로 고르면 이름이 옆에 뜬다.
 * 맨 아래 흐린 재생 아이콘은 시연용이다. 누르면 장면 목록이 뜨고, 고르면 채팅 입력창을 채운다.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { DEMO_SCENARIOS } from "@/lib/demo-scenarios";

const ITEMS = [
  { href: "/", label: "새 요청", paths: ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"] },
  { href: "/dashboard", label: "대시보드", paths: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"] },
  { href: "/dashboard/purchases", label: "전체 기록", paths: ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"] },
  { href: "/dashboard/alerts", label: "이상 거래", paths: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "M12 8v4", "M12 16h.01"] },
];

/** 지금 화면에 맞는 메뉴. 구매 상세는 전체 기록에서 들어가므로 전체 기록에 불을 켠다. */
function activeHref(pathname: string): string {
  if (pathname === "/") return "/";
  if (pathname.startsWith("/dashboard/alerts")) return "/dashboard/alerts";
  if (pathname === "/dashboard") return "/dashboard";
  return "/dashboard/purchases";
}

export function SiteNav() {
  const active = activeHref(usePathname());
  const [demoOpen, setDemoOpen] = useState(false);
  return (
    <nav className="rail" aria-label="주 메뉴">
      <Link className="railLogo" href="/" aria-label="agent-M2M">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 5h2l2 11h10l2-8H7" />
          <circle cx="9.5" cy="20" r="1" />
          <circle cx="17" cy="20" r="1" />
        </svg>
        <span className="railTip" role="tooltip">agent-M2M</span>
      </Link>
      {ITEMS.map((item) => (
        <Link key={item.href} className="railItem" href={item.href} aria-label={item.label} aria-current={item.href === active ? "page" : undefined}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {item.paths.map((d) => (
              <path key={d} d={d} />
            ))}
          </svg>
          <span className="railTip" role="tooltip">{item.label}</span>
        </Link>
      ))}
      <div className="railDemo">
        <button type="button" className="railDemoButton" aria-label="시연 장면" aria-expanded={demoOpen} onClick={() => setDemoOpen(!demoOpen)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M7 4v16l13-8z" />
          </svg>
        </button>
        {demoOpen && (
          <div className="demoMenu" role="menu">
            {DEMO_SCENARIOS.map((scenario) => (
              <Link key={scenario.id} role="menuitem" href={`/?scenario=${scenario.id}`} onClick={() => setDemoOpen(false)}>
                <b>{scenario.label}</b>
                <span>{scenario.hint}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </nav>
  );
}
