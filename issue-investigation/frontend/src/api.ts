import { useRouter } from "vue-router";

const BASE = "";

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    const err = new Error(detail) as any;
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}

export interface Run {
  id: string;
  title: string;
  env: "dev" | "sit";
  app: string;
  mode: string;
  trace_id: string;
  alert: string;
  biz_key: string;
  phenomenon: string;
  scope: string;
  status: string;
  message_count: number;
  turn_limit: number;
  created_at: number;
  updated_at: number;
  timeline: Array<{ t: number; event: string; detail: string }>;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export interface BizKeyRule {
  pattern: string;
  table: string;
  field: string;
}

export interface AppConfig {
  db_name: string;
  biz_keys: BizKeyRule[];
}

export interface TermConfig {
  term: string;
  apps: string[];
}

export interface PlatformConfig {
  apps: Record<string, AppConfig>;
  terms: TermConfig[];
}

export function getConfig(): Promise<PlatformConfig> {
  return api("/config");
}

export function updateConfig(cfg: PlatformConfig): Promise<{ saved: boolean; errors?: string[] }> {
  return api("/config", { method: "PUT", body: JSON.stringify(cfg) });
}

export function createRun(payload: Record<string, unknown>): Promise<Run> {
  return api("/runs", { method: "POST", body: JSON.stringify(payload) });
}

export function listRuns(): Promise<Run[]> {
  return api("/runs");
}

export function getRun(id: string): Promise<Run> {
  return api(`/runs/${id}`);
}

export function getMessages(id: string): Promise<ChatMessage[]> {
  return api(`/runs/${id}/messages`);
}

export async function getCost(id: string): Promise<number> {
  try {
    const data = await api<{ cost: number }>(`/runs/${id}/cost`);
    return data.cost ?? 0;
  } catch {
    return 0;
  }
}

export function sendMessage(id: string, text: string, env: string, resume = false) {
  return api(`/runs/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ text, env, resume }),
  });
}

export async function getRunStatus(id: string): Promise<{
  pending: boolean;
  pending_since: number | null;
  processing: boolean;
  sidecar_unreachable: boolean;
}> {
  try {
    return await api(`/runs/${id}/status`);
  } catch {
    return { pending: false, pending_since: null, processing: false, sidecar_unreachable: true };
  }
}

export function getReport(id: string): Promise<string> {
  return fetch(`${BASE}/runs/${id}/report`).then((r) => r.text());
}

export function listArtifacts(id: string): Promise<Array<{ name: string; files: string[] }>> {
  return api(`/runs/${id}/artifacts`);
}

export function openStream(id: string): WebSocket {
  // 开发环境直连后端（VITE_WS_BASE），绕开 vite 代理的 WS 不稳定；生产走同源 ingress
  const wsBase = import.meta.env.VITE_WS_BASE as string | undefined;
  if (wsBase) {
    return new WebSocket(`${wsBase.startsWith("ws") ? wsBase : `ws://${wsBase}`}/runs/${id}/stream`);
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${location.host}/runs/${id}/stream`);
}

export async function getModelName(): Promise<string> {
  try {
    const data = await api<{ model?: string }>("/envs");
    return data.model || "deepseek-v4-flash";
  } catch {
    return "deepseek-v4-flash";
  }
}

export function useGoDetail() {
  const router = useRouter();
  return (id: string) => router.push({ name: "detail", params: { id } });
}
