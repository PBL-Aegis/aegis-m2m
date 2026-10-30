"use client";

/**
 * 채팅 화면. 보낸 문장 하나가 곧 구매 한 건이다.
 *
 * 보내면 서버가 모델을 고르고 결제까지 끝낸 뒤 결과를 돌려준다. 그래서 버튼 이름이
 * "전송 후 결제"다. 고른 근거(후보 점수·탈락 사유)는 답변 아래 접어두고, 눌러야 펼친다.
 */

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { CandidateTables, PurchaseSummary } from "@/components/DecisionView";
import { parseAegis, toAegis } from "@/lib/format";
import { PRIORITY_LABEL } from "@/lib/priority-label";
import { PRIORITIES, type PurchaseRecord } from "@/lib/types";

/**
 * "기본"은 고르는 값이 아니다. 비워 두면 요청 문장을 읽어 우선순위를 정하고,
 * 문장에 선호가 없거나 서로 부딪힐 때만 기본 비중을 쓴다.
 */
const AUTO = "";
const PRIORITY_OPTIONS = [
  { value: AUTO, label: "요청 문장으로 판단" },
  ...PRIORITIES.filter((value) => value !== "default").map((value) => ({ value, label: PRIORITY_LABEL[value] })),
];

interface Turn {
  id: number;
  prompt: string;
  record: PurchaseRecord | null;
  error: string | null;
}

export function ChatPanel() {
  const [prompt, setPrompt] = useState("");
  const [budget, setBudget] = useState("0.3");
  const [priority, setPriority] = useState<string>(AUTO);
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [open, setOpen] = useState<number | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (text === "" || busy) return;
    if (parseAegis(budget) === null) return;

    const id = Date.now();
    setTurns((prev) => [...prev, { id, prompt: text, record: null, error: null }]);
    setPrompt("");
    setBusy(true);
    try {
      const response = await fetch("/api/purchase", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt: text, budget: budget.trim(), ...(priority === AUTO ? {} : { priority }) }),
      });
      const body = (await response.json()) as PurchaseRecord | { error: string };
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id !== id
            ? turn
            : !response.ok || "error" in body
              ? { ...turn, error: "error" in body ? body.error : `요청 실패 (${response.status})` }
              : { ...turn, record: body },
        ),
      );
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "요청을 보내지 못했습니다";
      setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, error: message } : turn)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      {turns.length === 0 ? (
        <div className="chat-empty">
          <h1>무엇을 물어볼까요?</h1>
          <p className="muted">
            보내면 벤치마크 표로 모델을 고르고, 그 모델에 결제한 뒤 결과를 가져옵니다.
          </p>
        </div>
      ) : (
        <div className="chat-log">
          {turns.map((turn) => (
            <div key={turn.id} className="turn">
              <div className="bubble user">{turn.prompt}</div>

              {turn.record === null && turn.error === null && (
                <div className="bubble agent muted">모델을 고르고 결제하는 중…</div>
              )}

              {turn.error !== null && <div className="bubble agent error">{turn.error}</div>}

              {turn.record !== null && turn.record.status === "FAILED" && (
                <div className="bubble agent error">
                  결제하지 못했습니다: {turn.record.failureReason}
                </div>
              )}

              {turn.record !== null && turn.record.status === "SETTLED" && (
                <div className="bubble agent">
                  <div className="picked">
                    <b>{turn.record.decision.winner.displayName}</b> 선택 ·{" "}
                    {toAegis(turn.record.decision.winner.amountUnits)} AEGIS 결제
                    {turn.record.payment !== null && turn.record.payment.mode !== "live" && ` (${turn.record.payment.mode})`}
                  </div>
                  <pre className="result">{turn.record.resultText}</pre>
                  <button
                    type="button"
                    className="link"
                    onClick={() => setOpen(open === turn.id ? null : turn.id)}
                  >
                    {open === turn.id ? "고른 근거 접기" : "고른 근거 보기"}
                  </button>
                  {open === turn.id && (
                    <div className="evidence">
                      <PurchaseSummary record={turn.record} />
                      <CandidateTables record={turn.record} />
                      <p className="muted">
                        <Link href={`/dashboard/${turn.record.id}`}>기록 상세 보기</Link>
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <form className="composer" onSubmit={onSubmit}>
        <div className="composer-row">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              // 엔터로 보내고, 줄바꿈은 Shift+엔터. 폼에 제출을 맡겨야 입력값이 최신 상태로 읽힌다.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="무엇을 시킬지 적어주세요"
            rows={2}
          />
          <button type="submit" disabled={busy || prompt.trim() === ""}>
            {busy ? "처리 중…" : "전송 후 결제"}
          </button>
        </div>
        <div className="composer-options">
          <label>
            예산
            <input
              type="number"
              min={0}
              step={0.000001}
              value={budget}
              onChange={(event) => setBudget(event.target.value)}
            />
            <span className="muted">AEGIS</span>
          </label>
          <label>
            우선순위
            <select value={priority} onChange={(event) => setPriority(event.target.value)}>
              {PRIORITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </form>
    </div>
  );
}
