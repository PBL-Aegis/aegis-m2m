import { AlertTabs } from "@/components/AlertTabs";
import { listAlerts } from "@/lib/api";

export const dynamic = "force-dynamic";

/** 한 화면에 보여줄 최근 알림 수. */
const ALERT_LIMIT = 200;

export default async function AlertsPage() {
  const { alerts, linked } = await listAlerts(ALERT_LIMIT);
  return (
    <div className="page tight">
      <h1>이상 거래</h1>
      <AlertTabs alerts={alerts} linked={[...linked]} />
    </div>
  );
}
