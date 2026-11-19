/**
 * 이상 거래 알림 목록. 대시보드(최근 몇 건), 이상 거래 화면(전체), 구매 상세(그 거래의 알림)가 함께 쓴다.
 * 규칙이 결제를 막은 알림은 "막음", ctx.alert 로 남긴 알림은 "경고"로 보여준다.
 * 협상 깨기의 보조 알림(판매자 버티기 등)은 따로 카드를 만들지 않고 같은 구매의 협상 깨기 카드에 근거로 붙인다.
 * 카드에는 규칙 이름과 한 줄 요약만 두고, 규칙이 남긴 긴 원문은 "자세히"를 눌러야 펼친다.
 */

import Link from "next/link";

import { HOLDOUT_EXTRAS, ruleName, scenarioRule, shortReason, shortTime } from "@/lib/purchase-view";
import type { AuditAlert, AuditStage } from "@/lib/types";

export const STAGE_LABEL: Record<AuditStage, string> = {
  "on-request": "요청 직후",
  "before-payment": "송금 직전",
  "after-payment": "결제 후",
};

/** 결제 전 감사에 걸린 건은 경고여도 빨간색으로 눈에 띄게 한다. */
export function alertTone(stage: AuditStage | undefined): "risk" | "warn" {
  return stage === "on-request" || stage === "before-payment" ? "risk" : "warn";
}

function tone(alert: AuditAlert): "risk" | "warn" {
  return alert.blocked ? "risk" : alertTone(alert.stage);
}

/** 보조 알림을 같은 구매의 협상 깨기 알림 아래로 모은다. 협상 깨기 알림이 없으면 그대로 둔다. */
function group(alerts: AuditAlert[]): { alert: AuditAlert; extras: AuditAlert[] }[] {
  const holdouts = new Set(alerts.filter((alert) => alert.rule === "holdout").map((alert) => alert.purchaseId));
  const rows = alerts
    .filter((alert) => !(HOLDOUT_EXTRAS.has(alert.rule) && holdouts.has(alert.purchaseId)))
    .map((alert) => ({ alert, extras: [] as AuditAlert[] }));
  for (const extra of alerts.filter((alert) => HOLDOUT_EXTRAS.has(alert.rule) && holdouts.has(alert.purchaseId))) {
    rows.find((row) => row.alert.rule === "holdout" && row.alert.purchaseId === extra.purchaseId)?.extras.push(extra);
  }
  return rows;
}

/** 단계와 시각. 예: "결제 후 · 11월 17일 12:28". */
function when(alert: AuditAlert): string {
  return [alert.stage === undefined ? null : STAGE_LABEL[alert.stage], shortTime(alert.createdAt)].filter(Boolean).join(" · ");
}

function Title({ alert }: { alert: AuditAlert }) {
  return (
    <span className="alertTitle">
      <i className={tone(alert)} aria-hidden="true" />
      <b>{ruleName(scenarioRule(alert.rule))}</b>
      <span className={`alertKind ${tone(alert)}`}>{alert.blocked ? "막음" : "경고"}</span>
    </span>
  );
}

/** linked: 구매 기록이 있는 구매 번호. 요청 직후에 막혀 기록이 없는 알림에는 링크를 달지 않는다. */
export function AlertList({
  alerts,
  linked,
  compact = false,
  emptyText = "감지된 이상 거래가 없어요",
}: {
  alerts: AuditAlert[];
  linked: Set<string> | string[];
  compact?: boolean;
  emptyText?: string;
}) {
  if (alerts.length === 0) return <p className="empty">{emptyText}</p>;
  const rows = group(alerts);
  const hasRecord = (id: string) => (Array.isArray(linked) ? linked.includes(id) : linked.has(id));

  if (compact) {
    return (
      <div className="compactAlerts">
        {rows.map(({ alert }) => {
          const body = (
            <>
              <Title alert={alert} />
              <span className="alertShort">{shortReason(alert)}</span>
              <small>{when(alert)}</small>
            </>
          );
          return hasRecord(alert.purchaseId) ? (
            <Link className="compactAlert" key={alert.id} href={`/dashboard/${alert.purchaseId}`}>{body}</Link>
          ) : (
            <div className="compactAlert" key={alert.id}>{body}</div>
          );
        })}
      </div>
    );
  }

  return (
    <section className="alertList">
      {rows.map(({ alert, extras }) => (
        <article className="alertCard" key={alert.id}>
          <div className="alertHead">
            <Title alert={alert} />
            {hasRecord(alert.purchaseId) ? (
              <Link className="textLink" href={`/dashboard/${alert.purchaseId}`}>거래 보기 →</Link>
            ) : (
              <small>기록 없음</small>
            )}
          </div>
          <p className="alertShort">{shortReason(alert)}</p>
          <details className="alertMore">
            <summary>
              <span>{when(alert)}</span>
              <b>자세히</b>
            </summary>
            <p>{alert.message}</p>
            {extras.map((extra) => (
              <p key={extra.id}>{extra.message}</p>
            ))}
          </details>
        </article>
      ))}
    </section>
  );
}
