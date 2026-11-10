"use client";

import { useState } from "react";

/** 줄여서 보여 주는 값의 전체를 복사한다. 브라우저가 막으면 전체 값은 "자세히"에서 고를 수 있다. */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copyButton"
      aria-label={copied ? "복사했어요" : label}
      title={copied ? "복사했어요" : label}
      onClick={() => {
        navigator.clipboard?.writeText(value).then(() => setCopied(true)).catch(() => {});
      }}
    >
      {copied ? (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#02744a" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m5 12 5 5L20 7" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V6a2 2 0 0 1 2-2h9" />
        </svg>
      )}
    </button>
  );
}
