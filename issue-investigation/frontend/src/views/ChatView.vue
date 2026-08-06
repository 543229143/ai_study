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
            {{ fmtTimeShort(s.updated_at) }} · {{ s.message_count }} 轮
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
        <div class="main-top-right">
          <div class="agent-switch">
            <select
              class="agent-select mono"
              :value="agent"
              title="切换 Agent（会话列表按 Agent 过滤）"
              @change="switchAgent(($event.target as HTMLSelectElement).value)"
            >
              <option v-for="a in agents" :key="a" :value="a">{{ agentLabel(a) }}</option>
            </select>
          </div>
          <router-link to="/config" class="cfg-link mono">配置</router-link>
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
      </div>

      <!-- 消息区：消息不依赖 run 存在即可展示（首条消息乐观回显不被空态挡住） -->
      <div class="messages" ref="msgBox">
        <div v-if="!run && !messages.length" class="empty-state">
          <div class="empty-mark"></div>
          <p class="empty-title">描述你要排查的问题</p>
          <p class="empty-hint">例如：查一下 traceId 95642f860689476c5bbedcef4b329ba8 为什么报错<br />或：lcs 借据 LO1067937042120667136 没有生成还款计划</p>
        </div>

        <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
          <template v-if="m.role === 'user'">
            <div class="msg-content user-bubble">
              <div class="msg-text" v-html="m.html || renderMd(m.text)"></div>
              <div class="msg-time mono" v-if="m.ts">{{ fmtTime(m.ts) }}</div>
            </div>
          </template>
          <template v-else>
            <div class="msg-avatar">AI</div>
            <div class="msg-content">
              <div class="msg-text" v-html="m.html || renderMd(m.text)"></div>

              <!-- 处理详情（pi-web 风格，默认折叠，不含思考过程） -->
              <div v-if="m.intermediate?.length || m.tool_calls?.length" class="details-block">
                <button class="details-toggle" @click="m.collapsed = !m.collapsed">
                  <span class="chevron" :class="{ open: !m.collapsed }">▸</span>
                  <span class="details-label mono">处理详情</span>
                  <span class="details-count mono">
                    · {{ m.intermediate?.length || 0 }} 条消息
                    · {{ m.tool_calls?.length || 0 }} 次工具调用
                  </span>
                </button>
                <div v-if="!m.collapsed" class="details-body">
                  <div v-if="m.intermediate?.length" class="details-section">
                    <div class="details-sec-title mono">中间过程</div>
                    <div v-for="(it, j) in m.intermediate" :key="j" class="details-text">{{ it }}</div>
                  </div>
                  <div v-if="m.tool_calls?.length" class="details-section">
                    <div class="details-sec-title mono">工具调用</div>
                    <div v-for="(tc, j) in m.tool_calls" :key="j" class="tool-call">
                      <button class="tool-call-head" @click="tc.open = !tc.open">
                        <span class="chevron" :class="{ open: tc.open }">▸</span>
                        <span class="tool-call-name mono" :class="{ err: tc.error }">{{ tc.name }}</span>
                        <span v-if="tc.error" class="tool-call-err mono">ERROR</span>
                      </button>
                      <div v-if="tc.open" class="tool-call-body">
                        <div class="tool-call-part" v-if="tc.args && tc.args !== '{}'">
                          <span class="mono tool-call-label">args</span>
                          <pre class="tool-call-pre">{{ tc.args }}</pre>
                        </div>
                        <div class="tool-call-part" v-if="tc.result">
                          <span class="mono tool-call-label">result</span>
                          <pre class="tool-call-pre">{{ tc.result }}</pre>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 模型 + usage + 成本 + 时间脚注 -->
              <div class="msg-foot mono" v-if="m.model || m.usage || m.ts">
                <template v-if="m.model">{{ m.model }}</template>
                <template v-if="m.usage">
                  <span class="foot-sep"> · </span>{{ m.usage.input.toLocaleString() }} in ·
                  {{ m.usage.output.toLocaleString() }} out ·
                  {{ m.usage.cacheRead.toLocaleString() }} cache R ·
                  {{ fmtCost(m.usage.cost) }}
                </template>
                <template v-if="m.elapsed != null"><span class="foot-sep"> · </span>{{ m.elapsed.toFixed(1) }}s</template>
                <template v-if="m.ts"><span class="foot-sep"> · </span>{{ fmtTime(m.ts) }}</template>
              </div>
            </div>
          </template>
        </div>

        <!-- 执行中：只展示流式文本（思考过程完成后再进处理详情） -->
        <div class="msg assistant" v-if="running || streamText">
          <div class="msg-avatar">AI</div>
          <div class="msg-content">
            <div class="gen-stats mono" v-if="running">
              <span class="gen-model">{{ modelName }}</span>
              <span class="gen-down">↓</span>
              <span class="gen-tokens">{{ streamTokens.toLocaleString() }} tokens</span>
              <span class="gen-sep">·</span>
              <span class="gen-speed">{{ streamSpeed.toFixed(1) }} token/s</span>
              <span class="gen-sep">·</span>
              <span class="gen-elapsed">{{ streamElapsed.toFixed(1) }}s</span>
            </div>
            <div class="msg-text" v-if="streamHtml" v-html="streamHtml"></div>
            <div class="thinking-hint mono" v-if="running && !streamText">推理中…</div>

            <!-- 推理中恢复的半成品处理详情（中间过程/工具调用合并进执行中区域，不另起空消息） -->
            <div v-if="(streamIntermediate?.length || streamToolCalls?.length) && streamDetailsOpen" class="details-block stream-details">
              <button class="details-toggle" @click="streamDetailsOpen = !streamDetailsOpen">
                <span class="chevron" :class="{ open: streamDetailsOpen }">▸</span>
                <span class="details-label mono">处理详情</span>
                <span class="details-count mono">
                  · {{ streamIntermediate?.length || 0 }} 条消息
                  · {{ streamToolCalls?.length || 0 }} 次工具调用
                </span>
              </button>
              <div v-if="streamDetailsOpen" class="details-body">
                <div v-if="streamIntermediate?.length" class="details-section">
                  <div class="details-sec-title mono">中间过程</div>
                  <div v-for="(it, j) in streamIntermediate" :key="'s' + j" class="details-text">{{ it }}</div>
                </div>
                <div v-if="streamToolCalls?.length" class="details-section">
                  <div class="details-sec-title mono">工具调用</div>
                  <div v-for="(tc, j) in streamToolCalls" :key="'st' + j" class="tool-call">
                    <button class="tool-call-head" @click="tc.open = !tc.open">
                      <span class="chevron" :class="{ open: tc.open }">▸</span>
                      <span class="tool-call-name mono" :class="{ err: tc.error }">{{ tc.name }}</span>
                      <span v-if="tc.error" class="tool-call-err mono">ERROR</span>
                    </button>
                    <div v-if="tc.open" class="tool-call-body">
                      <div class="tool-call-part" v-if="tc.args && tc.args !== '{}'">
                        <span class="mono tool-call-label">args</span>
                        <pre class="tool-call-pre">{{ tc.args }}</pre>
                      </div>
                      <div class="tool-call-part" v-if="tc.result">
                        <span class="mono tool-call-label">result</span>
                        <pre class="tool-call-pre">{{ tc.result }}</pre>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <button v-else-if="(streamIntermediate?.length || streamToolCalls?.length)" class="details-toggle stream-details-toggle" @click="streamDetailsOpen = true">
              <span class="chevron">▸</span>
              <span class="details-label mono">处理详情</span>
              <span class="details-count mono">
                · {{ streamIntermediate?.length || 0 }} 条消息
                · {{ streamToolCalls?.length || 0 }} 次工具调用
              </span>
            </button>
          </div>
        </div>
      </div>

      <!-- 中断提示横幅 -->
      <div class="interrupt-bar" v-if="interrupted">
        <span class="interrupt-icon">⚠️</span>
        <span class="interrupt-text">{{ interruptText }}</span>
        <button class="resume-btn" :disabled="resuming" @click="resumeLastTurn">
          {{ resuming ? '继续中…' : '继续排查' }}
        </button>
      </div>

      <!-- 本次排查满意度（结论轮后出现；已评价则不打扰） -->
      <div class="rate-bar" v-if="showRate && !rated">
        <span class="rate-label">本次排查满意度</span>
        <el-rate v-model="rating" :max="5" class="rate-stars" @change="onRateChange" />
        <div class="rate-reason" v-if="rating > 0 && rating < 5">
          <el-input
            v-model="rateReason"
            type="textarea"
            :rows="2"
            size="small"
            placeholder="请说明不满意的原因，帮助我们改进"
          />
          <el-button size="small" type="primary" :loading="rateSaving" @click="submitRate(false)">提交评价</el-button>
        </div>
        <span class="rate-note mono" v-else-if="rating === 5">满意，感谢反馈</span>
      </div>
      <div class="rate-bar rated" v-else-if="rated">
        <span class="rate-label">满意度</span>
        <el-rate :model-value="rated.stars" disabled :max="5" class="rate-stars" />
        <span class="rate-note mono">{{ rated.stars }}/5</span>
      </div>

      <!-- 结论缺失警告横幅（自动补救仍缺结论时提示） -->
      <div class="conclusion-warn" v-if="conclusionWarning">
        <span class="interrupt-icon">⚠️</span>
        <span class="interrupt-text">{{ conclusionWarning }}，可继续提问让 AI 补充</span>
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
          <button class="stop-btn" v-if="running && !busy" :disabled="stopping" @click="stop">
            {{ stopping ? '停止中…' : '停止' }}
          </button>
          <button class="send-btn" :disabled="!draft.trim() || busy || (!!run && turnLimitReached)" @click="send">
            {{ busy ? '排查中' : run ? '发送' : '开始排查' }}
          </button>
        </div>
        <div class="input-hint" v-if="turnLimitReached">已达 10 轮沟通上限，点击「新建排查」开始新会话</div>
      </div>
    </main>

    <!-- 强制满意度（10 轮结束） -->
    <el-dialog
      v-model="forceRateVisible"
      :show-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      width="420px"
      class="force-rate-dialog"
    >
      <template #header>
        <div class="force-rate-head">
          <span class="interrupt-icon">⚠️</span>
          <span>本次排查已达 10 轮上限，请评价本次排查满意度</span>
        </div>
      </template>
      <div class="force-rate-body">
        <el-rate v-model="rating" :max="5" class="rate-stars" @change="onRateChange" />
        <el-input
          v-if="rating > 0 && rating < 5"
          v-model="rateReason"
          type="textarea"
          :rows="3"
          size="small"
          placeholder="请说明不满意的原因，帮助我们改进"
        />
        <el-button
          size="small"
          type="primary"
          class="force-rate-submit"
          :disabled="rating === 0"
          :loading="rateSaving"
          @click="submitRate(true)"
        >提交评价</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { marked } from "marked";
import {
  api,
  createRun,
  getAgents,
  getCost,
  getMessages,
  getModelName,
  getRun,
  getRunStatus,
  getSatisfaction,
  listRuns,
  openStream,
  sendMessage,
  submitSatisfaction,
  type Satisfaction,
  type Run,
} from "../api";

interface ToolCallInfo {
  name: string;
  args: string;
  result: string;
  error: boolean;
}

interface UsageInfo {
  input: number;
  output: number;
  cacheRead: number;
  cost: number;
}

interface Msg {
  role: string;
  text: string;
  html?: string;
  ts?: number;
  elapsed?: number;
  model?: string;
  thinking?: string;
  intermediate?: string[];
  tool_calls?: ToolCallInfo[];
  usage?: UsageInfo;
  collapsed?: boolean; // 处理详情默认折叠
}

const env = ref<"dev" | "sit">("dev");
const agents = ref<string[]>(["opencode", "pi"]);
const agent = ref("opencode");
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
const stopping = ref(false);
const aborted = ref(false);
const interrupted = ref(false);

/** 中断横幅文案：有错误记录时展示原因。 */
const interruptText = computed(() => {
  if (run.value?.last_error) {
    return `上次排查因错误中断：${run.value.last_error}`;
  }
  return "上次排查被中断（未完成），可继续排查或重新提问";
});
const conclusionWarning = ref("");

// ---- 满意度评价（run 级单次；10 轮结束强制） ----
const showRate = ref(false);
const forceRateVisible = ref(false);
const rating = ref(0);
const rateReason = ref("");
const rateSaving = ref(false);
const rated = ref<null | { stars: number; reason?: string; forced?: boolean }>(null);

function onRateChange(v: number) {
  if (v < 5) rateReason.value = ""; // 换星后重置原因输入
}

/** done 后判定是否弹出满意度：已有结论回答（本轮文本足够长）且尚未评价。 */
function maybeShowRate() {
  if (!run.value || rated.value) return;
  const msgs = messages.value;
  const lastAi = [...msgs].reverse().find((m: any) => m.role === "assistant");
  const hasConclusion = !!lastAi && (lastAi.text || "").trim().length >= 120;
  const exhausted = (run.value.turn_limit - run.value.message_count) <= 0;
  if (exhausted) {
    forceRateVisible.value = true;
    return;
  }
  if (hasConclusion) showRate.value = true;
}

async function submitRate(forced = false) {
  if (!run.value || rating.value < 1) return;
  rateSaving.value = true;
  try {
    const r = await submitSatisfaction(run.value.id, {
      stars: rating.value,
      reason: rating.value < 5 ? rateReason.value.trim() : "",
      forced,
    });
    rated.value = { stars: r.satisfaction.stars, reason: r.satisfaction.reason, forced: r.satisfaction.forced };
    showRate.value = false;
    forceRateVisible.value = false;
  } catch (err: any) {
    alert(`提交评价失败: ${err.message}`);
  } finally {
    rateSaving.value = false;
  }
}
const resuming = ref(false);
const streamTokens = ref(0);
const streamSpeed = ref(0);
const streamElapsed = ref(0);
/** 推理中恢复的半成品处理详情（合并进执行中区域显示，避免空消息/丢中间过程） */
const streamIntermediate = ref<string[]>([]);
const streamToolCalls = ref<any[]>([]);
const streamDetailsOpen = ref(false);
const modelName = ref("deepseek-v4-flash");
const msgBox = ref<HTMLElement | null>(null);
let copiedTimer: ReturnType<typeof setTimeout> | null = null;
let turnStartAt = 0;
let elapsedTimer: ReturnType<typeof setInterval> | null = null;

/** 估算 token 数：中文≈1 token/字，英文≈1 token/4 字符。 */
function estimateTokens(text: string): number {
  let ascii = 0;
  let other = 0;
  for (const ch of text) {
    if (ch.charCodeAt(0) < 128) ascii++;
    else other++;
  }
  return other + Math.round(ascii / 4);
}

/** 动态刷新生成速度（token/秒）。 */
function updateSpeed() {
  const elapsed = (Date.now() - turnStartAt) / 1000;
  streamSpeed.value = elapsed > 0 ? streamTokens.value / elapsed : 0;
}

/** 错误文案人性化：模型服务繁忙类错误统一提示，不透出内部限流细节。 */
function friendlyError(msg: string): string {
  const s = String(msg || "");
  if (/queue is full|503|busy|限流|rate.?limit|concurrent/i.test(s)) {
    return "模型服务繁忙，请稍后重试";
  }
  return s;
}

/** 执行中动态耗时秒表（250ms 刷新）。 */
function startElapsedTimer() {
  streamElapsed.value = 0;
  stopElapsedTimer();
  elapsedTimer = setInterval(() => {
    if (running.value) streamElapsed.value = (Date.now() - turnStartAt) / 1000;
  }, 250);
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

async function copyRunId() {
  if (!run.value) return;
  let ok = false;
  // 安全上下文（https/localhost）用 Clipboard API；http 局域网访问降级 execCommand
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(run.value.id);
      ok = true;
    } catch {
      /* 降级 */
    }
  }
  if (!ok) {
    try {
      fallbackCopy(run.value.id);
      ok = true;
    } catch {
      /* 剪贴板不可用时忽略 */
    }
  }
  if (ok) {
    copied.value = true;
    if (copiedTimer) clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => (copied.value = false), 1500);
  }
}

function fallbackCopy(text: string) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

async function stop() {
  if (!run.value || stopping.value) return;
  stopping.value = true;
  aborted.value = true;
  try {
    await api(`/runs/${run.value.id}/abort`, { method: "POST" });
  } catch {
    // 后端已推送 user_aborted 事件兜底
  } finally {
    stopping.value = false;
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
const filteredSessions = computed(() =>
  sessions.value.filter(
    (s) => s.env === env.value && (s.engine || "opencode") === agent.value,
  ),
);
const inputPlaceholder = computed(() => {
  if (!run.value) return "描述要排查的问题，附 traceId / 业务单号 + 项目(lps/lcs...) 更准确";
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
      const tokText = deltaBuf.text;
      const tokThink = deltaBuf.thinking;
      if (deltaBuf.text) {
        streamText.value += deltaBuf.text;
        deltaBuf.text = "";
        scheduleMd();
      }
      if (deltaBuf.thinking) {
        thinkingText.value += deltaBuf.thinking;
        deltaBuf.thinking = "";
      }
      if (tokText || tokThink) {
        streamTokens.value += estimateTokens(tokText + tokThink);
        updateSpeed();
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
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}月${d.getDate()}日 ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtTimeShort(ts: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function fmtCost(c: number | undefined): string {
  if (c === undefined || isNaN(c)) return "$-";
  if (c >= 0.01) return `$${c.toFixed(2)}`;
  return `$${c.toFixed(4)}`;
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
    sessions.value = await listRuns(agent.value);
  } catch {
    /* ignore */
  }
}

/** agent 显示名：直接显示引擎名（pi 不用数学符号 π）。 */
function agentLabel(a: string): string {
  return a;
}

/** 切换 agent：重置当前会话视图，会话列表按新 agent 过滤。 */
async function switchAgent(a: string) {
  if (a === agent.value) return;
  agent.value = a;
  disconnect();
  run.value = null;
  messages.value = [];
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  running.value = false;
  turnLimitReached.value = false;
  cost.value = null;
  streamTokens.value = 0;
  streamElapsed.value = 0;
  stopElapsedTimer();
  draft.value = "";
  showRate.value = false;
  forceRateVisible.value = false;
  rated.value = null;
  rating.value = 0;
  rateReason.value = "";
  await loadSessions();
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
  streamTokens.value = 0;
  streamElapsed.value = 0;
  stopElapsedTimer();
  draft.value = "";
  showRate.value = false;
  forceRateVisible.value = false;
  rated.value = null;
  rating.value = 0;
  rateReason.value = "";
}

async function openSession(s: Run) {
  if (run.value && run.value.id === s.id) return;
  disconnect();
  run.value = s;
  env.value = s.env;
  turnLimitReached.value = (s.turn_limit - s.message_count) <= 0;
  // 推理中恢复：run 仍在 processing 时恢复执行中状态（incomplete 轮由 syncFromServer 保留，流式从 WS 继续）
  const st = await getRunStatus(s.id).catch(() => null);
  if (st && st.pending && st.processing && !st.sidecar_unreachable) {
    running.value = true;
    streamTokens.value = 0;
    turnStartAt = Date.now();
    startElapsedTimer();
  }
  await syncFromServer();
  await loadSatisfaction(s.id);
  // 历史中被用户停止的排查：补一条停止标记
  if ((s.timeline || []).some((t) => t.event === "aborted")) {
    messages.value.push({
      role: "assistant",
      text: "> ⏹ 该次排查已被用户停止",
      html: renderMd("> ⏹ 该次排查已被用户停止"),
    });
  }
  cost.value = await getCost(s.id);
  connectStream(s.id);
  await checkInterrupted();
  scrollBottom();
}

/** 加载满意度状态：已评价显示结果；10 轮耗尽且未评价则强制弹窗。 */
async function loadSatisfaction(id: string) {
  rating.value = 0;
  rateReason.value = "";
  showRate.value = false;
  forceRateVisible.value = false;
  try {
    const s = await getSatisfaction(id);
    if (s && typeof s.stars === "number") {
      rated.value = { stars: s.stars, reason: s.reason, forced: s.forced };
      return;
    }
  } catch {
    /* 评价接口失败不阻塞会话 */
  }
  rated.value = null;
  if (run.value && (run.value.turn_limit - run.value.message_count) <= 0) {
    forceRateVisible.value = true; // 已耗尽且未评价 → 强制
    return;
  }
  // 已完成且有结论的历史会话：给出非强制评价入口
  const lastAi = [...messages.value].reverse().find((m: any) => m.role === "assistant");
  if (lastAi && (lastAi.text || "").trim().length >= 120) showRate.value = true;
}

let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempts = 0;
let manuallyClosed = false; // 手动关闭（切换会话/组件卸载）→ 不触发自动重连
let echoDrop = false; // 流式丢弃模式：模型回显 prompt 时整段丢弃（到 tool/message 边界重置）

function connectStream(id: string) {
  // 防重复连接：切换会话/重连时旧连接可能残留（残留连接会重复收事件，导致消息重复显示）
  if (ws) {
    ws.onclose = null;
    ws.onerror = null;
    ws.close();
    ws = null;
  }
  manuallyClosed = false;
  ws = openStream(id);
  ws.onopen = () => {
    wsOk.value = true;
    reconnectAttempts = 0;
    checkInterrupted();
  };
  ws.onclose = () => {
    wsOk.value = false;
    if (!manuallyClosed) scheduleReconnect();
  };
  ws.onerror = () => {
    wsOk.value = false;
  };
  ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
}

function scheduleReconnect() {
  if (!run.value || reconnectTimer) return;
  const delay = Math.min(1000 * 2 ** reconnectAttempts, 15000);
  reconnectAttempts++;
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    if (!run.value) return;
    connectStream(run.value.id);
    await syncFromServer();
  }, delay);
}

function disconnect() {
  manuallyClosed = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
}

/** 中断检测：run 标记 pending 且 agent 未在处理且最后一轮未完成 → 显示"继续排查"横幅。 */
/** 中断检测：run 标记 pending 且 agent 未在处理且最后一轮未完成/有错误 → 显示"继续排查"横幅。 */
async function checkInterrupted() {
  if (!run.value) {
    interrupted.value = false;
    return;
  }
  const status = await getRunStatus(run.value.id);
  if (!status.pending || status.processing || status.sidecar_unreachable) {
    interrupted.value = false;
    return;
  }
  const lastAi = [...messages.value].reverse().find((m) => m.role === "assistant");
  interrupted.value = !lastAi || !!lastAi.incomplete || !!run.value.last_error;
}

/** 手动继续：重发最后一条用户消息（跳过门禁、不计轮次）。 */
async function resumeLastTurn() {
  if (!run.value || resuming.value) return;
  const lastUser = [...messages.value].reverse().find((m) => m.role === "user");
  if (!lastUser || !lastUser.text.trim()) return;
  resuming.value = true;
  interrupted.value = false;
  running.value = true;
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  streamTokens.value = 0;
  turnStartAt = Date.now();
  startElapsedTimer();
  try {
    await sendMessage(run.value.id, lastUser.text.trim(), env.value, true);
    await refreshRun();
  } catch (err: any) {
    running.value = false;
    pushMsg({ role: "assistant", text: `> ❌ 继续排查失败: ${err.message}` });
  } finally {
    resuming.value = false;
  }
  scrollBottom();
}

/** 重连后/打开会话时从服务端同步消息，补回断线期间丢失的事件。
 *  运行中恢复（最终行为）：最后一条 incomplete 轮（半成品）——
 *  - 中间过程/工具调用合并进「执行中」区域的处理详情（可见可展开，不丢）
 *  - 正文由流式区域续传（streamText 以它继续 + WS delta 追加）
 *  不渲染空条目消息（避免"空 AI 消息"怪异感）；done 后 refreshTurn 全量替换。 */
async function syncFromServer() {
  if (!run.value) return;
  try {
    const msgs = await getMessages(run.value.id);
    if (!msgs.length) return;
    let list = msgs.map((m) => ({
      ...m,
      html: renderMd(m.text),
      collapsed: m.role === "assistant",
    }));
    if (running.value) {
      const last = list[list.length - 1];
      if (last.role === "assistant" && last.incomplete) {
        const resume = last.text || "";
        if (resume) {
          streamText.value = resume;
          streamHtml.value = renderMd(resume);
          streamTokens.value = estimateTokens(resume);
        }
        // 中间过程/工具调用并入执行中区域（不渲染空条目）
        streamIntermediate.value = last.intermediate || [];
        streamToolCalls.value = last.tool_calls || [];
        streamDetailsOpen.value = false;
        list = list.slice(0, -1);
      }
    }
    messages.value = list;
  } catch {
    /* 忽略，等下次重连再同步 */
  }
}

async function handleEvent(e: any) {
  switch (e.type) {
    case "user_message":
      // 前端已乐观回显，WS 事件跳过（避免重复）；新一轮开始重置回显丢弃模式
      echoDrop = false;
      break;
    case "text_delta":
      if (aborted.value) break;
      // 丢弃模式：模型回显 prompt（[当前排查环境…]/用户消息: [识别提示…]/原文/补救系统提示）时整段丢弃，
      // 直到段边界（tool_start/tool_end/message_end）重置；完成后 refreshTurn 用分组结果兜底
      // 注：回显段是模型真实输出，消耗 token——丢弃文本同样计入估算，避免"token 停住"假象
      if (echoDrop) {
        streamTokens.value += estimateTokens(e.data.text);
        break;
      }
      if (/用户消息:|\[当前排查环境:|\[识别提示:|系统提示：/.test(e.data.text)) {
        echoDrop = true;
        streamTokens.value += estimateTokens(e.data.text);
        break;
      }
      queueDelta(e.data.text, "");
      break;
    case "message_end":
      echoDrop = false;
      // 每条中间消息结束后插入换行分隔（流式展示时各过程消息分行，避免连成一段）
      if (aborted.value) break;
      queueDelta("\n\n", "");
      break;
    case "tool_start":
    case "tool_end":
      echoDrop = false;
      // 工具调用前后分段（opencode 一轮单条消息多 part，中间无 message_end，需手动分隔）
      if (aborted.value) break;
      queueDelta("\n\n", "");
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
      if (!rated.value) forceRateVisible.value = true; // 10 轮结束强制满意度
      break;
    case "user_aborted":
      flushStream();
      messages.value.push({ role: "assistant", text: "> ⏹ 排查已停止（可继续提问或新建排查）" });
      refreshRun();
      break;
    case "done":
      if (aborted.value) break;
      if (typeof e.data?.cost === "number") cost.value = e.data.cost;
      conclusionWarning.value = e.data?.warning || "";
      flushStream();
      await refreshTurn();
      await refreshRun();
      maybeShowRate();
      break;
    case "error":
      running.value = false;
      pushMsg({ role: "assistant", text: `> ❌ ${friendlyError(e.data.message)}` });
      break;
  }
  scrollBottom();
}

function flushStream() {
  const text = streamText.value.trim();
  const thinking = thinkingText.value.trim();
  // 完成后立即用服务端分组消息替换（含最终答案/处理详情/usage），本地缓冲不再单独入列
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  streamIntermediate.value = [];
  streamToolCalls.value = [];
  streamDetailsOpen.value = false;
  running.value = false;
  streamTokens.value = 0;
  streamElapsed.value = 0;
  stopElapsedTimer();
  void text;
  void thinking;
}

/** 回答完成后从服务端拉取分组消息，替换整条列表（最终答案 + 折叠处理详情 + usage）。
 *  done 事件早于会话落盘：重试直到拉到的最后一轮 assistant 消息带 usage（完成标志）。 */
async function refreshTurn() {
  if (!run.value) return;
  const prevCount = messages.value.length;
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      const msgs = await getMessages(run.value.id);
      const lastAi = [...msgs].reverse().find((m) => m.role === "assistant");
      if (msgs.length > prevCount && lastAi && !lastAi.incomplete) {
        messages.value = msgs.map((m) => ({
          ...m,
          html: renderMd(m.text),
          collapsed: m.role === "assistant",
        }));
        return;
      }
    } catch {
      /* 继续重试 */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
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
  // 文本中显式提到环境时，自动切换顶栏开关（用户明确表达优先于开关当前值）
  if (/\bsit\b/i.test(text)) env.value = "sit";
  else if (/\bdev\b/i.test(text)) env.value = "dev";
  busy.value = true;
  running.value = true;
  aborted.value = false;
  conclusionWarning.value = "";
  streamText.value = "";
  streamHtml.value = "";
  thinkingText.value = "";
  streamTokens.value = 0;
  turnStartAt = Date.now();
  startElapsedTimer();
  // 乐观回显：立即显示用户消息，不等后端建会话/门禁
  pushMsg({ role: "user", text });
  try {
    if (!run.value) {
      // 首条消息：自动创建会话（后端从文本识别 mode/app/查询值；agent 用当前选择的）
      const r = await createRun({ env: env.value, text, engine: agent.value });
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

onMounted(async () => {
  try {
    const r = await getAgents();
    if (r.engines?.length) agents.value = r.engines;
    if (!agents.value.includes(agent.value)) agent.value = agents.value[0];
  } catch {
    /* 默认 opencode */
  }
  loadSessions();
  modelName.value = await getModelName();
});onBeforeUnmount(disconnect);
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
  cursor: pointer;
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

.agent-select {
  max-width: 130px;
  padding: 4px 6px;
  font-size: 11px;
  color: var(--ink);
  background: var(--bg);
  border: 1px solid var(--line-2);
  border-radius: 4px;
  outline: none;
  cursor: pointer;
  transition: all 0.15s;
}

.agent-select:hover {
  border-color: var(--warn);
}

.main-top-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.cfg-link {
  font-size: 11.5px;
  color: var(--ink-dim);
  text-decoration: none;
  padding: 3px 10px;
  border: 1px solid var(--line-2);
  border-radius: 4px;
  transition: all 0.15s;
}

.cfg-link:hover {
  color: var(--ink);
  border-color: var(--warn);
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

/* 用户消息：右对齐气泡 */
.msg.user {
  justify-content: flex-end;
}

.msg.user .msg-content {
  max-width: 70%;
}

.user-bubble {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 12px 12px 4px 12px;
  padding: 10px 14px;
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

.msg.assistant .msg-avatar {
  background: rgba(45, 212, 191, 0.14);
  color: var(--accent);
}

.msg-content {
  flex: 1;
  min-width: 0;
  max-width: 860px;
}

/* AI 消息头：模型名 */
.msg-head {
  font-size: 10.5px;
  color: var(--accent-2);
  margin-bottom: 6px;
  letter-spacing: 0.5px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.msg-head::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 2px;
  background: var(--accent-2);
}

/* AI 消息脚注：usage + 成本 + 时间 */
.msg-foot {
  margin-top: 6px;
  font-size: 10.5px;
  color: var(--ink-faint);
  letter-spacing: 0.3px;
}

.foot-sep {
  color: var(--ink-faint);
}

/* 用户消息时间 */
.msg-time {
  margin-top: 5px;
  font-size: 10.5px;
  color: var(--ink-faint);
  text-align: right;
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

/* 处理详情（pi-web 风格，默认折叠） */
.details-block {
  margin-top: 10px;
}

.details-toggle {
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

.details-toggle:hover {
  border-color: var(--line-2);
  color: var(--ink-dim);
  background: var(--bg-2);
}

.details-label {
  letter-spacing: 1px;
}

.details-count {
  font-size: 10px;
  color: var(--ink-faint);
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

.details-body {
  margin-top: 8px;
  padding: 12px 14px;
  background: rgba(11, 15, 20, 0.6);
  border: 1px solid var(--line);
  border-left: 2px solid var(--line-2);
  border-radius: 3px;
}

/* 中间过程 与 工具调用 上下排列（中间过程在前） */
.details-section {
  margin-bottom: 14px;
}

.details-section:last-child {
  margin-bottom: 0;
}

.details-sec-title {
  font-size: 10px;
  color: var(--ink-faint);
  letter-spacing: 1px;
  margin-bottom: 6px;
}

.details-text {
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-dim);
  white-space: pre-wrap;
  word-break: break-word;
  margin-bottom: 6px;
}

.details-text:last-child {
  margin-bottom: 0;
}

@keyframes breathe {
  0%, 100% { opacity: 0.75; }
  50% { opacity: 1; }
}

/* 工具调用明细：每个工具可单独点开 */
.tool-call {
  margin-bottom: 6px;
  border: 1px solid var(--line);
  border-radius: 3px;
  overflow: hidden;
  background: var(--bg-2);
}

.tool-call:last-child {
  margin-bottom: 0;
}

.tool-call-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--ink-dim);
  font-size: 12px;
  text-align: left;
  transition: background 0.15s;
}

.tool-call-head:hover {
  background: var(--bg-3);
}

.tool-call-name {
  font-size: 11.5px;
  color: var(--accent-2);
}

.tool-call-name.err {
  color: var(--danger);
}

.tool-call-err {
  font-size: 9px;
  color: var(--danger);
  border: 1px solid rgba(242, 84, 91, 0.4);
  padding: 0 5px;
  border-radius: 3px;
}

.tool-call-body {
  border-top: 1px solid var(--line);
}

.tool-call-part {
  padding: 6px 10px;
  border-top: 1px solid var(--line);
}

.tool-call-part:first-child {
  border-top: none;
}

.tool-call-label {
  font-size: 9px;
  color: var(--ink-faint);
  margin-bottom: 3px;
  display: block;
}

.tool-call-pre {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--ink-dim);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
  font-family: var(--mono);
}

.gen-stats {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: 3px;
  background: var(--bg);
  font-size: 11px;
  color: var(--ink-dim);
}

.gen-model {
  color: var(--accent-2);
}

.gen-down {
  color: var(--accent);
  animation: down-bounce 1.2s ease-in-out infinite;
}

@keyframes down-bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(3px); }
}

.gen-tokens {
  color: var(--ink-dim);
}

.gen-sep {
  color: var(--ink-faint);
}

.gen-speed {
  color: var(--accent);
}

.thinking-hint {
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 1px;
}

/* 输入区 */
.interrupt-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 22px 0;
  padding: 9px 14px;
  background: rgba(240, 160, 48, 0.1);
  border: 1px solid rgba(240, 160, 48, 0.35);
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--warn);
}

.interrupt-icon {
  font-size: 13px;
}

.interrupt-text {
  flex: 1;
}

.conclusion-warn {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 22px 0;
  padding: 9px 14px;
  background: rgba(240, 160, 48, 0.1);
  border: 1px solid rgba(240, 160, 48, 0.35);
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--warn);
}

.rate-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 22px 0;
  padding: 9px 14px;
  background: rgba(52, 211, 153, 0.06);
  border: 1px solid rgba(52, 211, 153, 0.25);
  border-radius: 8px;
}

.rate-bar.rated {
  background: rgba(255, 255, 255, 0.02);
  border-color: var(--line-2);
}

.rate-label {
  font-size: 12.5px;
  color: var(--ink-dim);
  flex: 0 0 auto;
}

.rate-stars {
  flex: 0 0 auto;
}

.rate-reason {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}

.rate-note {
  font-size: 12px;
  color: var(--ok);
}

.force-rate-dialog {
  --el-dialog-bg-color: var(--bg-2);
}

.force-rate-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.force-rate-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-items: flex-start;
}

.force-rate-submit {
  align-self: flex-end;
}

.resume-btn {
  flex: 0 0 auto;
  border: 1px solid rgba(240, 160, 48, 0.5);
  background: rgba(240, 160, 48, 0.15);
  color: var(--warn);
  font-size: 12px;
  font-weight: 600;
  padding: 5px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.resume-btn:hover:not(:disabled) {
  background: rgba(240, 160, 48, 0.28);
}

.resume-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

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

.stop-btn {
  flex: 0 0 auto;
  border: 1px solid rgba(242, 84, 91, 0.5);
  background: rgba(242, 84, 91, 0.12);
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
  padding: 9px 18px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}

.stop-btn:hover:not(:disabled) {
  background: rgba(242, 84, 91, 0.22);
}

.stop-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  color: var(--warn);
  font-size: 12px;
  margin-top: 7px;
}
</style>
