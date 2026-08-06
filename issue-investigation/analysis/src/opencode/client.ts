/**
 * opencode 集成层：serve 子进程管理 + SDK client + run_id ↔ session_id 会话映射。
 * 所有 opencode 相关代码集中在本目录（配置/工具在 config/opencode/）。
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createOpencodeClient } from "@opencode-ai/sdk";

export const PORT = Number(process.env.INV_ANALYSIS_PORT || 8700);
export const PROJECT_ROOT = join(import.meta.dir, "..", "..", "..");
export const DATA_DIR = process.env.INV_DATA_DIR || join(PROJECT_ROOT, "data");
export const MAPPINGS_DIR = join(DATA_DIR, "opencode", "mappings");
export const OPENCODE_CONFIG_DIR = join(PROJECT_ROOT, "config", "opencode");
export const OPENCODE_PORT = Number(process.env.INV_OPENCODE_PORT || 14100);
export const OPENCODE_DATA_DIR = join(DATA_DIR, "opencode");
export const OPENCODE_DB = join(OPENCODE_DATA_DIR, "opencode.db");
export const OPENCODE_URL = `http://127.0.0.1:${OPENCODE_PORT}`;
export const SIDECAR_URL = `http://127.0.0.1:${PORT}`;

const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN || "local-dev-token";

function resolveOpencodeBin(): string {
  try {
    Bun.spawnSync(["opencode", "--version"], { stdout: "ignore", stderr: "ignore" });
    return "opencode";
  } catch {
    return join(homedir(), ".opencode", "bin", "opencode");
  }
}

export function spawnServe(): void {
  mkdirSync(OPENCODE_DATA_DIR, { recursive: true });
  const proc = Bun.spawn(
    [resolveOpencodeBin(), "serve", "--port", String(OPENCODE_PORT), "--hostname", "127.0.0.1"],
    {
      cwd: OPENCODE_CONFIG_DIR,
      env: {
        ...process.env,
        OPENCODE_DB,
        INV_SIDECAR_URL: SIDECAR_URL,
        INV_PI_TOOL_TOKEN: TOOL_TOKEN,
      },
      stdout: "inherit",
      stderr: "inherit",
    },
  );
  proc.exited.then(async (code) => {
    console.error(`[analysis] opencode serve exited (code ${code})，3s 后重启`);
    await Bun.sleep(3000);
    if (!process.env.INV_OPENCODE_NO_RESTART) spawnServe();
  });
}

export async function waitForHealth(timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(`${OPENCODE_URL}/global/health`);
      if (resp.ok) {
        const data = await resp.json();
        console.log(`[analysis] opencode serve healthy (version ${data.version})`);
        return;
      }
    } catch {
      /* 未就绪，重试 */
    }
    await Bun.sleep(500);
  }
  console.error(`[analysis] opencode serve 启动超时（${OPENCODE_URL}）`);
  process.exit(1);
}

export const client = createOpencodeClient({ baseUrl: OPENCODE_URL, throwOnError: true });

// ---------- 会话映射（run_id ↔ session_id） ----------
export const sessions = new Map<string, string>(); // runId -> sessionId
export const runBySession = new Map<string, string>(); // sessionId -> runId
const creating = new Map<string, Promise<string>>(); // runId -> 创建中（并发去重）

function mappingFile(runId: string): string {
  return join(MAPPINGS_DIR, `run-${runId}`, "session.json");
}

export function loadMapping(runId: string): string | null {
  try {
    const data = JSON.parse(readFileSync(mappingFile(runId), "utf-8"));
    return data.session_id || null;
  } catch {
    return null;
  }
}

function saveMapping(runId: string, sessionId: string): void {
  mkdirSync(join(MAPPINGS_DIR, `run-${runId}`), { recursive: true });
  writeFileSync(
    mappingFile(runId),
    JSON.stringify({ run_id: runId, session_id: sessionId, created_at: new Date().toISOString() }, null, 2),
  );
}

function register(runId: string, sessionId: string): void {
  sessions.set(runId, sessionId);
  runBySession.set(sessionId, runId);
}

export async function resolveSessionId(runId: string): Promise<string> {
  const existing = sessions.get(runId);
  if (existing) return existing;
  let p = creating.get(runId);
  if (!p) {
    p = (async () => {
      const mapped = loadMapping(runId);
      if (mapped) {
        try {
          await client.session.get({ path: { id: mapped } });
          register(runId, mapped);
          return mapped;
        } catch {
          /* DB 被清过，重建 */
        }
      }
      const created: any = await client.session.create({ body: { title: `run-${runId}` } });
      const sessionId = created.data?.id ?? created.id;
      if (!sessionId) throw new Error(`create session failed: ${JSON.stringify(created)}`);
      register(runId, sessionId);
      saveMapping(runId, sessionId);
      return sessionId;
    })()
      .then((id) => {
        sessions.set(runId, id);
        return id;
      })
      .finally(() => creating.delete(runId));
    creating.set(runId, p);
  }
  return p;
}

export async function findRunBySession(sessionId: string): Promise<string | null> {
  const cached = runBySession.get(sessionId);
  if (cached) return cached;
  try {
    const dirs = new Bun.Glob(`run-*/session.json`).scanSync({ cwd: MAPPINGS_DIR });
    for (const rel of dirs) {
      try {
        const data = JSON.parse(readFileSync(join(MAPPINGS_DIR, rel), "utf-8"));
        if (data.session_id === sessionId) {
          register(data.run_id, sessionId);
          return data.run_id;
        }
      } catch {
        /* 跳过损坏映射 */
      }
    }
  } catch {
    /* 目录不存在 */
  }
  return null;
}

export async function listSessionIds(): Promise<string[]> {
  try {
    const result: any = await client.session.list();
    const list = result.data ?? result;
    return Array.isArray(list) ? list.map((s: any) => s.id) : [];
  } catch {
    return [];
  }
}
