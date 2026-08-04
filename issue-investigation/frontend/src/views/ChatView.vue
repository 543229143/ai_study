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
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: run && run.id === s.id }"
          @click="openSession(s)"
        >
          <div class="si-top">
            <span class="si-title">{{ s.title }}</span>
            <span class="si-env mono" :class="`env-${s.env}`">{{ s.env.toUpperCase() }}</span>
          </div>
          <div class="si-meta mono">
            {{ fmtTime(s.updated_at) }} · {{ s.message_count }} 轮
          </div>
        </div>
        <div v-if="!sessions.length" class="side-empty">
          暂无排查记录<br />输入问题即可开始
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
            <span class="run-meta mono">#{{ run.id.slice(9, 17) }} · {{ run.app }} · {{ remaining }}/{{ run.turn_limit }} 轮</span>
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

      <!-- 消息区 -->
      <div class="messages" ref="msgBox">
        <div v-if="!run" class="empty-state">
          <div class="empty-mark"></div>
          <p class="empty-title">描述你要排查的问题</p>
          <p class="empty-hint">例如：查一下 traceId 95642f… 为什么报错<br />或：lcs 借据 LN123456789012 没有生成还款计划</p>
        </div>

        <template v-else>
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="msg-avatar">{{ m.role === 'user' ? '我' : 'AI' }}</div>
            <div class="msg-content">
              <div class="msg-text" v-html="renderMd(m.text)"></div>
            </div>
          </div>

          <div class="msg assistant" v-if="streamText || activeTools.length">
            <div class="msg-avatar">AI</div>
            <div class="msg-content">
              <div class="tool-strip" v-if="activeTools.length">
                <div v-for="t in activeTools" :key="t.name + t.t0" class="tool-chip" :class="t.done ? 'done' : t.error ? 'err' : ''">
                  <span class="tool-dot"></span>
                  <span class="mono tool-name">{{ t.name }}</span>
                  <span class="mono tool-time" v-if="t.done">{{ t.cost }}s</span>
                  <span class="tool-spin" v-if="!t.done"></span>
                </div>
              </div>
              <div class="msg-text" v-if="streamText" v-html="renderMd(streamText)"></div>
              <div class="thinking mono" v-if="thinking && !streamText">推理中…</div>
            </div>
          </div>
        </template>
      </div>

      <!-- 底部输入 -->
      <div class="input-bar">
        <div class="input-box">
          <textarea
            v-model="draft"
            rows="1"
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
  getMessages,
  getRun,
  listRuns,
  openStream,
  sendMessage,
  type Run,
} from "../api";

const env = ref<"dev" | "sit">("dev");
const run = ref<Run | null>(null);
const sessions = ref<Run[]>([]);
const messages = ref<Array<{ role: string; text: string }>>([]);
const streamText = ref("");
const thinking = ref(false);
const draft = ref("");
const busy = ref(false);
const turnLimitReached = ref(false);
const wsOk = ref(false);
const msgBox = ref<HTMLElement | null>(null);

interface ToolState {
  name: string;
  done: boolean;
  error: boolean;
  cost?: number;
  t0: number;
}
const activeTools = ref<ToolState[]>([]);

let ws: WebSocket | null = null;
let toolTimer: ReturnType<typeof setInterval> | null = null;

const remaining = computed(() => (run.value ? run.value.turn_limit - run.value.message_count : 10));
const inputPlaceholder = computed(() => {
  if (!run.value) return "描述要排查的问题，按回车或点击开始排查…";
  if (turnLimitReached.value) return "已达上限，请新建排查";
  return "继续提问… 例如：再查下这张表 / 换 sit 再看看";
});

function renderMd(text: string): string {
  return marked.parse(text || "", { breaks: true }) as string;
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
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight;
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
  activeTools.value = [];
  turnLimitReached.value = false;
  draft.value = "";
}

async function openSession(s: Run) {
  if (run.value && run.value.id === s.id) return;
  disconnect();
  run.value = s;
  env.value = s.env;
  turnLimitReached.value = (s.turn_limit - s.message_count) <= 0;
  messages.value = await getMessages(s.id);
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
  if (toolTimer) {
    clearInterval(toolTimer);
    toolTimer = null;
  }
  ws?.close();
  ws = null;
}

function handleEvent(e: any) {
  switch (e.type) {
    case "user_message":
      messages.value.push({ role: "user", text: e.data.text });
      break;
    case "text_delta":
      streamText.value += e.data.text;
      break;
    case "thinking_delta":
      thinking.value = true;
      break;
    case "tool_start":
      activeTools.value.push({ name: e.data.tool, done: false, error: false, t0: Date.now() });
      if (!toolTimer) toolTimer = setInterval(() => {}, 500);
      break;
    case "tool_end": {
      const t = activeTools.value.find((x) => x.name === e.data.tool && !x.done);
      if (t) {
        t.done = true;
        t.cost = Math.round((Date.now() - t.t0) / 1000);
      }
      break;
    }
    case "tool_error": {
      const t = activeTools.value.find((x) => x.name === e.data.tool && !x.done);
      if (t) {
        t.error = true;
        t.done = true;
        t.cost = Math.round((Date.now() - t.t0) / 1000);
      }
      break;
    }
    case "gate_rejected":
      messages.value.push({ role: "assistant", text: e.data.message || "该问题不属于排查范围。" });
      flushStream();
      break;
    case "turn_limit":
      turnLimitReached.value = true;
      messages.value.push({ role: "assistant", text: e.data.message });
      break;
    case "done":
      flushStream();
      refreshRun();
      break;
    case "error":
      flushStream();
      messages.value.push({ role: "assistant", text: `> ❌ ${e.data.message}` });
      break;
  }
  scrollBottom();
}

function flushStream() {
  const text = streamText.value.trim();
  if (text) messages.value.push({ role: "assistant", text });
  streamText.value = "";
  thinking.value = false;
  if (toolTimer) {
    clearInterval(toolTimer);
    toolTimer = null;
  }
  setTimeout(() => (activeTools.value = []), 400);
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
  streamText.value = "";
  activeTools.value = [];
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
      messages.value.push({ role: "assistant", text: err.message });
    } else if (run.value) {
      messages.value.push({ role: "assistant", text: `> ❌ 发送失败: ${err.message}` });
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

.si-env {
  flex: 0 0 auto;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}

.si-env.env-dev {
  background: rgba(56, 189, 248, 0.13);
  color: var(--accent-2);
}

.si-env.env-sit {
  background: rgba(240, 160, 48, 0.13);
  color: var(--warn);
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
}

.env-switch {
  display: flex;
  border: 1px solid var(--line-2);
  border-radius: 8px;
  overflow: hidden;
}

.env-btn {
  border: none;
  background: transparent;
  color: var(--ink-dim);
  font-family: var(--mono);
  font-size: 12px;
  padding: 5px 18px;
  cursor: pointer;
  letter-spacing: 1px;
  transition: all 0.15s;
}

.env-btn.active.env-dev {
  background: rgba(56, 189, 248, 0.16);
  color: var(--accent-2);
}

.env-btn.active.env-sit {
  background: rgba(240, 160, 48, 0.16);
  color: var(--warn);
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

.tool-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.tool-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 5px 10px;
  font-size: 12px;
}

.tool-chip.done {
  border-color: rgba(52, 211, 153, 0.35);
}

.tool-chip.err {
  border-color: rgba(242, 84, 91, 0.5);
}

.tool-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-2);
}

.tool-chip.done .tool-dot {
  background: var(--ok);
}

.tool-chip.err .tool-dot {
  background: var(--danger);
}

.tool-name {
  color: var(--ink);
}

.tool-time {
  color: var(--ink-faint);
  font-size: 11px;
}

.tool-spin {
  width: 10px;
  height: 10px;
  border: 2px solid var(--line-2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.thinking {
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
  border: 1px solid var(--line-2);
  border-radius: 12px;
  padding: 8px 8px 8px 16px;
  transition: border-color 0.15s;
}

.input-box:focus-within {
  border-color: var(--accent);
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
  max-height: 160px;
  padding: 6px 0;
}

.input-box textarea::placeholder {
  color: var(--ink-faint);
}

.send-btn {
  flex: 0 0 auto;
  border: none;
  background: var(--accent);
  color: #06241f;
  font-size: 13px;
  font-weight: 650;
  padding: 9px 22px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.send-btn:hover:not(:disabled) {
  background: #4be0cc;
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  color: var(--warn);
  font-size: 12px;
  margin-top: 7px;
}
</style>
