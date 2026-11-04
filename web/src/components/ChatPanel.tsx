"use client";

/**
 * 채팅 화면. 보낸 문장 하나가 곧 구매 한 건이다.
 *
 * 서버가 흥정 진행을 한 줄씩 바로 보내고(/api/purchase/stream), 여기서 그 대화를 읽을 수 있는 속도로 풀어 보여준다.
 * 끝나면 어디서 왜 샀는지와 받아온 결과를 보여주고, 끝난 흥정은 접어 둔다.
 */

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { BuyerAvatar, NegotiationBlock } from "@/components/Negotiation";
import { aegisText, parseAegis } from "@/lib/format";
import { dealStatus, endsDeal, isOverBudget, purchaseReason, purchaseTitle, quotesOf, quoteStatus } from "@/lib/purchase-view";
import type { NegotiationTurn, Priority, PurchaseRecord, PurchaseStreamEvent, StreamModel } from "@/lib/types";

/** 흥정 말풍선 하나를 보여주는 간격. 서버는 흥정을 순식간에 끝내므로 읽을 시간을 여기서 준다. */
const TURN_DELAY_MS = 650;

/** "기본"은 고르는 값이 아니다. 비워 두면 요청 문장을 읽어 우선순위를 정한다. */
const AUTO = "";

const PLAN_OPENING: Partial<Record<Priority, string>> = {
  default: "기본으로 살게요.",
  price: "싸게 살게요.",
  intelligence: "똑똑하게 살게요.",
};

interface Block extends StreamModel {
  turns: NegotiationTurn[];
}

interface Turn {
  id: number;
  prompt: string;
  priority: Priority | null;
  blocks: Block[];
  record: PurchaseRecord | null;
  error: string | null;
}

function planText(priority: Priority, models: StreamModel[]): string {
  const opening = PLAN_OPENING[priority] ?? "";
  const names = models.map((model) => model.displayName);
  if (names.length === 1) return `${opening} ${names[0]} 판매 에이전트와 흥정할게요.`;
  return `${opening} ${names.join("와 ")} 판매 에이전트와 차례로 흥정해서 더 싸게 합의한 쪽을 고를게요.`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function PurchaseResult({ record, anchor }: { record: PurchaseRecord; anchor: (element: HTMLElement | null) => void }) {
  const { winner, budgetUnits } = record.decision;
  const reason = purchaseReason(record);
  return (
    <div className="msg top">
      <BuyerAvatar />
      <article className="final" ref={anchor}>
        <div className="finalHead">
          <h2>{purchaseTitle(record)}</h2>
          {reason !== null && <p>{reason}</p>}
          {record.status === "FAILED" && <p>{record.failureReason}</p>}
        </div>
        {isOverBudget(record) && (
          <Link className="warnLink" href="/dashboard/alerts">
            이상 거래에 경고를 남겼어요<span aria-hidden="true">→</span>
          </Link>
        )}
        <dl className="prices">
          <div>
            <dt>{record.status === "FAILED" ? "합의" : "결제"}</dt>
            <dd className="paid">{aegisText(winner.amountUnits)}</dd>
          </div>
          {winner.listAmountUnits !== undefined && (
            <div>
              <dt>호가</dt>
              <dd>{aegisText(winner.listAmountUnits)}</dd>
            </div>
          )}
          <div>
            <dt>예산</dt>
            <dd>{aegisText(budgetUnits)}</dd>
          </div>
        </dl>
        {record.resultText !== null && (
          <div className="finalResult">
            <h3>받아온 결과</h3>
            <pre className="resultBox">{record.resultText}</pre>
          </div>
        )}
        <Link className="textLink" href={`/dashboard/${record.id}`}>거래 기록 보기 →</Link>
      </article>
    </div>
  );
}

export function ChatPanel() {
  const [prompt, setPrompt] = useState("");
  const [budget, setBudget] = useState("0.3");
  const [priority, setPriority] = useState<string>(AUTO);
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);

  const log = useRef<HTMLDivElement>(null);
  const finalCard = useRef<HTMLElement | null>(null);
  const shownFinal = useRef<number | null>(null);

  // 말풍선이 늘면 아래로 따라가고, 결과가 나오면 구매 이유의 첫 줄이 먼저 보이게 한다.
  useEffect(() => {
    const element = log.current;
    if (element === null) return;
    const last = turns[turns.length - 1];
    if (last === undefined) return;
    if (last.record === null) {
      element.scrollTop = element.scrollHeight;
    } else if (shownFinal.current !== last.id && finalCard.current !== null) {
      shownFinal.current = last.id;
      element.scrollTop += finalCard.current.getBoundingClientRect().top - element.getBoundingClientRect().top - 16;
    }
  }, [turns]);

  function update(id: number, change: (turn: Turn) => Turn) {
    setTurns((prev) => prev.map((turn) => (turn.id === id ? change(turn) : turn)));
  }

  function apply(id: number, event: PurchaseStreamEvent) {
    if (event.type === "plan") {
      update(id, (turn) => ({
        ...turn,
        priority: event.priority,
        blocks: event.models.map((model) => ({ ...model, turns: [] })),
      }));
    } else if (event.type === "turn") {
      update(id, (turn) => ({
        ...turn,
        blocks: turn.blocks.map((block) => (block.key === event.key ? { ...block, turns: [...block.turns, event.turn] } : block)),
      }));
    } else if (event.type === "done") {
      update(id, (turn) => ({ ...turn, record: event.record }));
    } else {
      update(id, (turn) => ({ ...turn, error: event.error }));
    }
  }

  async function readEvents(response: Response, onEvent: (event: PurchaseStreamEvent) => void) {
    if (response.body === null) throw new Error("응답을 읽을 수 없습니다");
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let pending = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      pending += value;
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) {
        if (line.trim() !== "") onEvent(JSON.parse(line) as PurchaseStreamEvent);
      }
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if (text === "" || busy || parseAegis(budget) === null) return;

    const id = Date.now();
    setTurns((prev) => [...prev, { id, prompt: text, priority: null, blocks: [], record: null, error: null }]);
    setPrompt("");
    setBusy(true);

    // 받은 순서대로 쌓아 두고 하나씩 푼다. 이미 끝난 흥정에 붙는 말(취소 등)은 기다리지 않는다.
    const queue: PurchaseStreamEvent[] = [];
    const ended = new Set<string>();
    let reading = true;
    let wake: () => void = () => {};
    const shown = (async () => {
      while (reading || queue.length > 0) {
        const next = queue.shift();
        if (next === undefined) {
          await new Promise<void>((resolve) => { wake = resolve; });
          continue;
        }
        apply(id, next);
        if (next.type === "turn") {
          const alreadyEnded = ended.has(next.key);
          if (endsDeal(next.turn)) ended.add(next.key);
          if (!alreadyEnded) await sleep(TURN_DELAY_MS);
        }
      }
    })();

    const push = (next: PurchaseStreamEvent) => {
      queue.push(next);
      wake();
    };

    try {
      const response = await fetch("/api/purchase/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt: text, budget: budget.trim(), ...(priority === AUTO ? {} : { priority }) }),
      });
      if (response.ok) {
        await readEvents(response, push);
      } else {
        const body = (await response.json()) as { error?: string };
        push({ type: "error", error: body.error ?? `요청 실패 (${response.status})` });
      }
    } catch (caught) {
      push({ type: "error", error: caught instanceof Error ? caught.message : "요청을 보내지 못했습니다" });
    } finally {
      reading = false;
      wake();
      await shown;
      setBusy(false);
    }
  }

  return (
    <div className="chat">
      <div className="chatLog" ref={log}>
        {turns.length === 0 ? (
          <div className="chatEmpty">
            <h1>무엇을 시킬까요?</h1>
          </div>
        ) : (
          <div className="chatColumn">
            {turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                anchor={(element) => {
                  if (turn === turns[turns.length - 1]) finalCard.current = element;
                }}
              />
            ))}
          </div>
        )}
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <div className="composerInner">
          <div className="composerRow">
            <textarea
              aria-label="요청 내용"
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
              disabled={busy}
            />
            <button type="submit" aria-label="보내기" disabled={busy || prompt.trim() === "" || parseAegis(budget) === null}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 19V5M6 11l6-6 6 6" />
              </svg>
            </button>
          </div>
          <div className="composerOptions">
            <label>
              예산
              <input
                type="number"
                min={0}
                step={0.000001}
                value={budget}
                onChange={(event) => setBudget(event.target.value)}
                disabled={busy}
              />
              AEGIS
            </label>
            <label>
              우선순위
              <select value={priority} onChange={(event) => setPriority(event.target.value)} disabled={busy}>
                <option value={AUTO}>요청 문장으로 판단</option>
                <option value="price">싸게</option>
                <option value="intelligence">똑똑하게</option>
              </select>
            </label>
          </div>
        </div>
      </form>
    </div>
  );
}

function TurnView({ turn, anchor }: { turn: Turn; anchor: (element: HTMLElement | null) => void }) {
  const { record, error } = turn;
  const finished = record !== null || error !== null;
  // 어디서 살지 정해지면 기록의 결과로 그린다. 같은 기록을 다시 돌려받아 대화를 못 받은 경우에도 그릴 수 있다.
  const quotes = record === null ? [] : quotesOf(record);
  const blocks = record === null ? turn.blocks.filter((block) => block.turns.length > 0) : quotes.map((quote) => ({ ...quote, turns: quote.transcript }));
  const statusOf = (index: number, turns: NegotiationTurn[]) => (record === null ? dealStatus(turns) : quoteStatus(quotes[index]));

  const lastBlock = record === null ? blocks[blocks.length - 1] : undefined;
  const lastTurn = lastBlock?.turns[lastBlock.turns.length - 1];
  const allShown = turn.blocks.length > 0 && turn.blocks.every((block) => block.turns.some(endsDeal));

  return (
    <>
      <div className="bubble user">{turn.prompt}</div>

      <div className="msg">
        <BuyerAvatar />
        <div className="msgBody">
          <span className="msgName">구매 에이전트</span>
          <div className="bubble agent">네, 알겠어요. 어떤 모델끼리 비교할지 정할게요.</div>
        </div>
      </div>

      {turn.priority !== null && turn.blocks.length > 0 && (
        <div className="msg">
          <BuyerAvatar />
          <div className="msgBody">
            <div className="bubble agent">{planText(turn.priority, turn.blocks)}</div>
          </div>
        </div>
      )}

      {blocks.map((block, index) => (
        <NegotiationBlock
          key={block.key}
          displayName={block.displayName}
          sellerName={block.sellerName}
          askUnits={"askUnits" in block ? block.askUnits : 0}
          turns={block.turns}
          live={!finished && !block.turns.some(endsDeal)}
          status={statusOf(index, block.turns)}
        />
      ))}

      {!finished && (
        <div
          className={`typing${!allShown && lastTurn !== undefined && !endsDeal(lastTurn) && lastTurn.from === "buyer" ? " right" : ""}`}
          role="status"
          aria-label={allShown ? "결제하는 중" : "입력하는 중"}
        >
          <i />
          <i />
          <i />
          {allShown && <span>합의한 값으로 결제하는 중이에요</span>}
        </div>
      )}

      {error !== null && (
        <div className="msg">
          <BuyerAvatar />
          <div className="msgBody">
            <div className="bubble error">{error}</div>
          </div>
        </div>
      )}

      {record !== null && <PurchaseResult record={record} anchor={anchor} />}
    </>
  );
}
