<template>
  <div class="history-page">
    <div class="history-head">
      <el-button text size="small" @click="$router.back()">← 返回</el-button>
      <span class="h-title">历史排查记录</span>
      <select
        class="agent-select mono"
        :value="agent"
        title="按 Agent 过滤"
        @change="agent = ($event.target as HTMLSelectElement).value; load()"
      >
        <option v-for="a in agents" :key="a" :value="a">{{ agentLabel(a) }}</option>
      </select>
      <span class="h-sub mono">{{ runs.length }} SESSIONS</span>
      <el-button size="small" text @click="load" :loading="loading">刷新</el-button>
    </div>
    <div class="history-list" v-if="runs.length">
      <div
        v-for="r in runs"
        :key="r.id"
        class="row"
        @click="go(r.id)"
      >
        <div class="row-main">
          <span class="row-title">{{ r.title }}</span>
          <span class="mono row-meta">#{{ r.id.slice(9, 17) }} · {{ r.app }}</span>
        </div>
        <div class="row-side">
          <span class="mono row-turns">{{ r.message_count }}/{{ r.turn_limit }} 轮</span>
          <span class="row-time mono">{{ fmt(r.created_at) }}</span>
          <span class="row-arrow">→</span>
        </div>
      </div>
    </div>
    <div class="empty" v-else-if="!loading">
      <div class="empty-mark"></div>
      <p>暂无排查记录</p>
      <router-link to="/" class="empty-link">开始第一次排查 →</router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getAgents, listRuns, useGoDetail, type Run } from "../api";

const runs = ref<Run[]>([]);
const loading = ref(false);
const agents = ref<string[]>(["opencode", "pi"]);
const agent = ref("opencode");
const go = useGoDetail();

/** agent 显示名：pi 显示为数学符号 π。 */
function agentLabel(a: string): string {
  return a === "pi" ? "π" : a;
}

function fmt(ts: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function load() {
  loading.value = true;
  try {
    runs.value = await listRuns(agent.value);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    const r = await getAgents();
    if (r.engines?.length) agents.value = r.engines;
    if (!agents.value.includes(agent.value)) agent.value = agents.value[0];
  } catch {
    /* 默认 opencode */
  }
  load();
});
</script>

<style scoped>
.history-page {
  height: 100%;
  padding: 24px 28px;
  overflow-y: auto;
}

.history-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 18px;
}

.h-title {
  font-size: 18px;
  font-weight: 600;
}

.h-sub {
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 2px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all 0.15s;
}

.row:hover {
  border-color: var(--line-2);
  background: var(--bg-2);
  transform: translateX(2px);
}

.row-main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}


.row-title {
  font-size: 13.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

.row-meta {
  font-size: 11px;
  color: var(--ink-faint);
}

.row-side {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 0 0 auto;
}

.row-turns {
  font-size: 11px;
  color: var(--ink-dim);
}

.row-time {
  font-size: 12px;
  color: var(--ink-dim);
}

.row-arrow {
  color: var(--ink-faint);
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 90px;
  color: var(--ink-faint);
}

.empty-mark {
  width: 42px;
  height: 42px;
  border: 2px solid var(--line-2);
  border-radius: 12px;
  margin-bottom: 14px;
  position: relative;
}

.empty-mark::after {
  content: "";
  position: absolute;
  inset: 10px;
  border-radius: 5px;
  background: rgba(45, 212, 191, 0.25);
}

.empty-link {
  color: var(--accent);
  text-decoration: none;
  margin-top: 6px;
}
</style>
