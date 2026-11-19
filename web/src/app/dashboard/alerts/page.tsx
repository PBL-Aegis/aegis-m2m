import { AlertTabs } from "@/components/AlertTabs";
import { AuditRing } from "@/components/AuditRing";
import { listAlerts, listPurchases } from "@/lib/api";
import { aegisText } from "@/lib/format";
import { auditResult, recordRules, ruleName, type AuditResult } from "@/lib/purchase-view";

export const dynamic = "force-dynamic";

/** 한 화면에 보여줄 최근 알림 수. */
const ALERT_LIMIT = 200;

/** 시나리오 감사 규칙. 걸린 요청이 없어도 무엇을 잡는지 보이게 늘 보여 준다. */
const RULES: { rule: string; blocks: boolean; text: string }[] = [
  { rule: "intent-swap", blocks: true, text: "요청 내용에 숨긴 문장이 Gemma의 등급 판단을 바꾸면 송금 직전에 멈춥니다." },
  { rule: "holdout", blocks: true, text: "판매자가 값을 안 내려 협상이 깨지고 예산을 넘겨 사게 되면 막습니다. 같은 값을 버틴 기록과 자주 버티는 판매자인지도 함께 남깁니다." },
  { rule: "seller-collusion", blocks: false, text: "최근 여러 건에서 판매자들이 함께 덜 깎아 주면 결제 후 경고합니다." },
  { rule: "persona-gap", blocks: false, text: "품질형으로 산 값이 최저가형으로 다시 계산한 값보다 5% 넘게 비싸면 경고합니다." },
];

export default async function AlertsPage() {
  const [{ alerts, linked }, records] = await Promise.all([listAlerts(ALERT_LIMIT), listPurchases()]);
  const done = records.filter((record) => record.status !== "PROCESSING");
  const counts: Record<AuditResult, number> = { pass: 0, alert: 0, block: 0 };
  for (const record of done) counts[auditResult(record)] += 1;
  const guardedUnits = done.filter((record) => record.blockedRule !== undefined).reduce((sum, record) => sum + record.decision.winner.amountUnits, 0);
  const hits = (rule: string) => done.filter((record) => recordRules(record).includes(rule)).length;

  return (
    <div className="page tight">
      <h1>이상 거래</h1>
      <section className="auditSummary">
        <div className="auditSummarySide">
          <AuditRing counts={counts} size={132} />
          <div className="guarded stacked">
            <span>막아서 지킨 금액</span>
            <strong>{aegisText(guardedUnits)}</strong>
            <small>막은 {counts.block}건이 보내려던 금액의 합</small>
          </div>
        </div>
        <div className="ruleTable">
          <h2>감사 규칙</h2>
          {RULES.map((item) => (
            <div className="ruleRow" key={item.rule}>
              <strong>{ruleName(item.rule)}</strong>
              <span className={`dotLabel ${item.blocks ? "risk" : "warn"}`}>{item.blocks ? "막음" : "경고"}</span>
              <span className="ruleText">{item.text}</span>
              <strong className="num">{hits(item.rule)}</strong>
            </div>
          ))}
        </div>
      </section>
      <AlertTabs alerts={alerts} linked={[...linked]} />
    </div>
  );
}
