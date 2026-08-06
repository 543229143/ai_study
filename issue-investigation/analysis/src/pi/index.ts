/**
 * Pi 分析服务：Bun + pi-coding-agent SDK。
 *
 * 职责：
 * - 每 run 一个 AgentSession（持久化到 data/pi/sessions/）
 * - 自定义工具 6 个，通过 HTTP 回调 FastAPI 后端执行排查内核
 * - 会话事件流推送到后端 /events/{run_id}，由后端转发浏览器
 * - 结论完整性校验：agent_end 时缺结论自动补救一轮，仍缺则以 warning 放行
 *
 * 配置：LLM 配置（auth/settings/models）在 config/pi/（项目根，不入库），
 * 会话数据在 data/pi/sessions/（运行时，gitignore）。
 *
 * HTTP API（对后端开放）：
 *   POST /sessions/:runId                 创建会话
 *   POST /sessions/:runId/prompt          {text, env, history} 发送用户消息
 *   GET  /sessions/:runId/messages        返回简化消息列表（页面刷新恢复）
 */
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { Type } from "typebox";
import {
  createAgentSession,
  defineTool,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { validateConclusion, ECHO_MARKERS } from "../conclusion_check.ts";

const PORT = Number(process.env.INV_ANALYSIS_PORT || 8701);
const BACKEND_URL = process.env.INV_BACKEND_URL || "http://127.0.0.1:8600";
const TOOL_TOKEN = process.env.INV_PI_TOOL_TOKEN || "local-dev-token";
const DATA_DIR = process.env.INV_DATA_DIR || join(import.meta.dir, "..", "..", "..", "data");
const AGENT_DIR = process.env.INV_PI_AGENT_DIR || join(DATA_DIR, "pi");
// LLM 配置目录（独立于 ~/.pi/agent 与 data/）
const CONFIG_DIR = process.env.INV_PI_CONFIG_DIR || join(import.meta.dir, "..", "..", "..", "config", "pi");

const SYSTEM_PROMPT = await Bun.file(join(import.meta.dir, "..", "..", "..", "config", "prompt.md")).text();

// ---------- LLM 配置校验：fail-fast，缺失时给出迁移指引 ----------
function checkConfigFiles() {
  const required = ["auth.json", "settings.json", "models.json", "models-store.json"];
  const missing = required.filter((f) => !existsSync(join(CONFIG_DIR, f)));
  if (missing.length > 0) {
    console.error(`[analysis] 缺少 LLM 配置文件: ${missing.join(", ")} (${CONFIG_DIR})`);
    console.error(`[analysis] 请从 data/pi/ 移入这 4 个文件，或写入新的 key（auth.json 的 opencode-go.key）。`);
    process.exit(1);
  }
}
checkConfigFiles();

const modelRuntime = await ModelRuntime.create({
  authPath: join(CONFIG_DIR, "auth.json"),
  modelsPath: join(CONFIG_DIR, "models.json"),
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

function toolResult(name: string, result: unknown, maxLen = 24000) {
  const text = JSON.stringify(result, null, 2);
  return {
    content: [{ type: "text", text: text.length > maxLen ? text.slice(0, maxLen) + "\n...(截断)" : text }],
    details: { tool: name },
  };
}

const str = (d: string) => Type.String({ description: d });
const opt = (d: string) => Type.Optional(Type.String({ description: d }));

function buildTools(runId: string) {
  return [
  defineTool({
    name: "collect_logs",
    label: "采集日志",
    description: "采集 dev/sit 环境 ES 日志（按 traceId/告警/业务键）。结果含各应用命中数与错误数，以及日志原文采样。",
    parameters: Type.Object({
      env: str("环境：dev 或 sit"),
      app: str("主应用：lcs/goa/ams/lps"),
      mode: Type.Optional(Type.Union([Type.Literal("trace_id"), Type.Literal("alert"), Type.Literal("biz_key")], { description: "排查模式" })),
      query: opt("查询值：traceId 或业务键"),
      alert: opt("告警/报错文本（mode=alert 时）"),
      biz_key: opt("业务键（mode=biz_key 时）"),
      apps: Type.Optional(Type.Array(Type.String(), { description: "涉及应用列表（默认仅主应用）" })),
    }),
    execute: async (_id, params) => toolResult("collect_logs", await callTool(runId, "collect_logs", params)),
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
    execute: async (_id, params) => toolResult("scan_code", await callTool(runId, "scan_code", params)),
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
    execute: async (_id, params) => toolResult("nacos_query", await callTool(runId, "nacos_query", params)),
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
    execute: async (_id, params) => toolResult("db_query", await callTool(runId, "db_query", params)),
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
    execute: async (_id, params) => toolResult("run_investigation", await callTool(runId, "run_investigation", params)),
  }),
  defineTool({
    name: "read_artifact",
    label: "读取产物",
    description: "读取当前 run 的中间产物全文（artifacts/ 下相对路径）。当工具返回的采样/摘要不足以判断（如日志采样被截断、需要看完整日志/完整 SQL 结果/完整报告）时使用。",
    parameters: Type.Object({
      path: str("artifacts/ 下相对路径，如 collect_logs-001/logs.json、db_query-001/database.json、run_investigation-001/investigation-report.md"),
      max_chars: Type.Optional(Type.Number({ description: "读取字符数上限（默认 20000，最大 60000，配合 offset 按字符分段读）" })),
      offset: Type.Optional(Type.Number({ description: "起始偏移（配合 max_chars 分段读大文件）" })),
    }),
    execute: async (_id, params) => toolResult("read_artifact", await callTool(runId, "read_artifact", params), 60000),
  }),
  ];
}

// ---------- 会话管理 ----------
type SessionHandle = Awaited<ReturnType<typeof createAgentSession>>;
const sessions = new Map<string, SessionHandle>();
const creating = new Map<string, Promise<SessionHandle>>();

/** 获取会话：内存 → 历史恢复 → 新建；并发去重（同一 run 只创建一个 AgentSession）。 */
function getOrCreate(runId: string): Promise<SessionHandle> {
  const existing = sessions.get(runId);
  if (existing) return Promise.resolve(existing);
  let p = creating.get(runId);
  if (!p) {
    p = (async () => {
      try {
        return await resumeSession(runId);
      } catch {
        return await createSession(runId);
      }
    })()
      .then((h) => {
        sessions.set(runId, h);
        return h;
      })
      .finally(() => creating.delete(runId));
    creating.set(runId, p);
  }
  return p;
}

async function createSession(runId: string) {
  const sessionDir = join(AGENT_DIR, "sessions", `run-${runId}`);
  const sessionManager = SessionManager.create(join(DATA_DIR, "pi"), sessionDir);
  const loader = new DefaultResourceLoader({
    cwd: join(DATA_DIR, "pi"),
    agentDir: CONFIG_DIR,
    systemPromptOverride: () => SYSTEM_PROMPT,
  });
  await loader.reload();

  const handle = await createAgentSession({
    cwd: join(DATA_DIR, "pi"),
    agentDir: CONFIG_DIR,
    modelRuntime,
    customTools: buildTools(runId),
    noTools: "builtin",
    tools: ["collect_logs", "scan_code", "nacos_query", "db_query", "run_investigation", "read_artifact"],
    resourceLoader: loader,
    sessionManager,
  });
  const { session } = handle;

  subscribeSession(runId, handle);

  sessions.set(runId, handle);
  return handle;
}

/** 订阅会话事件：agent_end 前做结论完整性校验（缺结论→自动补救一轮；仍缺→done 带 warning）。 */
function subscribeSession(runId: string, handle: SessionHandle) {
  handle.session.subscribe((event) => {
    const mapped = mapEvent(event);
    if (mapped.type === "done") {
      void concludeTurn(runId, handle, mapped);
    } else {
      forwardEvent(runId, mapped);
    }
  });
}

/** 本轮是否已自动补救过（每轮用户提问最多补救 1 次，新提问复位）。 */
const remedied = new Map<string, boolean>();

const REMEDY_PROMPT = (reason: string) =>
  `系统提示：你的上一条回答未通过结论完整性检查：${reason}。` +
  (reason.includes("多余断言")
    ? `请重新输出「结论」小节：只保留根因/置信度/证据要点，删除"无需干预/无需操作"类总结断言，在证据链与结论处收尾，不要重复排查过程。`
    : `请只补充输出缺失的「结论」小节（根因/置信度/证据要点）或「待补线索」小节（还需什么信息），` +
      `不要重复已输出的排查过程与结论。`);

/** 取会话状态中最后一条 assistant 消息文本（本轮最终答案）。 */
function lastAssistantText(handle: SessionHandle): string {
  const msgs = handle.session.agent?.state?.messages ?? [];
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i]?.role === "assistant") return extractText(msgs[i]);
  }
  return "";
}

/** 取会话状态中最后一条 user 消息文本（校验"多余断言"是否算多余）。 */
function lastUserText(handle: SessionHandle): string {
  const msgs = handle.session.agent?.state?.messages ?? [];
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i]?.role === "user") return extractText(msgs[i]);
  }
  return "";
}

/** agent_end → 校验结论；通过则 done；缺结论自动补救一轮（不计 message_count），仍缺则 done 带 warning。 */
async function concludeTurn(runId: string, handle: SessionHandle, doneEvent: any) {
  const v = validateConclusion(lastAssistantText(handle), { userText: lastUserText(handle) });
  if (v.ok) {
    forwardEvent(runId, doneEvent);
    return;
  }
  if (remedied.get(runId)) {
    forwardEvent(runId, {
      ...doneEvent,
      data: { ...(doneEvent.data || {}), warning: v.reason },
    });
    return;
  }
  remedied.set(runId, true);
  pendingPrompts.set(runId, (pendingPrompts.get(runId) || 0) + 1);
  touchActivity(runId);
  try {
    const prompt = REMEDY_PROMPT(v.reason);
    if (handle.session.isStreaming) {
      await handle.session.followUp(prompt);
    } else {
      await handle.session.prompt(prompt);
    }
  } catch (err) {
    console.error("[concludeTurn remedy]", runId, err);
    forwardEvent(runId, {
      ...doneEvent,
      data: { ...(doneEvent.data || {}), warning: v.reason },
    });
  } finally {
    const n = (pendingPrompts.get(runId) || 1) - 1;
    if (n <= 0) pendingPrompts.delete(runId);
    else pendingPrompts.set(runId, n);
  }
}

async function getSession(runId: string): Promise<SessionHandle> {
  return getOrCreate(runId);
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
    cwd: join(DATA_DIR, "pi"),
    agentDir: CONFIG_DIR,
    systemPromptOverride: () => SYSTEM_PROMPT,
  });
  await loader.reload();

  const handle = await createAgentSession({
    cwd: join(DATA_DIR, "pi"),
    agentDir: CONFIG_DIR,
    modelRuntime,
    customTools: buildTools(runId),
    noTools: "builtin",
    tools: ["collect_logs", "scan_code", "nacos_query", "db_query", "run_investigation", "read_artifact"],
    resourceLoader: loader,
    sessionManager: SessionManager.open(files[0], sessionDir),
  });
  subscribeSession(runId, handle);
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
// ---------- 事件协议（升级 pi 后必核对的字段名） ----------
/**
 * pi 会话事件 → 平台事件的字段映射。
 * pi 升级若改了事件类型/字段名，这里会静默失效（编译不报错），
 * 升级后须按 README「Pi 升级 SOP」逐项核对本表。
 */
const EVENT_PROTOCOL = {
  piMessageUpdate: "message_update",
  piTextDelta: "text_delta",
  piThinkingDelta: "thinking_delta",
  piToolStart: "tool_execution_start",
  piToolEnd: "tool_execution_end",
  piMessageEnd: "message_end",
  piAgentEnd: "agent_end",
  outTextDelta: "text_delta",
  outThinkingDelta: "thinking_delta",
  outToolStart: "tool_start",
  outToolEnd: "tool_end",
  outDone: "done",
} as const;
const EVENT_PROTOCOL_VERSION = "1.0";

function mapEvent(event: any): { type: string; data: any } {
  switch (event.type) {
    case EVENT_PROTOCOL.piMessageUpdate: {
      const ae = event.assistantMessageEvent;
      if (ae?.type === EVENT_PROTOCOL.piTextDelta)
        return { type: EVENT_PROTOCOL.outTextDelta, data: { text: ae.delta } };
      if (ae?.type === EVENT_PROTOCOL.piThinkingDelta)
        return { type: EVENT_PROTOCOL.outThinkingDelta, data: { text: ae.delta } };
      return { type: EVENT_PROTOCOL.piMessageUpdate, data: {} };
    }
    case EVENT_PROTOCOL.piToolStart:
      return { type: EVENT_PROTOCOL.outToolStart, data: { tool: event.toolName } };
    case EVENT_PROTOCOL.piToolEnd:
      return { type: EVENT_PROTOCOL.outToolEnd, data: { tool: event.toolName, isError: event.isError } };
    case EVENT_PROTOCOL.piMessageEnd:
      return { type: "message_end", data: {} };
    case EVENT_PROTOCOL.piAgentEnd:
      return { type: EVENT_PROTOCOL.outDone, data: {} };
    default:
      return { type: "ignored", data: {} };
  }
}

// ---------- 事件批量推送（60ms 合并一次，减少 HTTP 请求与卡顿） ----------
const eventQueues = new Map<string, any[]>();
const eventTimers = new Map<string, ReturnType<typeof setInterval>>();
const pendingPrompts = new Map<string, number>(); // runId -> 进行中的 prompt 数
const lastActivity = new Map<string, number>(); // runId -> 最近一次事件时间

const IDLE_TIMEOUT_MS = Number(process.env.INV_IDLE_TIMEOUT_MS || 180000); // 180s 无事件视为卡死

function touchActivity(runId: string) {
  lastActivity.set(runId, Date.now());
}

/** 看护：运行中（有未完成 prompt）且超过 IDLE_TIMEOUT_MS 无事件 → 自动停止。 */
function startWatchdog() {
  setInterval(() => {
    const now = Date.now();
    for (const [runId, pending] of pendingPrompts) {
      if (pending <= 0) continue;
      const last = lastActivity.get(runId) ?? now;
      if (now - last <= IDLE_TIMEOUT_MS) continue;
      const h = sessions.get(runId);
      console.error(`[watchdog] run ${runId} 无事件 ${(now - last) / 1000}s，自动停止`);
      if (h) {
        h.session.abort().catch(() => {});
      }
      pendingPrompts.delete(runId);
      forwardEvent(runId, {
        type: "error",
        data: { message: "排查长时间无响应（可能为网络/模型超时），已自动停止，请重试" },
      });
    }
  }, 20000);
}

/** 累计会话 token 成本（USD）：累加各 assistant 消息 usage.cost.total。 */
function computeCost(runId: string): number {
  let total = 0;
  try {
    const h = sessions.get(runId);
    if (h) {
      const msgs = h.session.agent?.state?.messages ?? [];
      for (const m of msgs) {
        if (m.role === "assistant" && m.usage?.cost?.total) total += m.usage.cost.total;
      }
      return total;
    }
  } catch {
    /* fallthrough 到文件解析 */
  }
  const files = listJsonlFiles(join(AGENT_DIR, "sessions", `run-${runId}`));
  if (files.length === 0) return 0;
  for (const line of readFileSync(files[0], "utf-8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (entry.type !== "message") continue;
      const m = entry.message ?? {};
      if (m.role === "assistant" && m.usage?.cost?.total) total += m.usage.cost.total;
    } catch {
      /* 跳过损坏行 */
    }
  }
  return total;
}

function forwardEvent(runId: string, ev: { type: string; data: any }) {
  if (ev.type === "ignored") return;
  touchActivity(runId);
  if (ev.type === "done") {
    // 每轮回答完成时动态带出累计成本
    ev.data = { ...(ev.data || {}), cost: Number(computeCost(runId).toFixed(6)) };
  }
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
    // 失败时把事件放回队列尾部，避免丢失
    const cur = eventQueues.get(runId) ?? [];
    eventQueues.set(runId, [...cur, ...q]);
    console.error("[forwardEvent]", runId, err);
  }
}

function summarizeMessages(session: SessionHandle, runId: string): any[] {
  const stateMsgs = session.agent?.state?.messages ?? [];
  if (stateMsgs.length > 0) return groupMessages(stateMsgs);
  const file = listJsonlFiles(join(AGENT_DIR, "sessions", `run-${runId}`));
  if (file.length > 0) return parseSessionFile(file[0]);
  return [];
}

function parseSessionFile(path: string): any[] {
  const entries: any[] = [];
  for (const line of readFileSync(path, "utf-8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (entry.type === "message") entries.push(entry.message ?? {});
    } catch {
      /* 跳过损坏行 */
    }
  }
  return groupMessages(entries);
}

/** 去掉 sidecar 注入的环境头、"用户消息:"前缀与平台注入的 [识别提示: ...] 块，还原用户原话。 */
function stripUserPrefix(text: string): string {
  let t = text.trim();
  if (t.startsWith("[当前排查环境:")) {
    const idx = t.indexOf("用户消息:");
    if (idx !== -1) t = t.slice(idx + "用户消息:".length);
  }
  while (t.startsWith("用户消息:")) {
    t = t.replace(/^用户消息:\s*/, "");
  }
  // 剥掉环境头/"用户消息:"后可能残留前导空格（"用户消息: [识别提示...]"），先归位再剥块
  t = t.trim();
  while (/^\[识别提示:[^\]]*\]/.test(t)) {
    t = t.replace(/^\[识别提示:[^\]]*\]\s*/, "").trim();
  }
  return t.trim();
}

/**
 * 按"轮次"分组：一个用户问题 = 一轮。
 * - user 消息：原话 + 时间戳
 * - assistant 轮：最终答案(text) + 处理详情（thinking/intermediate/tool_calls）+ usage + model + 时间戳
 */
function groupMessages(entries: any[]): any[] {
  // 第一遍：收集全部 toolResult（结果在 toolCall 之后到达，须先全量收集再回填）
  const toolResults = new Map<string, any>();
  for (const m of entries) {
    if (m.role !== "toolResult") continue;
    for (const c of m.content ?? []) {
      const r = c?.toolCallResult;
      if (r?.toolCallId) toolResults.set(r.toolCallId, r);
      const tid = r?.toolCallId || m.toolCallId;
      if (tid) {
        toolResults.set(tid, {
          toolCallId: tid,
          output: typeof c === "string" ? c : c?.text ?? r?.output ?? "",
          isError: !!r?.isError || !!m.isError,
        });
      }
    }
  }

  // 第二遍：按轮次分组
  const out: any[] = [];
  let cur: any = null;

  for (const m of entries) {
    const role = m.role;
    if (role === "toolResult") continue;
    if (role === "user") {
      const text = stripUserPrefix(extractText(m));
      // 仅去重紧邻的重复（自动续跑重发同一消息）；隔了 assistant 回复的相同提问保留
      const last = out[out.length - 1];
      if (last && last.role === "user" && last.text === text) {
        continue;
      }
      out.push({ role: "user", text, ts: m.timestamp });
      cur = null;
      continue;
    }
    if (role !== "assistant") continue;

    const rawText = extractText(m);
    // 展示层过滤回显段（模型空回复时复述用户消息/平台注入前缀）
    const text = ECHO_MARKERS.some((mark) => rawText.includes(mark)) ? "" : rawText;
    const thinking = extractThinking(m);
    const calls = (m.content ?? [])
      .filter((c: any) => c?.type === "toolCall")
      .map((c: any) => {
        const r = toolResults.get(c.id) ?? {};
        return {
          name: c.name ?? "",
          args:
            typeof c.arguments === "string"
              ? c.arguments
              : JSON.stringify(c.arguments ?? "", null, 1),
          result:
            typeof r.output === "string"
              ? r.output
              : JSON.stringify(r.output ?? "", null, 1),
          error: !!r.isError,
        };
      });

    if (!cur) {
      cur = {
        role: "assistant",
        text: "",
        thinking: "",
        intermediate: [],
        tool_calls: [],
        ts: m.timestamp,
        start_ts: m.timestamp,
        model: m.model ?? "",
        usage: null,
      };
      out.push(cur);
    }
    if (text) {
      if (cur.text) cur.intermediate.push(cur.text);
      cur.text = text;
    }
    if (thinking) cur.thinking += (cur.thinking ? "\n\n" : "") + thinking;
    if (calls.length) cur.tool_calls.push(...calls);
    cur.ts = m.timestamp;
    if (m.model) cur.model = m.model;
    if (m.usage) {
      cur.usage = {
        input: m.usage.input ?? 0,
        output: m.usage.output ?? 0,
        cacheRead: m.usage.cacheRead ?? 0,
        cost: m.usage.cost?.total ?? 0,
      };
    }
  }
  // 过滤空 assistant 轮（既无文本也无工具调用）
  const filtered = out.filter(
    (m: any) => !(m.role === "assistant" && !m.text && !m.tool_calls.length),
  );

  // 每轮处理耗时（秒）：该轮最后一条 assistant 消息 - 该轮第一条（毫秒时间戳）
  for (const m of filtered) {
    if (m.role === "assistant" && m.start_ts) {
      m.elapsed = Math.round(((m.ts - m.start_ts) / 1000) * 10) / 10;
      delete m.start_ts;
    }
  }

  // 中断检测：最后一条原始条目不是"stop"结尾的 assistant 消息 → 最后一轮未完成
  // （重启/被杀时文件通常停在 toolUse 消息、toolResult 或 user 消息之后）
  const lastRaw = entries[entries.length - 1];
  const lastTurnIncomplete = !lastRaw
    || lastRaw.role === "user"
    || lastRaw.role === "toolResult"
    || (lastRaw.role === "assistant" && lastRaw.stopReason !== "stop");
  if (filtered.length) {
    const last = filtered[filtered.length - 1];
    if (last.role === "assistant") {
      last.incomplete = lastTurnIncomplete;
    }
  }
  return filtered;
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

function extractThinking(m: any): string {
  const content = m.content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((c: any) => c?.type === "thinking")
    .map((c: any) => c.thinking ?? "")
    .join("\n");
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
        await getOrCreate(runId);
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
      remedied.delete(runId); // 新提问恢复一次结论补救机会
      const run = async () => {
        pendingPrompts.set(runId, (pendingPrompts.get(runId) || 0) + 1);
        touchActivity(runId);
        try {
          if (handle.session.isStreaming) {
            await handle.session.followUp(prompt);
          } else {
            await handle.session.prompt(prompt);
          }
        } finally {
          const n = (pendingPrompts.get(runId) || 1) - 1;
          if (n <= 0) pendingPrompts.delete(runId);
          else pendingPrompts.set(runId, n);
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

    if (req.method === "POST" && parts[0] === "sessions" && parts[2] === "abort") {
      const runId = parts[1];
      const h = sessions.get(runId);
      if (!h) return Response.json({ ok: true });
      try {
        await h.session.abort();
      } catch (err) {
        console.error("[abort]", runId, err);
      }
      return Response.json({ ok: true });
    }

    if (req.method === "GET" && parts[0] === "sessions" && parts[2] === "cost") {
      const runId = parts[1];
      return Response.json({ run_id: runId, cost: Number(computeCost(runId).toFixed(6)) });
    }

    if (req.method === "GET" && parts[0] === "sessions" && parts[2] === "status") {
      const runId = parts[1];
      // processing：该 run 是否仍有未完成的 prompt（重启后内存清空 → false）
      const processing = (pendingPrompts.get(runId) || 0) > 0;
      const hasSession = sessions.has(runId);
      return Response.json({ run_id: runId, processing, has_session: hasSession });
    }

    return Response.json({ error: "not found" }, { status: 404 });
  },
});

function piSdkVersion(): string {
  try {
    const pkgPath = join(
      import.meta.dir, "..", "..", "node_modules", "@earendil-works", "pi-coding-agent", "package.json",
    );
    return JSON.parse(readFileSync(pkgPath, "utf-8")).version ?? "unknown";
  } catch {
    return "unknown";
  }
}

console.log(`[analysis] pi sidecar listening on :${PORT}, configDir=${CONFIG_DIR}, sessionsDir=${AGENT_DIR}`);
console.log(`[analysis] pi-coding-agent@${piSdkVersion()} 事件协议 v${EVENT_PROTOCOL_VERSION}`);

startWatchdog();
