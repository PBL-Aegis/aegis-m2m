/**
 * 비교 모델을 표로 정하기 전의 옛 기록에 남은 후보 점수표. 기록 상세 화면이 쓴다.
 */

import { toAegis } from "@/lib/format";
import type { PurchaseRecord } from "@/lib/types";

function fmt(value: number): string {
  return value.toLocaleString("ko-KR");
}

/** 새 기록은 출력 속도(토큰/초), 옛 기록은 끝까지 걸린 시간(초)을 보여준다. */
function speed(candidate: { outputTokensPerSecond?: number; completionMs?: number }): string {
  if (candidate.outputTokensPerSecond !== undefined) return `${Math.round(candidate.outputTokensPerSecond)} 토큰/초`;
  if (candidate.completionMs !== undefined) return `${Math.round(candidate.completionMs / 1000)}초`;
  return "-";
}

function score(value: number): string {
  return value.toFixed(2);
}

/** 옛 기록(AA·Arena 시절)에만 있는 점수도 깨지지 않게 보여준다. */
function maybe(value: number | undefined): string {
  return value === undefined ? "-" : score(value);
}

/** 후보 점수표 + 성능 점수 내역 + 탈락 후보표. */
export function CandidateTables({ record }: { record: PurchaseRecord }) {
  const { decision } = record;
  // 비교 모델을 표로 정한 뒤의 기록은 점수로 고르지 않는다.
  if (decision.quotes !== undefined) return null;
  const sources = decision.performanceSources;
  return (
    <section className="panel">
      <h2>후보 점수</h2>
      <p className="muted">총점 = 가격·속도·성능 점수(각 100점 만점)를 가중치로 합친 값입니다.</p>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th className="num">순위</th>
              <th>모델</th>
              <th className="num">금액 (AEGIS)</th>
              <th className="num">속도</th>
              <th className="num">가격 점수</th>
              <th className="num">속도 점수</th>
              <th className="num">성능 점수</th>
              <th className="num">총점</th>
            </tr>
          </thead>
          <tbody>
            {decision.candidates.map((candidate) => (
              <tr key={candidate.key} className={candidate.rank === 1 ? "winner" : undefined}>
                <td className="num">{candidate.rank}</td>
                <td>{candidate.displayName}</td>
                <td className="num">{toAegis(candidate.amountUnits)}</td>
                <td className="num">{speed(candidate)}</td>
                <td className="num">{score(candidate.priceScore)}</td>
                <td className="num">{maybe(candidate.timeScore)}</td>
                <td className="num">{score(candidate.intelligenceScore)}</td>
                <td className="num">{score(candidate.totalScore)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {decision.candidates.every((candidate) => candidate.eci !== undefined) ? (
        <>
          <h2>점수 근거 · 세 출처</h2>
          <p className="muted">
            성능은 Epoch Capabilities Index(여러 벤치마크를 난이도까지 고려해 합친 지수), 가격은 OpenRouter 판매 단가,
            속도는 Artificial Analysis가 잰 출력 속도(1초에 내보내는 토큰 수)를 생각 단계별로 평균낸 값입니다. 세 점수 모두
            후보 중 가장 나쁜 값을 0점, 가장 좋은 값을 100점으로 폈고, 가격과 속도는 몇 배 차이인지가 반영되도록 로그로
            폈습니다.
          </p>
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>모델</th>
                  <th className="num">ECI</th>
                  <th className="num">95% 신뢰구간</th>
                  <th className="num">성능 점수</th>
                  <th>속도를 잰 AA 항목</th>
                </tr>
              </thead>
              <tbody>
                {decision.candidates.map((candidate) => (
                  <tr key={candidate.key}>
                    <td>{candidate.displayName}</td>
                    <td className="num">{candidate.eci}</td>
                    <td className="num">
                      {candidate.eciCiLow}~{candidate.eciCiHigh}
                    </td>
                    <td className="num">{score(candidate.intelligenceScore)}</td>
                    <td>{candidate.aaModelNames?.join(", ") ?? candidate.aaModelName ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <h2>성능 점수 내역 · 두 출처</h2>
          {sources?.arena === undefined ? (
            <p className="muted">이 기록은 두 출처를 합치기 전에 만들어져 AA 지능 지수 하나로 계산했습니다.</p>
          ) : (
            <>
              <p className="muted">
                성능 점수 = (AA 점수 + Arena 점수) ÷ 2. 원래 값을 후보 중 최고 대비 100점 만점으로 바꿨습니다
                {sources.arenaPublishDate != null && <> · Arena 발행일 {sources.arenaPublishDate}</>}.
              </p>
              <div className="tableWrap">
                <table>
                  <thead>
                    <tr>
                      <th>모델</th>
                      <th className="num">AA 지능 지수</th>
                      <th className="num">AA 점수</th>
                      <th className="num">Arena Elo</th>
                      <th className="num">Arena 점수</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decision.candidates.map((candidate) => (
                      <tr key={candidate.key}>
                        <td>{candidate.displayName}</td>
                        <td className="num">{candidate.intelligenceIndex ?? "-"}</td>
                        <td className="num">{maybe(candidate.aaScore)}</td>
                        <td className="num">
                          {candidate.arenaRating === undefined ? "-" : fmt(Math.round(candidate.arenaRating))}
                        </td>
                        <td className="num">{maybe(candidate.arenaScore)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}

      <h2>탈락 후보</h2>
      {decision.rejected.length === 0 ? (
        <p className="muted">필터에서 떨어진 후보가 없습니다.</p>
      ) : (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>모델</th>
                <th className="num">금액 (AEGIS)</th>
                <th>탈락 사유</th>
              </tr>
            </thead>
            <tbody>
              {decision.rejected.map((item) => (
                <tr key={item.key}>
                  <td>{item.displayName}</td>
                  <td className="num">{toAegis(item.amountUnits)}</td>
                  <td>{item.reasons.join(" / ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
