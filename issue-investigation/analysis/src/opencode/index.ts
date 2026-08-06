/**
 * 分析服务：Bun + opencode server SDK。
 *
 * 职责：
 * - 管理 opencode serve 子进程与会话映射（见 src/opencode/client.ts）
 * - 6 个自定义工具（config/opencode/.opencode/tools/）通过内部端点 /tool/{name} 回调本服务，
 *   由本服务解析 run_id 后转发 FastAPI 后端执行排查内核
 * - 会话事件流（SSE）映射（见 src/opencode/events.ts）推送到后端 /events/{run_id}
 * - 结论完整性校验：session.idle 时缺结论自动补救一轮，仍缺则以 warning 放行
 *
 * HTTP API（对后端开放，契约与 pi 版本一致）：
 *   POST /sessions/:runId                 创建会话
 *   POST /sessions/:runId/prompt          {text, env, history, agent} 发送用户消息
 *   GET  /sessions/:runId/messages        返回简化消息列表（页面刷新恢复）
 *   POST /sessions/:runId/abort           中止
 *   GET  /sessions/:runId/cost            累计成本（USD）
 *   GET  /sessions/:runId/status          运行状态
 *   POST /tool/:name                      自定义工具回调（内部，x-tool-token 鉴权）
 */
import { join } from "node:path";
import { readFileSync } from "node:fs";
import {
  client,
  PROJECT_ROOT,
  SESSIONS_DIR,
  OPENCODE_DB,
  PORT,
  spawnServe,
  waitForHealth,
  resolveSessionId,
  findRunBySession,
} from "./client.ts";
import { createEventHandler, EVENT_PROTOCOL_VERSION } from "./events.ts";
import { validateConclusion } from "../conclusion_check.ts";

const BACKEND_URL = process.env.INV_BACKEND_URL || "http://127.0.0.1:8600";
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN || "local-dev-token";
const DEFAULT_AGENT = "investigation";

// ---------- opencode serve 启动 ----------
spawnServe();
await waitForHealth();

// ---------- 工具回调（.opencode/tools/*.ts → 本服务 → 后端内核） ----------
async function handleTool(name: string, sessionId: string, args: Record<string, unknown>) {
  const runId = await findRunBySession(sessionId);
  if (!runId) throw new Error(`session not mapped: ${sessionId}`);
  const resp = await fetch(`${BACKEND_URL}/tools/${name}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-tool-token": TOOL_TOKEN,
    },
    body: JSON.stringify({ run_id: runId, env: args.env, params: args }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`tool ${name} failed (${resp.status}): ${text.slice(0, 500)}`);
  }
  return resp.json();
}

// ---------- 轮次与结论校验 ----------
/** 每 run 进行中的轮次（prompt 已发出未结束）；session.idle 后复位。 */
const activeTurn = new Map<string, boolean>();
const pendingPrompts = new Map<string, number>(); // runId -> 进行中的 prompt 数
const lastActivity = new Map<string, number>();
const remedied = new Map<string, boolean>();
const promptQueues = new Map<string, string[]>(); // 会话忙时排队

const IDLE_TIMEOUT_MS = Number(process.env.INV_IDLE_TIMEOUT_MS || 180000);

function touchActivity(runId: string) {
  lastActivity.set(runId, Date.now());
}

const REMEDY_PROMPT = (reason: string) =>
  `系统提示：你的上一条回答未通过结论完整性检查：${reason}。` +
  `请只补充输出缺失的「结论」小节（根因/置信度/证据要点）或「待补线索」小节（还需什么信息），` +
  `不要重复已输出的排查过程与结论。`;

async function sendPrompt(runId: string, sessionId: string, text: string, agent = DEFAULT_AGENT): Promise<void> {
  activeTurn.set(runId, true);
  pendingPrompts.set(runId, (pendingPrompts.get(runId) || 0) + 1);
  touchActivity(runId);
  try {
    await client.session.promptAsync({
      path: { id: sessionId },
      body: { agent, parts: [{ type: "text", text }] },
    });
  } catch (err) {
    activeTurn.delete(runId);
    throw err;
  } finally {
    const n = (pendingPrompts.get(runId) || 1) - 1;
    if (n <= 0) pendingPrompts.delete(runId);
    else pendingPrompts.set(runId, n);
  }
}

/** session.idle → 校验结论；缺则自动补救一轮（不计轮次），仍缺则 done 带 warning。 */
async function concludeTurn(runId: string, sessionId: string): Promise<void> {
  if (!activeTurn.get(runId)) return; // 历史会话重放 / 无进行中任务 → 忽略
  activeTurn.delete(runId);
  const queued = promptQueues.get(runId) ?? [];
  if (queued.length > 0) {
    promptQueues.set(runId, queued.slice(1));
    void sendPrompt(runId, sessionId, queued[0]).catch((err) => {
      console.error("[queue prompt]", runId, err);
      forwardEvent(runId, { type: "error", data: { message: String(err) } });
    });
    return;
  }

  let v: { ok: boolean; reason?: string };
  try {
    v = validateConclusion(await lastAssistantText(runId));
  } catch (err) {
    console.error("[concludeTurn validate]", runId, err);
    v = { ok: false, reason: String(err) };
  }
  const cost = await computeCostSafe(runId);
  if (v.ok) {
    forwardEvent(runId, { type: "done", data: { cost } });
    return;
  }
  if (remedied.get(runId)) {
    forwardEvent(runId, { type: "done", data: { cost, warning: v.reason } });
    return;
  }
  remedied.set(runId, true);
  try {
    await sendPrompt(runId, sessionId, REMEDY_PROMPT(v.reason ?? ""));
  } catch (err) {
    console.error("[concludeTurn remedy]", runId, err);
    forwardEvent(runId, { type: "done", data: { cost, warning: v.reason } });
  }
}

async function lastAssistantText(runId: string): Promise<string> {
  const sessionId = await resolveSessionId(runId);
  const result: any = await client.session.messages({ path: { id: sessionId } });
  const rows = result.data ?? result;
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    if (row.info.role !== "assistant") continue;
    const texts = (row.parts as any[])
      .filter((p) => p.type === "text" && p.text)
      .map((p) => p.text)
      .join("\n");
    if (texts) return texts;
  }
  return "";
}

async function computeCostSafe(runId: string): Promise<number> {
  try {
    const sessionId = await resolveSessionId(runId);
    const result: any = await client.session.messages({ path: { id: sessionId } });
    const rows = result.data ?? result;
    let total = 0;
    for (const row of rows) {
      for (const p of row.parts as any[]) {
        if (p.type === "step-finish" && typeof p.cost === "number") total += p.cost;
      }
    }
    return Number(total.toFixed(6));
  } catch {
    return 0;
  }
}

// ---------- 看护 ----------
function startWatchdog() {
  setInterval(() => {
    const now = Date.now();
    for (const [runId, pending] of pendingPrompts) {
      if (pending <= 0) continue;
      const last = lastActivity.get(runId) ?? now;
      if (now - last <= IDLE_TIMEOUT_MS) continue;
      console.error(`[watchdog] run ${runId} 无事件 ${(now - last) / 1000}s，自动停止`);
      void (async () => {
        try {
          const sid = await resolveSessionId(runId);
          await client.session.abort({ path: { id: sid } });
        } catch {
          /* 会话可能已不存在 */
        }
      })();
      pendingPrompts.delete(runId);
      activeTurn.delete(runId);
      forwardEvent(runId, {
        type: "error",
        data: { message: "排查长时间无响应（可能为网络/模型超时），已自动停止，请重试" },
      });
    }
  }, 20000);
}

// ---------- 事件批量推送（60ms 合并） ----------
const eventQueues = new Map<string, any[]>();
const eventTimers = new Map<string, ReturnType<typeof setInterval>>();

function forwardEvent(runId: string, ev: { type: string; data: any }) {
  touchActivity(runId);
  let q = eventQueues.get(runId);
  if (!q) {
    q = [];
    eventQueues.set(runId, q);
  }
  q.push(ev);
  if (!eventTimers.has(runId)) {
    const timer = setInterval(() => flushEvents(runId), 60);
    eventTimers.set(runId, timer);
  }
}

async function flushEvents(runId: string) {
  const q = eventQueues.get(runId) ?? [];
  if (q.length === 0) return;
  eventQueues.set(runId, []);
  try {
    await fetch(`${BACKEND_URL}/events/${runId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-tool-token": TOOL_TOKEN },
      body: JSON.stringify({ events: q }),
    });
  } catch (err) {
    const cur = eventQueues.get(runId) ?? [];
    eventQueues.set(runId, [...cur, ...q]);
    console.error("[forwardEvent]", runId, err);
  }
}

// ---------- 事件流订阅 ----------
const handleEvent = createEventHandler({
  forwardEvent,
  onSessionIdle: (runId, sessionId) => {
    void concludeTurn(runId, sessionId);
  },
});

async function startEventStream(): Promise<void> {
  for (;;) {
    try {
      const events = await client.event.subscribe();
      for await (const event of (events as any).stream) {
        handleEvent(event);
      }
    } catch (err) {
      console.error("[analysis] 事件流断开，3s 后重连:", err);
      await Bun.sleep(3000);
    }
  }
}

// ---------- 消息分组（opencode rows → 平台消息结构） ----------
function stripUserPrefix(text: string): string {
  let t = text.trim();
  if (t.startsWith("[当前排查环境:")) {
    const idx = t.indexOf("用户消息:");
    if (idx !== -1) t = t.slice(idx + "用户消息:".length);
  }
  while (t.startsWith("用户消息:")) {
    t = t.replace(/^用户消息:\s*/, "");
  }
  return t.trim();
}

/**
 * 按"轮次"分组：一个用户问题 = 一轮（连续 assistant 步骤合并）。
 * - user：原话 + 时间戳
 * - assistant 轮：最终答案(text) + 处理详情（thinking/tool_calls）+ usage + model + 时间戳
 */
function groupRows(rows: any[]): any[] {
  const out: any[] = [];
  let cur: any = null;
  let turnCost = 0;

  for (const row of rows) {
    const info = row.info;
    const parts: any[] = row.parts ?? [];

    if (info.role === "user") {
      if (cur) cur.usage.cost = turnCost; // 结算上一轮成本
      cur = null;
      turnCost = 0;
      const text = stripUserPrefix(
        parts.filter((p) => p.type === "text").map((p) => p.text ?? "").join("\n"),
      );
      const lastUser = [...out].reverse().find((x: any) => x.role === "user");
      if (lastUser && lastUser.text === text) continue;
      out.push({ role: "user", text, ts: info.time?.created ?? Date.now() });
      continue;
    }
    if (info.role !== "assistant") continue;

    const texts = parts.filter((p) => p.type === "text" && p.text).map((p) => p.text ?? "");
    const reasoning = parts.filter((p) => p.type === "reasoning" && p.text).map((p) => p.text ?? "");
    const calls = parts
      .filter((p) => p.type === "tool")
      .map((p: any) => ({
        name: p.tool ?? "",
        args: JSON.stringify(p.state?.input ?? {}, null, 1),
        result: typeof p.state?.output === "string" ? p.state.output : JSON.stringify(p.state?.output ?? "", null, 1),
        error: p.state?.status === "error",
      }));
    const stepCost = parts.filter((p) => p.type === "step-finish").reduce((s, p: any) => s + (p.cost ?? 0), 0);
    turnCost += stepCost;
    const tokens = parts.filter((p) => p.type === "step-finish").reduce(
      (acc: any, p: any) => {
        acc.input += p.tokens?.input ?? 0;
        acc.output += p.tokens?.output ?? 0;
        acc.cacheRead += p.tokens?.cache?.read ?? 0;
        return acc;
      },
      { input: 0, output: 0, cacheRead: 0 },
    );

    if (!cur) {
      cur = {
        role: "assistant",
        text: "",
        thinking: "",
        intermediate: [],
        tool_calls: [],
        ts: info.time?.completed ?? info.time?.created ?? Date.now(),
        start_ts: info.time?.created ?? Date.now(),
        model: info.modelID ? `${info.providerID}/${info.modelID}` : "",
        usage: { ...tokens, cost: 0 },
        incomplete: false,
      };
      out.push(cur);
    }
    if (texts.length) {
      if (cur.text) cur.intermediate.push(cur.text);
      cur.text = texts.join("\n");
    }
    if (reasoning.length) cur.thinking += (cur.thinking ? "\n\n" : "") + reasoning.join("\n");
    if (calls.length) cur.tool_calls.push(...calls);
    cur.ts = info.time?.completed ?? info.time?.created ?? cur.ts;
    if (info.modelID) cur.model = `${info.providerID}/${info.modelID}`;
    cur.usage = {
      input: cur.usage.input + tokens.input,
      output: cur.usage.output + tokens.output,
      cacheRead: cur.usage.cacheRead + tokens.cacheRead,
      cost: 0,
    };
    cur.incomplete = !info.time?.completed;
  }

  // 过滤空 assistant 轮（既无文本也无工具调用）
  const filtered = out.filter(
    (m: any) => !(m.role === "assistant" && !m.text && !m.tool_calls.length),
  );
  // 每轮耗时；最后一轮成本在收尾结算
  for (const m of filtered) {
    if (m.role === "assistant") {
      m.elapsed = Math.round(((m.ts - m.start_ts) / 1000) * 10) / 10;
      delete m.start_ts;
    }
  }
  if (cur) cur.usage.cost = turnCost; // 结算最后一轮成本
  return filtered;
}

async function summarizeMessages(runId: string): Promise<any[]> {
  try {
    const sessionId = await resolveSessionId(runId);
    const result: any = await client.session.messages({ path: { id: sessionId } });
    const rows = result.data ?? result;
    return groupRows(rows);
  } catch (err) {
    console.error("[messages]", runId, err);
    return [];
  }
}

// ---------- HTTP 服务 ----------
Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const parts = url.pathname.split("/").filter(Boolean);

    // 自定义工具回调（.opencode/tools/*.ts → 本服务）
    if (req.method === "POST" && parts[0] === "tool" && parts.length === 2) {
      if (req.headers.get("x-tool-token") !== TOOL_TOKEN) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      const name = parts[1];
      try {
        const body = await req.json();
        const result = await handleTool(name, String(body.session_id || ""), (body.args ?? {}) as Record<string, unknown>);
        return Response.json(result);
      } catch (err) {
        return Response.json({ error: String(err) }, { status: 500 });
      }
    }

    if (req.method === "POST" && parts[0] === "sessions" && parts.length === 2) {
      const runId = parts[1];
      try {
        await resolveSessionId(runId);
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
      const agent = String(body.agent || DEFAULT_AGENT);
      const prompt = `[当前排查环境: ${env}]（所有日志/库表/配置查询均按 ${env} 执行；如与之前声明不一致，以此为准）\n\n用户消息: ${text}`;
      remedied.delete(runId);
      try {
        const sessionId = await resolveSessionId(runId);
        const busy = (pendingPrompts.get(runId) || 0) > 0 || activeTurn.get(runId);
        if (busy) {
          // 会话忙：排队，等 session.idle 后自动发出
          const q = promptQueues.get(runId) ?? [];
          promptQueues.set(runId, [...q, prompt]);
        } else {
          void sendPrompt(runId, sessionId, prompt, agent).catch((err) => {
            console.error("[prompt]", runId, err);
            forwardEvent(runId, { type: "error", data: { message: String(err) } });
          });
        }
      } catch (err) {
        console.error("[prompt]", runId, err);
        forwardEvent(runId, { type: "error", data: { message: String(err) } });
        return Response.json({ ok: false, error: String(err) }, { status: 500 });
      }
      return Response.json({ ok: true });
    }

    if (req.method === "GET" && parts[0] === "sessions" && parts[2] === "messages") {
      const runId = parts[1];
      return Response.json(await summarizeMessages(runId));
    }

    if (req.method === "POST" && parts[0] === "sessions" && parts[2] === "abort") {
      const runId = parts[1];
      const sessionId = await resolveSessionId(runId).catch(() => "");
      if (!sessionId) return Response.json({ ok: true });
      try {
        await client.session.abort({ path: { id: sessionId } });
      } catch (err) {
        console.error("[abort]", runId, err);
      }
      pendingPrompts.delete(runId);
      activeTurn.delete(runId);
      return Response.json({ ok: true });
    }

    if (req.method === "GET" && parts[0] === "sessions" && parts[2] === "cost") {
      const runId = parts[1];
      return Response.json({ run_id: runId, cost: await computeCostSafe(runId) });
    }

    if (req.method === "GET" && parts[0] === "sessions" && parts[2] === "status") {
      const runId = parts[1];
      const processing = (pendingPrompts.get(runId) || 0) > 0 || (activeTurn.get(runId) || false);
      const hasSession = (await resolveSessionId(runId).catch(() => "")) !== "";
      return Response.json({ run_id: runId, processing, has_session: hasSession });
    }

    return Response.json({ error: "not found" }, { status: 404 });
  },
});

function sdkVersion(): string {
  try {
    const pkgPath = join(import.meta.dir, "..", "..", "node_modules", "@opencode-ai", "sdk", "package.json");
    return JSON.parse(readFileSync(pkgPath, "utf-8")).version ?? "unknown";
  } catch {
    return "unknown";
  }
}

console.log(`[analysis] opencode sidecar listening on :${PORT}, sessionsDir=${SESSIONS_DIR}, opencodeDb=${OPENCODE_DB}`);
console.log(`[analysis] @opencode-ai/sdk@${sdkVersion()} 事件协议 v${EVENT_PROTOCOL_VERSION}`);

startEventStream();
startWatchdog();
