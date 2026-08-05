<template>
  <div class="app-shell">
    <!-- 左侧会话栏（pi-web 风格） -->
    <aside class="sidebar">
      <div class="side-head">
        <div class="logo">
          <span class="logo-dot"></span>
          <span class="logo-name">问题排查台</span>
        </div>
        <button class="new-btn" @click="newSession">
          <span class="plus">＋</span> 新建排查
        </button>
      </div>

      <div class="side-list">
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="session-item"
          :class="{ active: run && run.id === s.id }"
          @click="openSession(s)"
        >
          <div class="si-top">
            <span class="si-title">{{ s.title }}</span>
          </div>
          <div class="si-meta mono">
            {{ fmtTime(s.updated_at) }} · {{ s.message_count }} 轮
          </div>
        </div>
        <div v-if="!filteredSessions.length" class="side-empty">
          <template v-if="sessions.length">暂无 {{ env.toUpperCase() }} 环境的排查记录<br />输入问题即可开始</template>
          <template v-else>暂无排查记录<br />输入问题即可开始</template>
        </div>
      </div>

      <div class="side-foot">
        <router-link to="/history" class="foot-link">历史记录</router-link>
        <span class="foot-status" :class="{ on: wsOk }"></span>
      </div>
    </aside>

    <!-- 主聊天区 -->
    <main class="main">
      <!-- 顶栏：环境切换 + 会话信息 -->
      <div class="main-top">
        <div class="run-info">
          <template v-if="run">
            <span class="run-title">{{ run.title }}</span>
            <span
              class="run-meta mono"
              :class="{ copied: copied }"
              title="双击复制编号"
              @dblclick="copyRunId"
            >#{{ run.id }} · {{ copied ? '已复制 ✓' : costText }}</span>
          </template>
          <span v-else class="run-title idle">未开始排查</span>
        </div>
        <div class="env-switch">
          <button
            v-for="e in ['dev', 'sit']"
            :key="e"
            class="env-btn"
            :class="[env === e ? 'active' : '', `env-${e}`]"
            @click="env = e"
          >
            {{ e.toUpperCase() }}
          </button>
        </div>
      </div>

      <!-- 消息区：消息不依赖 run 存在即可展示（首条消息乐观回显不被空态挡住） -->
      <div class="messages" ref="msgBox">
        <div v-if="!run && !messages.length" class="empty-state">
          <div class="empty-mark"></div>
          <p class="empty-title">描述你要排查的问题</p>
          <p class="empty-hint">例如：查一下 traceId 95642f… 为什么报错<br />或：lcs 借据 LN123456789012 没有生成还款计划</p>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <div class="msg-avatar">{{ m.role === 'user' ? '我' : 'AI' }}</div>
          <div class="msg-content">
            <!-- 历史消息：思考过程默认折叠 -->
            <div v-if="m.role === 'assistant' && m.thinking" class="thinking-block">
              <button class="thinking-toggle" @click="m.collapsed = !m.collapsed">
                <span class="chevron" :class="{ open: !m.collapsed }">▸</span>
                <span class="thinking-label mono">思考过程</span>
                <span class="thinking-state mono">{{ m.collapsed ? '已折叠' : '展开' }}</span>
              </button>
              <div v-if="!m.collapsed" class="thinking-body">{{ m.thinking }}</div>
            </div>
            <div class="msg-text" v-html="m.html || renderMd(m.text)"></div>
          </div>
        </div>

        <!-- 执行中：实时展示流式文本 + 思考过程（完成后自动折叠） -->
        <div class="msg assistant" v-if="running || streamText || thinkingText">
          <div class="msg-avatar">AI</div>
          <div class="msg-content">
            <div v-if="thinkingText" class="thinking-block">
              <div class="thinking-body live">{{ thinkingText }}</div>
            </div>
            <div class="msg-text" v-if="streamHtml" v-html="streamHtml"></div>
            <div class="thinking-hint mono" v-if="running && !streamText && !thinkingText">推理中…</div>
          </div>
        </div>
      </div>

      <!-- 底部输入 -->
      <div class="input-bar">
        <div class="input-box">
          <textarea
            v-model="draft"
            rows="2"
            :disabled="!!run && (turnLimitReached || busy)"
            :placeholder="inputPlaceholder"
            @keydown.enter.exact.prevent="send"
            @input="autoGrow"
          ></textarea>
          <button class="send-btn" :disabled="!draft.trim() || busy || (!!run && turnLimitReached)" @click="send">
            {{ busy ? '排查中' : run ? '发送' : '开始排查' }}
          </button>
        </div>
        <div class="input-hint" v-if="turnLimitReached">已达 10 轮沟通上限，点击「新建排查」开始新会话</div>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { marked } from "marked";
import {
  createRun,
  getCost,
  getMessages,
  getRun,
  listRuns,
  openStream,
  sendMessage,
  type Run,
} from "../api";

interface Msg {
  role: string;
  text: string;
  html?: string;
  thinking?: string;
  collapsed?: boolean; // 历史消息的思考过程是否折叠（默认折叠）
}

const env = ref<"dev" | "sit">("dev");
const run = ref<Run | null>(null);
const sessions = ref<Run[]>([]);
const messages = ref<Msg[]>([]);
const streamText = ref("");
const streamHtml = ref("");
const thinkingText = ref("");
const draft = ref("");
const busy = ref(false);
const running = ref(false);
const turnLimitReached = ref(false);
const wsOk = ref(false);
const cost = ref<number | null>(null);
const copied = ref(false);
const msgBox = ref<HTMLElement | null>(null);
let copiedTimer: ReturnType<typeof setTimeout> | null = null;

async function copyRunId() {
  if (!run.value) return;
  try {
    await navigator.clipboard.writeText(run.value.id);
    copied.value = true;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => (copied.value = false), 1500);
  } catch {
    /* 剪贴板不可用时忽略 */
  }
}

const costText = computed(() => {
  if (cost.value === null || isNaN(cost.value)) return "$-";
  if (cost.value >= 0.01) return `$${cost.value.toFixed(2)}`;
  return `$${cost.value.toFixed(5)}`;
});

let ws: WebSocket | null = null;
// 增量缓冲：事件先入缓冲，rAF 合并后一次更新，减少重渲染
const deltaBuf = { text: "", thinking: "" };
let rafId = 0;
// markdown 防抖渲染
let mdTimer: ReturnType<typeof setTimeout> | null = null;

const remaining = computed(() => (run.value ? run.value.turn_limit - run.value.message_count : 10));
const filteredSessions = computed(() => sessions.value.filter((s) => s.env === env.value));
const inputPlaceholder = computed(() => {
  if (!run.value) return "描述要排查的问题，按回车或点击开始排查…";
  if (turnLimitReached.value) return "已达上限，请新建排查";
  return "继续提问… 例如：再查下这张表 / 换 sit 再看看";
});

function renderMd(text: string): string {
  return marked.parse(text || "", { breaks: true }) as string;
}

/** 事件增量入缓冲，rAF 合并后一次性应用（消除每事件重渲染的卡顿）。 */
function queueDelta(text: string, thinking: string) {
  if (text) deltaBuf.text += text;
  if (thinking) deltaBuf.thinking += thinking;
  if (!rafId) {
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      if (deltaBuf.text) {
        streamText.value += deltaBuf.text;
        deltaBuf.text = "";
        scheduleMd();
      }
      if (deltaBuf.thinking) {
        thinkingText.value += deltaBuf.thinking;
        deltaBuf.thinking = "";
      }
    });
  }
}

/** markdown 渲染防抖（80ms）：流式期间不全量重复解析。 */
function scheduleMd() {
  if (mdTimer) clearTimeout(mdTimer);
  mdTimer = setTimeout(() => {
    mdTimer = null;
    streamHtml.value = renderMd(streamText.value);
  }, 80);
}

function pushMsg(m: Msg) {
  messages.value.push({ ...m, html: m.html || renderMd(m.text) });
}

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function autoGrow(e: Event) {
  const el = e.target as HTMLTextAreaElement;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

function scrollBottom() {
  nextTick(() => {
    if (!msgBox.value) return;
    const el = msgBox.value;
    // 用户上翻查看时不强制拉底，避免流式期间跳动
    if (el.scrollHeight - el.scrollTop - el.clientHeight > 120) return;
    el.scrollTop = el.scrollHeight;
  });
}

async function loadSessions() {
  try {
    sessions.value = await listRuns();
  } catch {
    /* ignore */
  }
}

function newSession() {
  disconnect();
  run.value = null;
  messages.value = [];
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  running.value = false;
  turnLimitReached.value = false;
  cost.value = null;
  draft.value = "";
}

async function openSession(s: Run) {
  if (run.value && run.value.id === s.id) return;
  disconnect();
  run.value = s;
  env.value = s.env;
  turnLimitReached.value = (s.turn_limit - s.message_count) <= 0;
  const msgs = await getMessages(s.id);
  // 加载的历史消息：思考过程默认折叠
  messages.value = msgs.map((m) => ({
    ...m,
    html: renderMd(m.text),
    collapsed: m.role === "assistant" && !!m.thinking,
  }));
  cost.value = await getCost(s.id);
  connectStream(s.id);
  scrollBottom();
}

function connectStream(id: string) {
  ws = openStream(id);
  ws.onopen = () => (wsOk.value = true);
  ws.onclose = () => (wsOk.value = false);
  ws.onerror = () => (wsOk.value = false);
  ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
}

function disconnect() {
  ws?.close();
  ws = null;
}

function handleEvent(e: any) {
  switch (e.type) {
    case "user_message":
      // 前端已乐观回显，WS 事件跳过（避免重复）
      break;
    case "text_delta":
      queueDelta(e.data.text, "");
      break;
    case "thinking_delta":
      queueDelta("", e.data.text);
      break;
    case "gate_rejected":
      running.value = false;
      pushMsg({ role: "assistant", text: e.data.message || "该问题不属于排查范围。" });
      break;
    case "turn_limit":
      running.value = false;
      turnLimitReached.value = true;
      pushMsg({ role: "assistant", text: e.data.message });
      break;
    case "done":
      if (typeof e.data?.cost === "number") cost.value = e.data.cost;
      flushStream();
      refreshRun();
      break;
    case "error":
      running.value = false;
      pushMsg({ role: "assistant", text: `> ❌ ${e.data.message}` });
      break;
  }
  scrollBottom();
}

function flushStream() {
  const text = streamText.value.trim();
  const thinking = thinkingText.value.trim();
  if (text) {
    pushMsg({
      role: "assistant",
      text,
      thinking: thinking || undefined,
      collapsed: true, // 有结果后思考过程自动折叠
    });
  }
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  running.value = false;
}

async function refreshRun() {
  if (!run.value) return;
  try {
    run.value = await getRun(run.value.id);
    turnLimitReached.value = (run.value.turn_limit - run.value.message_count) <= 0;
    loadSessions();
  } catch {
    /* ignore */
  }
}

async function send() {
  const text = draft.value.trim();
  if (!text || busy.value) return;
  draft.value = "";
  busy.value = true;
  running.value = true;
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  // 乐观回显：立即显示用户消息，不等后端建会话/门禁
  pushMsg({ role: "user", text });
  try {
    if (!run.value) {
      // 首条消息：自动创建会话（后端从文本识别 mode/app/查询值）
      const r = await createRun({ env: env.value, text });
      run.value = r;
      connectStream(r.id);
    }
    await sendMessage(run.value.id, text, env.value);
    await refreshRun();
  } catch (err: any) {
    if (err.status === 429) {
      turnLimitReached.value = true;
      pushMsg({ role: "assistant", text: err.message });
    } else if (run.value) {
      pushMsg({ role: "assistant", text: `> ❌ 发送失败: ${err.message}` });
    } else {
      run.value = null;
      alert(`创建排查失败: ${err.message}`);
    }
  } finally {
    busy.value = false;
  }
  scrollBottom();
}

onMounted(loadSessions);
onBeforeUnmount(disconnect);
</script>

<style scoped>
.app-shell {
  height: 100%;
  display: flex;
  min-width: 0;
}

/* ---------- 侧边栏 ---------- */
.sidebar {
  width: 264px;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
  background: var(--bg-2);
}

.side-head {
  padding: 16px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-bottom: 1px solid var(--line);
}

.logo {
  display: flex;
  align-items: center;
  gap: 9px;
}

.logo-dot {
  width: 9px;
  height: 9px;
  border-radius: 3px;
  background: var(--accent);
  box-shadow: 0 0 10px var(--accent);
}

.logo-name {
  font-weight: 650;
  font-size: 14px;
  letter-spacing: 0.3px;
}

.new-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 0;
  border: 1px solid var(--line-2);
  border-radius: 8px;
  background: transparent;
  color: var(--ink);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.new-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(45, 212, 191, 0.06);
}

.plus {
  font-size: 14px;
  font-weight: 600;
}

.side-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item {
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
}

.session-item:hover {
  background: var(--bg-3);
}

.session-item.active {
  background: rgba(45, 212, 191, 0.08);
}

.si-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.si-title {
  font-size: 12.5px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}


.si-meta {
  margin-top: 3px;
  font-size: 10.5px;
  color: var(--ink-faint);
}

.side-empty {
  padding: 30px 10px;
  text-align: center;
  font-size: 12px;
  color: var(--ink-faint);
  line-height: 1.8;
}

.side-foot {
  padding: 10px 14px;
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.foot-link {
  font-size: 12px;
  color: var(--ink-dim);
  text-decoration: none;
}

.foot-link:hover {
  color: var(--accent);
}

.foot-status {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.foot-status.on {
  background: var(--ok);
  box-shadow: 0 0 6px var(--ok);
}

/* ---------- 主区 ---------- */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.main-top {
  flex: 0 0 auto;
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
}

.run-info {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.run-title {
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 400px;
}

.run-title.idle {
  color: var(--ink-faint);
  font-weight: 400;
}

.run-meta {
  font-size: 11px;
  color: var(--ink-faint);
  cursor: copy;
  user-select: all;
}

.run-meta.copied {
  color: var(--ok);
}

.env-switch {
  display: flex;
  border: 1px solid var(--line-2);
  border-radius: 4px;
  overflow: hidden;
  background: var(--bg);
}

.env-btn {
  border: none;
  background: transparent;
  color: var(--ink-dim);
  font-family: var(--mono);
  font-size: 11px;
  padding: 4px 14px;
  cursor: pointer;
  letter-spacing: 1.5px;
  transition: all 0.15s;
}

.env-btn + .env-btn {
  border-left: 1px solid var(--line-2);
}

.env-btn.active.env-dev {
  background: rgba(56, 189, 248, 0.16);
  color: var(--accent-2);
  box-shadow: inset 0 -2px 0 var(--accent-2);
}

.env-btn.active.env-sit {
  background: rgba(240, 160, 48, 0.16);
  color: var(--warn);
  box-shadow: inset 0 -2px 0 var(--warn);
}

/* 消息区 */
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px 22px 10px;
}

.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  text-align: center;
}

.empty-mark {
  width: 46px;
  height: 46px;
  border: 1.5px solid var(--line-2);
  border-radius: 13px;
  margin-bottom: 10px;
  position: relative;
}

.empty-mark::after {
  content: "";
  position: absolute;
  inset: 11px;
  border-radius: 6px;
  background: rgba(45, 212, 191, 0.22);
}

.empty-title {
  font-size: 15px;
  color: var(--ink-dim);
  margin: 0;
}

.empty-hint {
  font-size: 12px;
  color: var(--ink-faint);
  margin: 4px 0 0;
  line-height: 1.9;
}

.msg {
  display: flex;
  gap: 12px;
  margin-bottom: 22px;
  animation: rise 0.22s ease;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(5px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.msg-avatar {
  flex: 0 0 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 650;
}

.msg.user .msg-avatar {
  background: rgba(56, 189, 248, 0.16);
  color: var(--accent-2);
}

.msg.assistant .msg-avatar {
  background: rgba(45, 212, 191, 0.14);
  color: var(--accent);
}

.msg-content {
  flex: 1;
  min-width: 0;
  max-width: 860px;
}

.msg-text {
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--ink);
  word-break: break-word;
}

.msg-text :deep(p) {
  margin: 0 0 8px;
}

.msg-text :deep(p:last-child) {
  margin-bottom: 0;
}

.msg-text :deep(pre) {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  font-family: var(--mono);
  font-size: 12px;
}

.msg-text :deep(code) {
  font-family: var(--mono);
  font-size: 12px;
  background: rgba(120, 150, 190, 0.12);
  padding: 1px 5px;
  border-radius: 4px;
}

.msg-text :deep(pre code) {
  background: none;
  padding: 0;
}

.msg-text :deep(table) {
  border-collapse: collapse;
  font-size: 12px;
  margin: 8px 0;
}

.msg-text :deep(th),
.msg-text :deep(td) {
  border: 1px solid var(--line-2);
  padding: 5px 10px;
}

.msg-text :deep(h1),
.msg-text :deep(h2),
.msg-text :deep(h3) {
  font-size: 14px;
  margin: 12px 0 6px;
}

/* 思考过程块：终端方格风格折叠头 */
.thinking-block {
  margin-bottom: 6px;
}

.thinking-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px 3px 8px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 3px;
  cursor: pointer;
  color: var(--ink-faint);
  font-size: 11px;
  transition: all 0.15s;
}

.thinking-toggle:hover {
  border-color: var(--line-2);
  color: var(--ink-dim);
  background: var(--bg-2);
}

.chevron {
  display: inline-block;
  transition: transform 0.2s ease;
  font-size: 9px;
  color: var(--ink-faint);
}

.chevron.open {
  transform: rotate(90deg);
  color: var(--accent);
}

.thinking-label {
  letter-spacing: 1.5px;
  text-transform: uppercase;
}

.thinking-state {
  font-size: 10px;
  padding-left: 6px;
  border-left: 1px solid var(--line);
  color: var(--ink-faint);
}

.thinking-body {
  margin-top: 6px;
  padding: 12px 14px;
  background: rgba(11, 15, 20, 0.6);
  border: 1px solid var(--line);
  border-left: 2px solid var(--line-2);
  border-radius: 3px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-dim);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow-y: auto;
}

.thinking-body.live {
  animation: breathe 2s ease-in-out infinite;
}

@keyframes breathe {
  0%, 100% { opacity: 0.75; }
  50% { opacity: 1; }
}

.thinking-hint {
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 1px;
}

/* 输入区 */
.input-bar {
  flex: 0 0 auto;
  padding: 12px 22px 18px;
}

.input-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  max-width: 900px;
  margin: 0 auto;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 10px 10px 10px 18px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.input-box:focus-within {
  border-color: rgba(45, 212, 191, 0.45);
  box-shadow: 0 0 0 3px rgba(45, 212, 191, 0.08), 0 4px 24px rgba(0, 0, 0, 0.25);
}

.input-box textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--ink);
  font-family: var(--sans);
  font-size: 13.5px;
  resize: none;
  line-height: 1.6;
  min-height: 72px;
  max-height: 200px;
  padding: 10px 0;
}

.input-box textarea::placeholder {
  color: var(--ink-faint);
}

.send-btn {
  flex: 0 0 auto;
  border: none;
  background: linear-gradient(135deg, var(--accent), #22c9b5);
  color: #06241f;
  font-size: 13px;
  font-weight: 650;
  padding: 9px 24px;
  border-radius: 10px;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(45, 212, 191, 0.25);
  transition: all 0.15s;
}

.send-btn:hover:not(:disabled) {
  filter: brightness(1.08);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(45, 212, 191, 0.35);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  box-shadow: none;
}

.input-hint {
  text-align: center;
  color: var(--warn);
  font-size: 12px;
  margin-top: 7px;
}
</style>
