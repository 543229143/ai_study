<template>
  <div class="cfg-page">
      <div class="cfg-head">
        <el-button text size="small" @click="$router.back()">← 返回</el-button>
        <span class="cfg-title">排查配置</span>
        <span class="cfg-sub mono">config/apps.json · 应用按卡片单独保存</span>
      </div>

    <el-alert
      v-if="message"
      :type="messageType"
      :closable="true"
      class="cfg-alert"
      :title="message"
      @close="message = ''"
    />

    <el-tabs v-model="tab" class="cfg-tabs">
      <!-- 应用配置 -->
      <el-tab-pane label="应用" name="apps">
      <div class="app-toolbar">
        <el-input
          v-model="appFilter"
          size="small"
          clearable
          class="app-filter"
          placeholder="按应用名查询，如 lps"
        />
        <span class="app-count mono">{{ filteredApps.length }}/{{ Object.keys(data.apps).length }} 应用</span>
        <div class="app-add-inline" v-if="addingApp">
          <el-input
            v-model="newAppName"
            size="small"
            autofocus
            class="app-add-input"
            placeholder="应用名（小写，如 fms）"
            @keydown.enter="confirmAdd"
            @keydown.esc="cancelAdd"
          />
          <el-button size="small" type="primary" @click="confirmAdd">确定</el-button>
          <el-button size="small" text @click="cancelAdd">取消</el-button>
        </div>
        <el-button v-else size="small" @click="addingApp = true">+ 添加应用</el-button>
      </div>
        <div class="app-list">
          <div v-for="([name, cfg]) in filteredApps" :key="name" class="app-card">
            <div class="app-card-head">
              <span class="app-name mono">{{ name }}</span>
              <span class="app-saved mono" v-if="savedFlag[name]">✓ 已保存</span>
              <el-button
                size="small"
                type="primary"
                :loading="savingApp === name"
                @click="saveApp(name)"
              >保存</el-button>
              <el-button size="small" text type="danger" @click="removeApp(name)">删除应用</el-button>
            </div>

            <div class="biz-title meta-title">采集元数据</div>
            <div class="meta-grid">
              <span class="meta-item">
                容器名
                <el-input
                  v-model="cfg.container"
                  size="small"
                  class="meta-input"
                  placeholder="留空推导 {app}-service"
                />
              </span>
              <span class="meta-item">
                数据库名
                <el-input
                  v-model="cfg.primary_schema"
                  size="small"
                  class="meta-input"
                  placeholder="新增应用自动同应用名"
                />
              </span>
            </div>

            <div class="biz-title biz-rule-title">业务键规则（单号命中 → 自动带出 表 + 字段）</div>
            <div v-for="(rule, i) in cfg.biz_keys" :key="i" class="biz-row">
              <el-input v-model="rule.pattern" size="small" class="biz-pat" placeholder="如 CR\d{19}（单反斜杠）" />
              <span class="biz-label">表名</span>
              <el-input v-model="rule.table" size="small" class="biz-col" placeholder="ap_fund_appl" />
              <span class="biz-label">字段名</span>
              <el-input v-model="rule.field" size="small" class="biz-col" placeholder="appl_no" />
              <el-button size="small" text type="danger" class="biz-del" @click="cfg.biz_keys.splice(i, 1)">删</el-button>
            </div>
            <el-button size="small" text @click="cfg.biz_keys.push({ pattern: '', table: '', field: '' })">
              + 添加规则
            </el-button>
          </div>
        </div>
      </el-tab-pane>

      <!-- 业务术语 -->
      <el-tab-pane label="业务术语" name="terms">
        <div class="term-list">
          <div v-for="(t, i) in data.terms" :key="i" class="term-row">
            <el-input v-model="t.term" size="small" class="term-name" placeholder="术语，如 授信号" />
            <el-select
              v-model="t.apps"
              multiple
              size="small"
              class="term-apps"
              placeholder="命中后注入的应用（可多选）"
            >
              <el-option v-for="a in appNames" :key="a" :label="a" :value="a" />
            </el-select>
            <el-button size="small" text type="danger" @click="data.terms.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" text @click="data.terms.push({ term: '', apps: [] })">
            + 添加术语
          </el-button>
          <div class="term-save">
            <el-button size="small" type="primary" :loading="savingTerms" @click="saveTerms">保存术语</el-button>
            <span class="app-saved mono" v-if="termsSaved">✓ 已保存</span>
          </div>
          <p class="term-tip">
            用户输入命中术语（如"借据号"）时，自动注入对应应用；命中应用仅作优先扫描，不排除其他应用。
          </p>
        </div>
      </el-tab-pane>

      <!-- 系统术语 -->
      <el-tab-pane label="系统术语" name="systerms">
        <div class="term-list">
          <div v-for="(st, i) in data.system_terms" :key="i" class="term-row sys-term-row">
            <el-input v-model="st.term" size="small" class="term-name" placeholder="用户说的词，如 日志id" />
            <el-input
              v-model="st.meaning"
              size="small"
              type="textarea"
              :rows="1"
              class="sys-meaning"
              placeholder="系统含义，如 ES 的 32 位 traceId（=requestNo）"
            />
            <el-button size="small" text type="danger" @click="data.system_terms.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" text @click="data.system_terms.push({ term: '', meaning: '' })">
            + 添加系统术语
          </el-button>
          <div class="term-save">
            <el-button size="small" type="primary" :loading="savingSysTerms" @click="saveSysTerms">保存系统术语</el-button>
            <span class="app-saved mono" v-if="sysTermsSaved">✓ 已保存</span>
          </div>
          <p class="term-tip">
            用户输入命中系统术语时，注入「术语「X」= 系统含义」提示，让 AI 按系统语义理解（如"日志id"→ ES 32 位 traceId）；不改动用户原文。
          </p>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { getConfig, updateConfig, type PlatformConfig } from "../api";

const tab = ref("apps");
const data = reactive<PlatformConfig>({ apps: {}, terms: [], system_terms: [] });
const newAppName = ref("");
const appFilter = ref("");
const addingApp = ref(false);
const savingApp = ref("");
const savedFlag = reactive<Record<string, boolean>>({});
const savingTerms = ref(false);
const termsSaved = ref(false);
const savingSysTerms = ref(false);
const sysTermsSaved = ref(false);
const message = ref("");
const messageType = ref<"success" | "error">("success");

const appNames = computed(() => Object.keys(data.apps));
const filteredApps = computed(() => {
  const kw = appFilter.value.trim().toLowerCase();
  return Object.entries(data.apps).filter(([name]) => !kw || name.includes(kw));
});

function clone(): PlatformConfig {
  return JSON.parse(JSON.stringify(data));
}

/** 提交整份配置（后端 PUT 全量）；UI 上按应用/术语维度触发。 */
async function persist(thenRefresh: boolean) {
  const r = await updateConfig(clone());
  if (!r.saved) {
    throw new Error((r.errors || []).join("；"));
  }
  if (thenRefresh) {
    const fresh = await getConfig();
    Object.keys(data.apps).forEach((k) => delete data.apps[k]);
    Object.assign(data.apps, fresh.apps);
    data.terms.splice(0, data.terms.length, ...fresh.terms);
    data.system_terms.splice(0, data.system_terms.length, ...(fresh.system_terms || []));
  }
}

function addApp() {
  const name = newAppName.value.trim().toLowerCase();
  if (!name || data.apps[name]) return;
  data.apps[name] = {
    container: "",
    primary_schema: name,
    biz_keys: [],
  };
  newAppName.value = "";
}

function confirmAdd() {
  const name = newAppName.value.trim().toLowerCase();
  if (!name) return;
  if (data.apps[name]) {
    messageType.value = "error";
    message.value = `应用 ${name} 已存在`;
    return;
  }
  addApp();
  addingApp.value = false;
  messageType.value = "success";
  message.value = `应用 ${name} 已添加，点卡片上的「保存」写入配置`;
}

function cancelAdd() {
  addingApp.value = false;
  newAppName.value = "";
}

function removeApp(name: string) {
  delete data.apps[name];
  for (const t of data.terms) {
    t.apps = t.apps.filter((a) => a !== name);
  }
  delete savedFlag[name];
}

/** 按单个应用维度保存（连同术语一起提交，后端为整份配置）。 */
async function saveApp(name: string) {
  savingApp.value = name;
  message.value = "";
  try {
    await persist(true);
    savedFlag[name] = true;
    messageType.value = "success";
    message.value = `应用 ${name} 已保存，即时生效`;
  } catch (err: any) {
    messageType.value = "error";
    message.value = `保存失败: ${err.message}`;
  } finally {
    savingApp.value = "";
  }
}

async function saveTerms() {
  savingTerms.value = true;
  message.value = "";
  try {
    await persist(true);
    termsSaved.value = true;
    messageType.value = "success";
    message.value = "术语已保存，即时生效";
  } catch (err: any) {
    messageType.value = "error";
    message.value = `保存失败: ${err.message}`;
  } finally {
    savingTerms.value = false;
  }
}

async function saveSysTerms() {
  savingSysTerms.value = true;
  message.value = "";
  try {
    await persist(true);
    sysTermsSaved.value = true;
    messageType.value = "success";
    message.value = "系统术语已保存，即时生效";
  } catch (err: any) {
    messageType.value = "error";
    message.value = `保存失败: ${err.message}`;
  } finally {
    savingSysTerms.value = false;
  }
}

onMounted(async () => {
  try {
    const cfg = await getConfig();
    Object.assign(data.apps, cfg.apps);
    data.terms.splice(0, data.terms.length, ...cfg.terms);
    data.system_terms.splice(0, data.system_terms.length, ...(cfg.system_terms || []));
  } catch (err: any) {
    messageType.value = "error";
    message.value = `加载配置失败: ${err.message}`;
  }
});
</script>

<style scoped>
.cfg-page {
  height: 100%;
  padding: 24px 28px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.cfg-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.cfg-title {
  font-size: 18px;
  font-weight: 600;
}

.cfg-sub {
  color: var(--ink-faint);
  font-size: 12px;
}

.cfg-spacer {
  flex: 1;
}

.cfg-alert {
  margin-bottom: 16px;
}

.cfg-tabs {
  flex: 1;
}

.app-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  max-width: 860px;
}

.app-filter {
  width: 260px;
}

.app-count {
  font-size: 12px;
  color: var(--ink-faint);
}

.app-add-inline {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-add-input {
  width: 220px;
}

.app-saved {
  font-size: 11.5px;
  color: var(--ok);
}

.term-save {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.app-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 860px;
}

.app-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.02);
}

.app-card-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}

.app-name {
  font-size: 16px;
  font-weight: 600;
  min-width: 60px;
}

.biz-title {
  font-size: 12.5px;
  color: var(--ink-faint);
  margin-bottom: 8px;
}

.biz-rule-title {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.biz-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 6px;
}

.biz-label {
  font-size: 12px;
  color: var(--ink-faint);
  white-space: nowrap;
  flex-shrink: 0;
}

.biz-pat {
  width: 320px;
}

.biz-col {
  width: 140px;
}

.biz-del {
  width: 40px;
}

.term-list {
  max-width: 860px;
}

.term-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}

.term-name {
  width: 220px;
}

.term-apps {
  width: 420px;
}

.sys-term-row {
  align-items: flex-start;
}

.sys-meaning {
  flex: 1;
}

.sys-meaning .el-textarea__inner {
  min-height: 32px !important;
  resize: vertical;
}

.term-tip {
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--ink-faint);
}

.meta-title {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
  margin-bottom: 6px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-faint);
  font-size: 12.5px;
}

.meta-item-wide {
  grid-column: 1 / -1;
}

.meta-input {
  flex: 1;
}
</style>
