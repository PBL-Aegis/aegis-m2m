import { AlertList } from "@/components/AlertList";
import { listAlerts } from "@/lib/api";

export const dynamic = "force-dynamic";

/** 한 화면에 보여줄 최근 알림 수. */
const ALERT_LIMIT = 200;

// PBL-aegis 감사 대시보드의 "감사 경고" 화면과 같은 구성.
export default async function AlertsPage() {
  const { alerts, linked } = await listAlerts(ALERT_LIMIT);
  return (
    <>
      <div className="pageHead">
        <p className="eyebrow">이상 거래</p>
        <h1>감사 규칙이 막거나 경고한 거래</h1>
      </div>
      <AlertList alerts={alerts} linked={linked} />
    </>
  );
}
