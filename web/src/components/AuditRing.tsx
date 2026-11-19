/**
 * 감사 결과 원형 게이지. 통과·경고·막음 구간이 끝이 둥근 고리로 나뉘고, 화면이 열리면 차례로 차오른다.
 * 대시보드와 이상 거래 화면이 함께 쓴다.
 */

import type { AuditResult } from "@/lib/purchase-view";

const SEGMENTS: { result: AuditResult; label: string; color: string }[] = [
  { result: "pass", label: "통과", color: "#2f9e6f" },
  { result: "alert", label: "경고", color: "#e0913f" },
  { result: "block", label: "막음", color: "#d64553" },
];

/** 둥근 끝이 이웃 구간에 닿지 않게 남기는 틈(둘레 100 기준). */
const GAP = 5.4;

export function AuditRing({ counts, size }: { counts: Record<AuditResult, number>; size: number }) {
  const total = counts.pass + counts.alert + counts.block;
  let start = 0;
  const arcs = SEGMENTS.map((segment, index) => {
    const share = total === 0 ? 0 : (counts[segment.result] / total) * 100;
    const arc = { ...segment, index, length: Math.max(share - GAP, 0), offset: -(start + GAP / 2) };
    start += share;
    return arc;
  });
  return (
    <div className="auditRing">
      <div className="ring" style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="42" className="ringTrack" />
          {arcs
            .filter((arc) => arc.length > 0)
            .map((arc) => (
              <circle
                key={arc.result}
                cx="50"
                cy="50"
                r="42"
                pathLength={100}
                className="ringArc"
                stroke={arc.color}
                strokeDasharray={`${arc.length} 100`}
                strokeDashoffset={arc.offset}
                style={{ animationDelay: `${arc.index * 0.15}s` }}
              />
            ))}
        </svg>
        <div className="ringCenter">
          <strong>{total}</strong>
          <span>감사한 요청</span>
        </div>
      </div>
      <ul className="ringLegend">
        {SEGMENTS.map((segment) => (
          <li key={segment.result}>
            <span>
              <i style={{ background: segment.color }} />
              {segment.label}
            </span>
            <strong>{counts[segment.result]}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
