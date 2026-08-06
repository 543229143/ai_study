<template>
  <div class="cfg-page">
    <div class="cfg-head">
      <el-button text size="small" @click="$router.back()">← 返回</el-button>
      <span class="cfg-title">排查配置</span>
      <span class="cfg-sub mono">data/config/apps.json</span>
      <span class="cfg-spacer"></span>
      <el-button size="small" type="primary" :loading="saving" @click="save">保存配置</el-button>
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
        </div>
        <div class="app-list">
          <div v-for="([name, cfg]) in filteredApps" :key="name" class="app-card">
            <div class="app-card-head">
              <span class="app-name mono">{{ name }}</span>
              <span class="app-db">
                数据库
                <el-input
                  v-model="cfg.db_name"
                  size="small"
                  placeholder="留空 = 应用名"
                  class="db-input"
                />
              </span>
              <el-button size="small" text type="danger" @click="removeApp(name)">删除应用</el-button>
            </div>

            <div class="biz-title">业务键规则（单号命中 → 自动带出 表 + 字段）</div>
            <div class="biz-row biz-head">
              <span class="biz-pat">正则</span>
              <span class="biz-col">表名</span>
              <span class="biz-col">字段名</span>
              <span class="biz-del"></span>
            </div>
            <div v-for="(rule, i) in cfg.biz_keys" :key="i" class="biz-row">
              <el-input v-model="rule.pattern" size="small" class="biz-pat" placeholder="如 LO\d{10,}" />
              <el-input v-model="rule.table" size="small" class="biz-col" placeholder="loan" />
              <el-input v-model="rule.field" size="small" class="biz-col" placeholder="loan_no" />
              <el-button size="small" text type="danger" class="biz-del" @click="cfg.biz_keys.splice(i, 1)">删</el-button>
            </div>
            <el-button size="small" text @click="cfg.biz_keys.push({ pattern: '', table: '', field: '' })">
              + 添加规则
            </el-button>
          </div>

          <div class="app-add">
            <el-input v-model="newAppName" size="small" placeholder="新应用名（小写，如 fms）" class="app-add-input" />
            <el-button size="small" @click="addApp">+ 添加应用</el-button>
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
          <p class="term-tip">
            用户输入命中术语（如"借据号"）时，自动注入对应应用；命中应用仅作优先扫描，不排除其他应用。
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
const data = reactive<PlatformConfig>({ apps: {}, terms: [] });
const newAppName = ref("");
const appFilter = ref("");
const saving = ref(false);
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

function addApp() {
  const name = newAppName.value.trim().toLowerCase();
  if (!name || data.apps[name]) return;
  data.apps[name] = { db_name: "", biz_keys: [] };
  newAppName.value = "";
}

function removeApp(name: string) {
  delete data.apps[name];
  for (const t of data.terms) {
    t.apps = t.apps.filter((a) => a !== name);
  }
}

async function save() {
  saving.value = true;
  message.value = "";
  try {
    const r = await updateConfig(clone());
    if (r.saved) {
      messageType.value = "success";
      message.value = "配置已保存，即时生效";
      const fresh = await getConfig();
      Object.keys(data.apps).forEach((k) => delete data.apps[k]);
      Object.assign(data.apps, fresh.apps);
      data.terms.splice(0, data.terms.length, ...fresh.terms);
    } else {
      messageType.value = "error";
      message.value = (r.errors || []).join("；");
    }
  } catch (err: any) {
    messageType.value = "error";
    message.value = `保存失败: ${err.message}`;
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    const cfg = await getConfig();
    Object.assign(data.apps, cfg.apps);
    data.terms.splice(0, data.terms.length, ...cfg.terms);
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

.app-db {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-faint);
  font-size: 12.5px;
}

.db-input {
  width: 160px;
}

.biz-title {
  font-size: 12.5px;
  color: var(--ink-faint);
  margin-bottom: 8px;
}

.biz-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 6px;
}

.biz-row.biz-head {
  font-size: 11.5px;
  color: var(--ink-faint);
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

.app-add {
  display: flex;
  gap: 10px;
}

.app-add-input {
  width: 240px;
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

.term-tip {
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--ink-faint);
}
</style>
