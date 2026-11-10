"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function SiteNav() {
  const pathname = usePathname();
  const onAlerts = pathname.startsWith("/dashboard/alerts");
  const current = (active: boolean) => (active ? "page" : undefined);
  return (
    <nav aria-label="주 메뉴">
      <Link href="/" aria-current={current(pathname === "/")}>새 요청</Link>
      <Link href="/dashboard" aria-current={current(pathname.startsWith("/dashboard") && !onAlerts)}>대시보드</Link>
      <Link href="/dashboard/alerts" aria-current={current(onAlerts)}>이상 거래</Link>
    </nav>
  );
}
