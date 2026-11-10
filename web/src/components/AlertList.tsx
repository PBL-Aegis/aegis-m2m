/**
 * 이상 거래 알림 목록. 대시보드(최근 몇 건), 이상 거래 화면(전체), 구매 상세(그 거래의 알림)가 함께 쓴다.
 * 규칙이 결제를 막은 알림은 "차단", ctx.alert 로 남긴 알림은 "경고"로 보여준다.
 */

import Link from "next/link";

import { shortTime } from "@/lib/purchase-view";
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

function Badge({ alert }: { alert: AuditAlert }) {
  return alert.blocked ? <span className="badge risk">차단</span> : <span className={`badge ${alertTone(alert.stage)}`}>경고</span>;
}

function Meta({ alert }: { alert: AuditAlert }) {
  return (
    <small>
      {alert.rule}
      {alert.stage !== undefined && <> · {STAGE_LABEL[alert.stage]}</>}
      {alert.userId !== null && <> · {alert.userId}</>} · {shortTime(alert.createdAt)}
    </small>
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
  const hasRecord = (id: string) => (Array.isArray(linked) ? linked.includes(id) : linked.has(id));

  if (compact) {
    return (
      <div className="compactAlerts">
        {alerts.map((alert) =>
          hasRecord(alert.purchaseId) ? (
            <Link className="compactAlert" key={alert.id} href={`/dashboard/${alert.purchaseId}`}>
              <Badge alert={alert} />
              <b>{alert.message}</b>
              <Meta alert={alert} />
            </Link>
          ) : (
            <div className="compactAlert" key={alert.id}>
              <Badge alert={alert} />
              <b>{alert.message}</b>
              <Meta alert={alert} />
            </div>
          ),
        )}
      </div>
    );
  }

  return (
    <section className="alertList">
      {alerts.map((alert) => (
        <article className="alertRow" key={alert.id}>
          <div>
            <Badge alert={alert} />
            <h2>{alert.message}</h2>
            <Meta alert={alert} />
            {alert.requestId !== undefined && (
              <small>
                요청 번호 <code>{alert.requestId}</code>
              </small>
            )}
          </div>
          {hasRecord(alert.purchaseId) ? (
            <Link className="textLink" href={`/dashboard/${alert.purchaseId}`}>거래 보기 →</Link>
          ) : (
            <small>기록 없음</small>
          )}
        </article>
      ))}
    </section>
  );
}
