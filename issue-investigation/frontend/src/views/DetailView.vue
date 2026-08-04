<template>
  <div class="detail-page" v-if="run">
    <div class="detail-head">
      <el-button text size="small" @click="$router.back()">← 返回</el-button>
      <span class="env-tag mono" :class="`env-${run.env}`">{{ run.env.toUpperCase() }}</span>
      <span class="d-title">{{ run.title }}</span>
      <span class="mono d-id">#{{ run.id }}</span>
      <span class="mono d-meta">{{ run.message_count }}/{{ run.turn_limit }} 轮 · {{ run.app }}</span>
    </div>

    <div class="detail-body">
      <!-- 左：对话回放 -->
      <section class="col replay">
        <div class="col-title">对话记录</div>
        <div class="msgs" ref="box">
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <span class="msg-avatar">{{ m.role === 'user' ? '我' : 'AI' }}</span>
            <div class="msg-text" v-html="renderMd(m.text)"></div>
          </div>
          <div class="msgs-empty" v-if="!messages.length">（无对话记录）</div>
        </div>
      </section>

      <!-- 右：报告与产物 -->
      <aside class="col report">
        <div class="col-title">排查报告</div>
        <div class="report-body" v-html="renderMd(report)"></div>
        <div class="col-title artifacts-title">产物</div>
        <div class="artifacts">
          <div v-for="a in artifacts" :key="a.name" class="art-block">
            <div class="art-name mono">{{ a.name }}</div>
            <div class="art-files">
              <span v-for="f in a.files" :key="f" class="art-file mono">{{ f }}</span>
            </div>
          </div>
          <div v-if="!artifacts.length" class="msgs-empty">（暂无产物）</div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { marked } from "marked";
import { getMessages, getReport, getRun, listArtifacts, type Run } from "../api";

const route = useRoute();
const run = ref<Run | null>(null);
const messages = ref<Array<{ role: string; text: string }>>([]);
const report = ref("");
const artifacts = ref<Array<{ name: string; files: string[] }>>([]);

function renderMd(text: string): string {
  return marked.parse(text || "", { breaks: true }) as string;
}

async function load() {
  const id = String(route.params.id);
  run.value = await getRun(id);
  messages.value = await getMessages(id);
  report.value = await getReport(id);
  artifacts.value = await listArtifacts(id);
}

onMounted(load);
watch(() => route.params.id, load);
</script>

<style scoped>
.detail-page {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.detail-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
}

.env-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 5px;
  letter-spacing: 1px;
}

.env-tag.env-dev {
  background: rgba(56, 189, 248, 0.14);
  color: var(--accent-2);
}

.env-tag.env-sit {
  background: rgba(240, 160, 48, 0.14);
  color: var(--warn);
}

.d-title {
  font-weight: 600;
  font-size: 14px;
}

.d-id,
.d-meta {
  font-size: 11px;
  color: var(--ink-faint);
}

.detail-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 0;
}

.col {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.replay {
  border-right: 1px solid var(--line);
}

.col-title {
  flex: 0 0 auto;
  padding: 12px 16px;
  font-size: 12px;
  color: var(--ink-dim);
  letter-spacing: 1px;
  border-bottom: 1px solid var(--line);
  text-transform: uppercase;
}

.msgs {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.msg-avatar {
  flex: 0 0 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
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

.msg-text {
  font-size: 13px;
  line-height: 1.7;
  word-break: break-word;
  min-width: 0;
}

.msg-text :deep(pre) {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  overflow-x: auto;
  font-size: 12px;
  font-family: var(--mono);
}

.msg-text :deep(table) {
  border-collapse: collapse;
  font-size: 12px;
}

.msg-text :deep(th),
.msg-text :deep(td) {
  border: 1px solid var(--line-2);
  padding: 4px 8px;
}

.report {
  overflow-y: auto;
}

.report-body {
  padding: 16px;
  font-size: 13px;
  line-height: 1.75;
  border-bottom: 1px solid var(--line);
}

.report-body :deep(h1),
.report-body :deep(h2),
.report-body :deep(h3) {
  font-size: 14px;
  margin: 12px 0 6px;
}

.report-body :deep(pre) {
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  overflow-x: auto;
  font-size: 12px;
}

.report-body :deep(table) {
  border-collapse: collapse;
  font-size: 12px;
}

.report-body :deep(th),
.report-body :deep(td) {
  border: 1px solid var(--line-2);
  padding: 4px 8px;
}

.artifacts-title {
  border-top: 1px solid var(--line);
}

.artifacts {
  padding: 12px 16px;
}

.art-block {
  margin-bottom: 12px;
}

.art-name {
  font-size: 12px;
  color: var(--accent-2);
  margin-bottom: 4px;
}

.art-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.art-file {
  font-size: 11px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 2px 8px;
  color: var(--ink-dim);
}

.msgs-empty {
  color: var(--ink-faint);
  font-size: 12px;
  padding: 20px 0;
}
</style>
