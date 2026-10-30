import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SiteNav } from "@/components/SiteNav";
import { paymentMode } from "@/lib/api";

import "./globals.css";

// 결제 모드는 요청 시점의 환경변수로 정해지므로 빌드 때 고정하지 않는다.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "agent-M2M",
  description: "AI 구매 에이전트가 벤치마크 표로 모델을 고르고 AEGIS 토큰으로 결제하는 데모",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const mode = await paymentMode();
  return (
    <html lang="ko">
      <body>
        <header className="site">
          <div className="inner">
            <span className="brand">
              <span className="brandMark">M2M</span>
              agent-M2M
            </span>
            <div className="right">
              <SiteNav />
              <span
                className={`mode${mode === "live" ? " live" : ""}`}
                title={mode === "live" ? "실제 AEGIS 토큰이 전송됩니다" : "이 컴퓨터의 로컬 체인으로 전송합니다"}
              >
                {mode === "live" ? "Live" : "Local"}
              </span>
            </div>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
