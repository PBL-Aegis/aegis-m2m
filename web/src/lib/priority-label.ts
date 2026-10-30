/**
 * 우선순위 라벨. "가격 우선"처럼 적으면 싸다는 뜻인지 비싸다는 뜻인지 읽는 사람이 헷갈린다.
 * 그래서 원하는 결과를 문장으로 적는다. 배점은 결정 근거 화면에서 보여준다.
 */

import type { Priority } from "@/lib/types";

export const PRIORITY_LABEL: Record<Priority, string> = {
  default: "가격, 속도, 성능이 적절한 모델을 원해요",
  price: "가장 싼 모델을 원해요",
  speed: "가장 빠른 모델을 원해요",
  intelligence: "가장 똑똑한 모델을 원해요",
};
