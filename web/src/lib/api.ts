/**
 * Python 서버(agent_m2m/api.py) 조회. 서버 컴포넌트가 화면을 그릴 때 쓴다.
 * 구매 요청(POST /api/purchase)은 브라우저가 보내고, next.config.ts 가 같은 서버로 넘긴다.
 */

import type { AuditAlert, PaymentMode, PurchaseRecord } from "@/lib/types";

const API_URL = process.env.AGENT_M2M_API_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`API ${path} 실패 (${response.status})`);
  return (await response.json()) as T;
}

export function listPurchases(limit = 50): Promise<PurchaseRecord[]> {
  return get(`/api/purchases?limit=${limit}`);
}

export async function getPurchase(id: string): Promise<PurchaseRecord | null> {
  const response = await fetch(`${API_URL}/api/purchases/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API /api/purchases/${id} 실패 (${response.status})`);
  return (await response.json()) as PurchaseRecord;
}

export function listAlertsForPurchase(id: string): Promise<AuditAlert[]> {
  return get(`/api/purchases/${encodeURIComponent(id)}/alerts`);
}

/** 최근 알림과, 링크를 달 수 있는(구매 기록이 있는) 구매 번호. 요청 직후에 막힌 알림은 기록이 없다. */
export async function listAlerts(limit = 50): Promise<{ alerts: AuditAlert[]; linked: Set<string> }> {
  const body = await get<{ alerts: AuditAlert[]; linkedPurchaseIds: string[] }>(`/api/alerts?limit=${limit}`);
  return { alerts: body.alerts, linked: new Set(body.linkedPurchaseIds) };
}

export function countAlerts(): Promise<{ blocked: number; warnings: number }> {
  return get("/api/alerts/summary");
}

export function buyerBalance(): Promise<{ units: number | null; status: string }> {
  return get("/api/wallet");
}

export async function paymentMode(): Promise<PaymentMode> {
  return (await get<{ mode: PaymentMode }>("/api/mode")).mode;
}
