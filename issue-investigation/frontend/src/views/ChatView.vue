<template>
  <div class="chat-page">
    <!-- 会话顶栏 -->
    <div class="chat-top" v-if="run">
      <div class="chat-title">
        <span class="status-led" :class="wsConnected ? 'on' : ''"></span>
        <span class="title-text">{{ run.title }}</span>
        <span class="mono run-id">#{{ run.id.slice(9, 17) }}</span>
      </div>
      <div class="env-switch">
        <button
          v-for="e in ['dev', 'sit']"
          :key="e"
          class="env-btn"
          :class="[env === e ? 'active' : '', `env-${e}`]"
          @click="switchEnv(e)"
        >
          {{ e.toUpperCase() }}
        </button>
      </div>
      <div class="turns mono" :class="{ low: remaining <= 2 }">
        {{ remaining }}/{{ run.turn_limit }} 轮
      </div>
    </div>

    <!-- 初始化表单 -->
    <div class="setup" v-if="!run">
      <div class="setup-card">
        <div class="setup-head">
          <span class="setup-title">新建排查</span>
          <span class="setup-sub mono">NEW INVESTIGATION</span>
        </div>
        <div class="setup-grid">
          <el-select v-model="form.app" placeholder="主应用" class="cell">
            <el-option v-for="a in ['lps', 'goa', 'lcs', 'ams']" :key="a" :label="a" :value="a" />
          </el-select>
          <el-select v-model="form.mode" placeholder="排查模式" class="cell">
            <el-option label="traceId" value="trace_id" />
            <el-option label="告警" value="alert" />
            <el-option label="数据核对" value="biz_key" />
          </el-select>
          <el-select v-model="form.scope" placeholder="范围" class="cell">
            <el-option label="仅主应用" value="primary_only" />
            <el-option label="四应用广扫" value="all" />
          </el-select>
        </div>
        <el-input
          v-model="form.query"
          :placeholder="
            form.mode === 'alert'
              ? '粘贴告警 / 报错片段'
              : form.mode === 'biz_key'
                ? '业务键（借据号 / 订单号 / 申请号）'
                : '32 位 traceId'
          "
          class="setup-query mono"
          @keyup.enter="startRun"
        />
        <el-input
          v-model="form.phenomenon"
          placeholder="现象描述（可选）"
          class="setup-query"
        />
        <div class="setup-actions">
          <el-button type="primary" class="start-btn" :loading="starting" @click="startRun">
            开始排查
          </el-button>
        </div>
      </div>
    </div>

    <!-- 消息区 -->
    <div class="messages" ref="msgBox" v-else>
      <div
        v-for="(m, i) in messages"
        :key="i"
        class="msg"
        :class="m.role"
      >
        <div class="msg-avatar">{{ m.role === 'user' ? '我' : 'AI' }}</div>
        <div class="msg-body">
          <div class="msg-text" v-html="renderMd(m.text)"></div>
        </div>
      </div>

      <!-- 流式中的 assistant 消息 -->
      <div class="msg assistant" v-if="streamText || activeTools.length">
        <div class="msg-avatar">AI</div>
        <div class="msg-body">
          <div class="tool-strip" v-if="activeTools.length">
            <div
              v-for="t in activeTools"
              :key="t.name"
              class="tool-chip"
              :class="t.done ? 'done' : t.error ? 'err' : ''"
            >
              <span class="tool-dot"></span>
              <span class="mono tool-name">{{ t.name }}</span>
              <span class="mono tool-time" v-if="t.done">({{ t.cost }}s)</span>
              <span class="tool-spin" v-if="!t.done"></span>
            </div>
          </div>
          <div class="msg-text" v-if="streamText" v-html="renderMd(streamText)"></div>
          <div class="thinking-hint mono" v-if="thinking && !streamText">正在推理…</div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area" v-if="run">
      <div class="input-wrap" :class="{ locked: !canSend }">
        <el-input
          v-model="draft"
          type="textarea"
          :rows="2"
          resize="none"
          :placeholder="inputPlaceholder"
          :disabled="!canSend"
          @keydown.enter.exact.prevent="send"
        />
        <el-button
          type="primary"
          class="send-btn"
          :disabled="!canSend || !draft.trim() || busy"
          @click="send"
        >
          {{ busy ? '排查中…' : '发送' }}
        </el-button>
      </div>
      <div class="input-hint" v-if="!canSend">
        {{ turnLimitReached ? '已达 10 轮沟通上限，请新建会话' : '' }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import { marked } from "marked";
import {
  createRun,
  getMessages,
  getRun,
  listArtifacts,
  openStream,
  sendMessage,
  type Run,
} from "../api";

const env = ref<"dev" | "sit">("dev");
const run = ref<Run | null>(null);
const messages = ref<Array<{ role: string; text: string }>>([]);
const streamText = ref("");
const thinking = ref(false);
const draft = ref("");
const busy = ref(false);
const starting = ref(false);
const wsConnected = ref(false);
const turnLimitReached = ref(false);
const msgBox = ref<HTMLElement | null>(null);

const form = ref({
  app: "lps",
  mode: "trace_id",
  scope: "primary_only",
  query: "",
  phenomenon: "",
});

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
const canSend = computed(() => !!run.value && !busy.value && !turnLimitReached.value && remaining.value > 0);
const inputPlaceholder = computed(() => {
  if (!run.value) return "";
  if (turnLimitReached.value) return "已达上限，请新建会话";
  return "描述要排查的问题… 例如：查这个 traceId 的报错原因 / 再查下 lcs.pilot_loan 这条记录";
});

function renderMd(text: string): string {
  return marked.parse(text || "", { breaks: true }) as string;
}

function scrollBottom() {
  nextTick(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight;
  });
}

async function startRun() {
  if (!form.value.query.trim()) return;
  starting.value = true;
  try {
    const payload: Record<string, unknown> = {
      env: env.value,
      app: form.value.app,
      mode: form.value.mode,
      scope: form.value.scope === "all" ? "all" : "primary_only",
      phenomenon: form.value.phenomenon || undefined,
    };
    if (form.value.mode === "trace_id") payload.trace_id = form.value.query.trim();
    if (form.value.mode === "alert") payload.alert = form.value.query.trim();
    if (form.value.mode === "biz_key") payload.biz_key = form.value.query.trim();
    const r = await createRun(payload);
    run.value = r;
    connectStream(r.id);
    messages.value = await getMessages(r.id);
  } catch (err: any) {
    alert(`创建排查失败: ${err.message}`);
  } finally {
    starting.value = false;
  }
}

function switchEnv(e: "dev" | "sit") {
  env.value = e;
}

function connectStream(id: string) {
  ws = openStream(id);
  ws.onopen = () => {
    wsConnected.value = true;
  };
  ws.onclose = () => {
    wsConnected.value = false;
  };
  ws.onerror = () => {
    wsConnected.value = false;
  };
  ws.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    handleEvent(e);
  };
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
      if (!toolTimer) {
        toolTimer = setInterval(() => {}, 500);
      }
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
      messages.value.push({
        role: "assistant",
        text: `> ⚠️ 该问题不属于排查范围\n\n${e.data.message}`,
      });
      flushStream();
      break;
    case "turn_limit":
      turnLimitReached.value = true;
      messages.value.push({ role: "assistant", text: e.data.message });
      break;
    case "done":
      flushStream();
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

async function send() {
  if (!run.value || !draft.value.trim() || busy.value) return;
  const text = draft.value.trim();
  draft.value = "";
  busy.value = true;
  streamText.value = "";
  activeTools.value = [];
  try {
    await sendMessage(run.value.id, text, env.value);
    run.value = await getRun(run.value.id);
    if ((run.value.turn_limit - run.value.message_count) <= 0) {
      turnLimitReached.value = true;
    }
  } catch (err: any) {
    if (err.status === 429) {
      turnLimitReached.value = true;
      messages.value.push({ role: "assistant", text: err.message });
    } else {
      messages.value.push({ role: "assistant", text: `> ❌ 发送失败: ${err.message}` });
    }
  } finally {
    busy.value = false;
  }
  scrollBottom();
}

onBeforeUnmount(() => {
  if (toolTimer) clearInterval(toolTimer);
  ws?.close();
});
</script>

<style scoped>
.chat-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 顶栏 */
.chat-top {
  flex: 0 0 auto;
  height: 48px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
}

.status-led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.status-led.on {
  background: var(--ok);
  box-shadow: 0 0 8px var(--ok);
}

.title-text {
  font-size: 13px;
  color: var(--ink);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-id {
  font-size: 11px;
  color: var(--ink-faint);
}

.env-switch {
  margin-left: auto;
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
  padding: 5px 16px;
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

.turns {
  font-size: 12px;
  color: var(--ink-dim);
  padding: 0 4px;
}

.turns.low {
  color: var(--warn);
}

/* 初始化表单 */
.setup {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.setup-card {
  width: 560px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
}

.setup-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 18px;
}

.setup-title {
  font-size: 17px;
  font-weight: 600;
}

.setup-sub {
  font-size: 10px;
  color: var(--ink-faint);
  letter-spacing: 2px;
}

.setup-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
  margin-bottom: 12px;
}

.setup-query {
  margin-bottom: 12px;
}

.setup-actions {
  display: flex;
  justify-content: flex-end;
}

.start-btn {
  background: var(--accent);
  border: none;
  color: #06241f;
  font-weight: 600;
}

.start-btn:hover {
  background: #4be0cc;
}

/* 消息区 */
.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 20px 12px;
}

.msg {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: rise 0.25s ease;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.msg-avatar {
  flex: 0 0 34px;
  height: 34px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.msg.user .msg-avatar {
  background: rgba(56, 189, 248, 0.18);
  color: var(--accent-2);
}

.msg.assistant .msg-avatar {
  background: rgba(45, 212, 191, 0.16);
  color: var(--accent);
}

.msg-body {
  flex: 1;
  min-width: 0;
  max-width: 860px;
}

.msg.user .msg-body {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 14px;
  align-self: flex-start;
}

.msg-text {
  line-height: 1.7;
  font-size: 13.5px;
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

/* 工具卡片 */
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

.thinking-hint {
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 1px;
}

/* 输入区 */
.input-area {
  flex: 0 0 auto;
  padding: 10px 20px 16px;
}

.input-wrap {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  max-width: 960px;
  margin: 0 auto;
}

.input-wrap :deep(.el-textarea__inner) {
  min-height: 56px !important;
  padding: 12px 14px;
}

.send-btn {
  height: 56px;
  width: 96px;
  background: var(--accent);
  border: none;
  color: #06241f;
  font-weight: 600;
}

.send-btn:hover {
  background: #4be0cc;
}

.input-wrap.locked {
  opacity: 0.5;
}

.input-hint {
  text-align: center;
  color: var(--warn);
  font-size: 12px;
  margin-top: 6px;
}
</style>
