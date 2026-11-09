/**
 * 페르소나 관점의 거래 평가. 이 구매가 목표에 맞았는지와 그 이유를 서버가 쓴 문장 그대로 보여준다.
 */

import { VERDICT_VIEW } from "@/lib/purchase-view";
import type { Evaluation } from "@/lib/types";

export function EvaluationCard({ evaluation }: { evaluation: Evaluation }) {
  const verdict = VERDICT_VIEW[evaluation.verdict];
  return (
    <section className={`evaluation ${verdict.tone}`} aria-label={evaluation.headline}>
      <div className="evaluationHead">
        <strong>{evaluation.personaName}</strong>
        <span className={`badge ${verdict.tone}`}>{verdict.label}</span>
      </div>
      <p className="evaluationGoal">{evaluation.goal}</p>
      <ul>
        {evaluation.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
