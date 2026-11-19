"use client";

/**
 * 대시보드 잔액. 화면에 들어올 때마다 조금 아래 값에서 실제 잔액까지 소수점이 0.8초 동안 굴러간다.
 * 동작 줄이기 설정이면 바로 실제 잔액을 보여 준다.
 */

import { useEffect, useRef, useState } from "react";

import { UNITS_PER_AEGIS } from "@/lib/format";

/** 굴리기 시작하는 값은 실제 잔액보다 이만큼(AEGIS) 아래다. */
const ROLL_FROM = 0.1;
const ROLL_MS = 800;

export function BalanceRoll({ units }: { units: number }) {
  const target = units / UNITS_PER_AEGIS;
  const start = Math.max(target - ROLL_FROM, 0);
  const [value, setValue] = useState(target);
  const element = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = element.current;
    if (node === null || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const roll = () => {
      cancelAnimationFrame(frame);
      let began: number | null = null;
      const tick = (now: number) => {
        began ??= now;
        const t = Math.min(1, (now - began) / ROLL_MS);
        setValue(t === 1 ? target : start + (target - start) * (1 - Math.pow(2, -10 * t)));
        if (t < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    };
    const seen = new IntersectionObserver(
      (entries) => entries.forEach((entry) => (entry.isIntersecting ? roll() : setValue(start))),
      { threshold: 0.6 },
    );
    seen.observe(node);
    return () => {
      seen.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [start, target]);

  return (
    <strong ref={element} className="balanceValue" aria-label={`${target.toFixed(6)} AEGIS`}>
      {value.toFixed(6)}
      <span>AEGIS</span>
    </strong>
  );
}
