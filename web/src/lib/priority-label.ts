/** 우선순위 라벨. 입력창과 기록에서 같은 말로 보여준다. */

import type { Priority } from "@/lib/types";

export const PRIORITY_LABEL: Record<Priority, string> = {
  default: "기본",
  price: "싸게",
  speed: "빠르게",
  intelligence: "똑똑하게",
};
