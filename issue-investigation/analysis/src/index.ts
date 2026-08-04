/**
 * Pi 分析服务：Bun + pi-coding-agent SDK。
 *
 * 职责：
 * - 每 run 一个 AgentSession（持久化到 data/pi-agent/sessions/）
 * - 自定义工具 5 个，通过 HTTP 回调 FastAPI 后端执行排查内核
 * - 会话事件流推送到后端 /events/{run_id}，由后端转发浏览器
 *
 * HTTP API（对后端开放）：
 *   POST /sessions/:runId                 创建会话
 *   POST /sessions/:runId/prompt          {text, env, history} 发送用户消息
 *   GET  /sessions/:runId/messages        返回简化消息列表（页面刷新恢复）
 */
import { existsSync, mkdirSync, copyFileSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { Type } from "typebox";
import {
  createAgentSession,
  defineTool,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";

const PORT = Number(process.env.INV_ANALYSIS_PORT || 8100);
const BACKEND_URL = process.env.INV_BACKEND_URL || "http://127.0.0.1:8000";
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN || "local-dev-token";
const DATA_DIR = process.env.INV_DATA_DIR || join(import.meta.dir, "..", "..", "data");
const HOME_AGENT_DIR = process.env.PI_AGENT_DIR_HOME || join(process.env.HOME || ".", ".pi", "agent");
const AGENT_DIR = process.env.INV_PI_AGENT_DIR || join(DATA_DIR, "pi-agent");

const SYSTEM_PROMPT = await Bun.file(join(import.meta.dir, "..", "prompt.md")).text();

// ---------- agentDir 引导：复用本机 ~/.pi/agent 的 LLM 配置 ----------
function bootstrapAgentDir() {
  mkdirSync(AGENT_DIR, { recursive: true });
  for (const f of ["auth.json", "settings.json", "models.json", "models-store.json"]) {
    const dest = join(AGENT_DIR, f);
    if (!existsSync(dest)) {
      const src = join(HOME_AGENT_DIR, f);
      if (existsSync(src)) copyFileSync(src, dest);
    }
  }
}
bootstrapAgentDir();

const modelRuntime = await ModelRuntime.create({
  authPath: join(AGENT_DIR, "auth.json"),
  modelsPath: join(AGENT_DIR, "models.json"),
});

// ---------- 工具：HTTP 回调后端执行排查内核 ----------
async function callTool(runId: string, name: string, params: Record<string, unknown>) {
  const resp = await fetch(`${BACKEND_URL}/tools/${name}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-tool-token": TOOL_TOKEN,
    },
    body: JSON.stringify({ run_id: runId, env: params.env, params }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`tool ${name} failed (${resp.status}): ${text.slice(0, 500)}`);
  }
  return resp.json();
}

function toolResult(name: string, result: unknown) {
  const text = JSON.stringify(result, null, 2);
  return {
    content: [{ type: "text", text: text.length > 16000 ? text.slice(0, 16000) + "\n...(截断)" : text }],
    details: { tool: name },
  };
}

const str = (d: string) => Type.String({ description: d });
const opt = (d: string) => Type.Optional(Type.String({ description: d }));

const TOOLS = [
  defineTool({
    name: "collect_logs",
    label: "采集日志",
    description: "采集 dev/sit 环境 ES 日志（按 traceId/告警/业务键）。结果含各应用命中数与错误数。",
    parameters: Type.Object({
      env: str("环境：dev 或 sit"),
      app: str("主应用：lcs/goa/ams/lps"),
      mode: Type.Optional(Type.Union([Type.Literal("trace_id"), Type.Literal("alert"), Type.Literal("biz_key")], { description: "排查模式" })),
      query: opt("查询值：traceId 或业务键"),
      alert: opt("告警/报错文本（mode=alert 时）"),
      biz_key: opt("业务键（mode=biz_key 时）"),
      apps: Type.Optional(Type.Array(Type.String(), { description: "涉及应用列表（默认仅主应用）" })),
    }),
    execute: async (_id, params, runId) => toolResult("collect_logs", await callTool(runId, "collect_logs", params)),
  }),
  defineTool({
    name: "scan_code",
    label: "扫描源码",
    description: "扫描 Java 源码 + Mapper XML + Spring 配置 + git 变更，定位异常类/方法/调用链。",
    parameters: Type.Object({
      env: str("环境：dev 或 sit"),
      app: str("主应用"),
      keywords: Type.Array(Type.String(), { description: "扫描关键词（类名/方法名/字段）" }),
      log_messages: Type.Optional(Type.Array(Type.String(), { description: "日志片段（可选，作为扫描上下文）" })),
    }),
    execute: async (_id, params, runId) => toolResult("scan_code", await callTool(runId, "scan_code", params)),
  }),
  defineTool({
    name: "nacos_query",
    label: "查询 Nacos",
    description: "查询指定应用的 Nacos 配置 key（group/dataId 自动发现）。",
    parameters: Type.Object({
      env: str("环境：dev 或 sit"),
      app: str("应用：lcs/goa/ams/lps"),
      keys: Type.Array(Type.String(), { description: "要查询的配置 key 列表" }),
    }),
    execute: async (_id, params, runId) => toolResult("nacos_query", await callTool(runId, "nacos_query", params)),
  }),
  defineTool({
    name: "db_query",
    label: "只读查库",
    description: "只读执行数据库查询（自动 LIMIT 20，单次≤5条）。plan 结构：{need_db:true, queries:[{app,table,sql}]}；无假设时返回 need_db:false。",
    parameters: Type.Object({
      env: str("环境：dev 或 sit"),
      app: opt("主应用"),
      plan: Type.Object({
        need_db: Type.Boolean({ description: "是否需要查库" }),
        queries: Type.Optional(Type.Array(Type.Object({
          app: str("应用"),
          table: opt("表名"),
          sql: str("只读 SELECT"),
          where: opt("where 条件描述"),
        }), { description: "查询列表（≤5 条）" })),
      }),
    }),
    execute: async (_id, params, runId) => toolResult("db_query", await callTool(runId, "db_query", params)),
  }),
  defineTool({
    name: "run_investigation",
    label: "一键全量排查",
    description: "一键执行完整排查流水线：ES 日志 + 源码扫描 + Nacos（可选）+ 报告 §1-§4（指纹去重/时序/交叉验证）。适合首次完整排查。",
    parameters: Type.Object({
      env: str("环境：dev 或 sit"),
      app: str("主应用：lcs/goa/ams/lps"),
      mode: Type.Optional(Type.Union([Type.Literal("trace_id"), Type.Literal("alert"), Type.Literal("biz_key")], { description: "排查模式" })),
      query: opt("查询值：traceId 或业务键"),
      alert: opt("告警/报错文本"),
      biz_key: opt("业务键"),
      scope: Type.Optional(Type.Union([Type.Literal("primary_only"), Type.Literal("all")], { description: "范围：仅主应用 / 四应用广扫" })),
    }),
    execute: async (_id, params, runId) => toolResult("run_investigation", await callTool(runId, "run_investigation", params)),
  }),
];

// ---------- 会话管理 ----------
type SessionHandle = Awaited<ReturnType<typeof createAgentSession>>;
const sessions = new Map<string, SessionHandle>();

async function createSession(runId: string) {
  const sessionDir = join(AGENT_DIR, "sessions", `run-${runId}`);
  const sessionManager = SessionManager.create(join(DATA_DIR, "pi-agent"), sessionDir);
  const loader = new DefaultResourceLoader({
    cwd: join(DATA_DIR, "pi-agent"),
    agentDir: AGENT_DIR,
    systemPromptOverride: () => SYSTEM_PROMPT,
  });
  await loader.reload();

  const handle = await createAgentSession({
    cwd: join(DATA_DIR, "pi-agent"),
    agentDir: AGENT_DIR,
    modelRuntime,
    customTools: TOOLS,
    resourceLoader: loader,
    sessionManager,
  });
  const { session } = handle;

  session.subscribe((event) => {
    forwardEvent(runId, mapEvent(event));
  });

  sessions.set(runId, handle);
  return handle;
}

async function getSession(runId: string): Promise<SessionHandle> {
  const h = sessions.get(runId);
  if (h) return h;
  return resumeSession(runId);
}

/** 从持久化 JSONL 恢复会话（sidecar 重启后可续聊/读消息）。 */
async function resumeSession(runId: string): Promise<SessionHandle> {
  const sessionDir = join(AGENT_DIR, "sessions", `run-${runId}`);
  const files = listJsonlFiles(sessionDir);
  if (files.length === 0) {
    console.error("[resume] no session file for", runId, "in", sessionDir);
    throw new Error(`session not found: ${runId}`);
  }

  const loader = new DefaultResourceLoader({
    cwd: join(DATA_DIR, "pi-agent"),
    agentDir: AGENT_DIR,
    systemPromptOverride: () => SYSTEM_PROMPT,
  });
  await loader.reload();

  const handle = await createAgentSession({
    cwd: join(DATA_DIR, "pi-agent"),
    agentDir: AGENT_DIR,
    modelRuntime,
    customTools: TOOLS,
    resourceLoader: loader,
    sessionManager: SessionManager.open(files[0], sessionDir),
  });
  handle.session.subscribe((event) => forwardEvent(runId, mapEvent(event)));
  sessions.set(runId, handle);
  return handle;
}

function listJsonlFiles(dir: string): string[] {
  try {
    mkdirSync(dir, { recursive: true });
    return readdirSync(dir)
      .filter((f) => f.endsWith(".jsonl"))
      .map((f) => join(dir, f))
      .sort((a, b) => b.localeCompare(a));
  } catch {
    return [];
  }
}

// ---------- 事件映射与推送 ----------
function mapEvent(event: any): { type: string; data: any } {
  switch (event.type) {
    case "message_update": {
      const ae = event.assistantMessageEvent;
      if (ae?.type === "text_delta") return { type: "text_delta", data: { text: ae.delta } };
      if (ae?.type === "thinking_delta") return { type: "thinking_delta", data: { text: ae.delta } };
      return { type: "message_update", data: {} };
    }
    case "tool_execution_start":
      return { type: "tool_start", data: { tool: event.toolName } };
    case "tool_execution_end":
      return { type: "tool_end", data: { tool: event.toolName, isError: event.isError } };
    case "message_end":
      return { type: "message_end", data: {} };
    case "agent_end":
      return { type: "done", data: {} };
    default:
      return { type: "ignored", data: {} };
  }
}

async function forwardEvent(runId: string, ev: { type: string; data: any }) {
  if (ev.type === "ignored") return;
  try {
    await fetch(`${BACKEND_URL}/events/${runId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-tool-token": TOOL_TOKEN },
      body: JSON.stringify(ev),
    });
  } catch (err) {
    console.error("[forwardEvent]", runId, ev.type, err);
  }
}

function summarizeMessages(session: SessionHandle, runId: string): any[] {
  const msgs: any[] = [];
  const stateMsgs = session.agent?.state?.messages ?? [];
  for (const m of stateMsgs) {
    if (m.role === "user") {
      const text = extractText(m);
      msgs.push({ role: "user", text });
    } else if (m.role === "assistant") {
      const text = extractText(m);
      if (text) msgs.push({ role: "assistant", text });
    }
  }
  if (msgs.length > 0) return msgs;
  const file = listJsonlFiles(join(AGENT_DIR, "sessions", `run-${runId}`));
  if (file.length > 0) return parseSessionFile(file[0]);
  return [];
}

function parseSessionFile(path: string): any[] {
  const msgs: any[] = [];
  for (const line of readFileSync(path, "utf-8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (entry.type !== "message") continue;
      const m = entry.message ?? {};
      const text = extractText(m);
      if (m.role === "user") msgs.push({ role: "user", text });
      else if (m.role === "assistant" && text) msgs.push({ role: "assistant", text });
    } catch {
      /* 跳过损坏行 */
    }
  }
  return msgs;
}

function extractText(m: any): string {
  const content = m.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((c: any) => c?.type === "text")
      .map((c: any) => c.text ?? "")
      .join("\n");
  }
  return m.text ?? "";
}

// ---------- HTTP 服务 ----------
Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const parts = url.pathname.split("/").filter(Boolean); // ["sessions", runId, ...]

    if (req.method === "POST" && parts[0] === "sessions" && parts.length === 2) {
      const runId = parts[1];
      try {
        await createSession(runId);
        return Response.json({ ok: true, run_id: runId });
      } catch (err) {
        return Response.json({ ok: false, error: String(err) }, { status: 500 });
      }
    }

    if (req.method === "POST" && parts[0] === "sessions" && parts[2] === "prompt") {
      const runId = parts[1];
      const body = await req.json();
      const text = String(body.text || "");
      const env = String(body.env || "dev");
      let handle: SessionHandle;
      try {
        handle = await getSession(runId);
      } catch {
        handle = await createSession(runId);
      }
      const prompt = `[当前排查环境: ${env}]（所有日志/库表/配置查询均按 ${env} 执行；如与之前声明不一致，以此为准）\n\n用户消息: ${text}`;
      const run = async () => {
        if (handle.session.isStreaming) {
          await handle.session.followUp(prompt);
        } else {
          await handle.session.prompt(prompt);
        }
      };
      run().catch((err) => {
        console.error("[prompt]", runId, err);
        forwardEvent(runId, { type: "error", data: { message: String(err) } });
      });
      return Response.json({ ok: true });
    }

    if (req.method === "GET" && parts[0] === "sessions" && parts[2] === "messages") {
      const runId = parts[1];
      try {
        const h = await getSession(runId);
        return Response.json(summarizeMessages(h, runId));
      } catch (err) {
        console.error("[messages]", runId, err);
        return Response.json([]);
      }
    }

    return Response.json({ error: "not found" }, { status: 404 });
  },
});

console.log(`[analysis] pi sidecar listening on :${PORT}, agentDir=${AGENT_DIR}`);
