/**
 * 이상 거래 알림 목록. 대시보드(최근 몇 건), 이상 거래 화면(전체), 구매 상세(그 거래의 알림)가 함께 쓴다.
 * 규칙이 결제를 막은 알림은 "차단", ctx.alert 로 남긴 알림은 "경고"로 보여준다.
 */

import Link from "next/link";

import type { AuditAlert, AuditStage } from "@/lib/types";

const STAGE_LABEL: Record<AuditStage, string> = {
  "on-request": "요청 직후",
  "before-payment": "송금 직전",
  "after-payment": "결제 후",
};

function when(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { hour12: false });
}

function Badge({ alert }: { alert: AuditAlert }) {
  return alert.blocked ? <span className="badge risk">차단</span> : <span className="badge warn">경고</span>;
}

function Meta({ alert }: { alert: AuditAlert }) {
  return (
    <small>
      {alert.rule}
      {alert.stage !== undefined && <> · {STAGE_LABEL[alert.stage]}</>}
      {alert.userId !== null && <> · {alert.userId}</>} · {when(alert.createdAt)}
    </small>
  );
}

/** linked: 구매 기록이 있는 구매 번호. 요청 직후에 막혀 기록이 없는 알림에는 링크를 달지 않는다. */
export function AlertList({
  alerts,
  linked,
  compact = false,
}: {
  alerts: AuditAlert[];
  linked: Set<string>;
  compact?: boolean;
}) {
  if (alerts.length === 0) {
    return (
      <div className="clearState">
        <span aria-hidden="true">✓</span>
        <strong>감지된 이상 거래 없음</strong>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="compactAlerts">
        {alerts.map((alert) => (
          <div key={alert.id}>
            <Badge alert={alert} />
            <span>
              {linked.has(alert.purchaseId) ? (
                <Link href={`/dashboard/${alert.purchaseId}`}>{alert.message}</Link>
              ) : (
                <b>{alert.message}</b>
              )}
              <Meta alert={alert} />
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <section className="alertList">
      {alerts.map((alert) => (
        <article className="panel alert" key={alert.id}>
          <Badge alert={alert} />
          <div>
            <h2>{alert.message}</h2>
            <Meta alert={alert} />
            {alert.requestId !== undefined && (
              <small>
                요청 번호 <code>{alert.requestId}</code>
              </small>
            )}
          </div>
          {linked.has(alert.purchaseId) ? (
            <Link href={`/dashboard/${alert.purchaseId}`}>거래 보기 →</Link>
          ) : (
            <small>기록 없음</small>
          )}
        </article>
      ))}
    </section>
  );
}
