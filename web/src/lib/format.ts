/**
 * 금액 표기. 화면에는 사람이 읽는 AEGIS로만 보여준다.
 *
 * 체인은 소수점을 다루지 못해서 내부 계산은 최소 단위(units) 정수로만 한다.
 * AEGIS 소수점이 6자리이므로 1 AEGIS = 1,000,000 units 다. 원-전, 달러-센트와 같은 관계다.
 */

export const UNITS_PER_AEGIS = 1_000_000;

/** 최소 단위 → AEGIS 문자열. 뒤에 붙는 0은 떼고, 정수면 소수점도 떼어 짧게 보여준다. */
export function toAegis(units: number): string {
  const text = (units / UNITS_PER_AEGIS).toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  return text === "" ? "0" : text;
}

/** 표와 문장에서 쓰는 기본 금액 표기. */
export function aegisText(units: number): string {
  return `${toAegis(units)} AEGIS`;
}

/**
 * 사람이 적은 AEGIS 금액("0.5", 0.5) → 최소 단위 정수. 소수점 오차가 없도록 문자열 자릿수로 바꾼다.
 * 0 이상이고 소수점 6자리까지만 받는다. 형식이 틀리면 null.
 */
export function parseAegis(value: unknown): number | null {
  const text = typeof value === "number" ? String(value) : typeof value === "string" ? value.trim() : "";
  const match = /^(\d+)(?:\.(\d{1,6}))?$/.exec(text);
  if (match === null) return null;
  const [, whole, fraction = ""] = match;
  return Number(whole) * UNITS_PER_AEGIS + Number(fraction.padEnd(6, "0"));
}
