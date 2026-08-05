# 问题排查平台

基于 pi-agent 内核 + 排查技能内核的 Web 化问题排查工具（dev/sit 专用）。

## 架构

```
浏览器 (Vue3 + Element Plus)  ──WS/HTTP──▶  FastAPI 后端 :8600  ──HTTP──▶  Pi 分析服务 :8700
                                                   │                          │
                                             排查内核 (kernel/)          pi-agent-core SDK
                                             ES/MySQL/Nacos/源码           LLM (opencode-go)
```

- **backend/**：FastAPI + 排查内核（kernel/，复用 issue-investigation skill 脚本）
- **analysis/**：Pi sidecar（Bun + `@earendil-works/pi-coding-agent@0.83.0`）
- **frontend/**：Vue3 + Element Plus 前端
- **data/**：运行时数据（会话 JSONL、产物），gitignore

## 启动（本机三进程）

```bash
# 1. 后端（首次自动装依赖；--host 0.0.0.0 支持局域网共享访问）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8600

# 2. Pi 分析服务（复用 ~/.pi/agent 的 LLM 配置，自动拷贝到 data/pi-agent/）
cd analysis
bun install
bun run src/index.ts

# 3. 前端（WS 直连后端，见 frontend/.env.development 的 VITE_WS_BASE）
cd frontend
npm install
npm run dev          # http://localhost:5178
```

或一键：`./dev.sh`（启动前自动清理三端口残留进程）。

## 功能

- **对话式排查**：单输入框提问（traceId/告警/业务单号均可）→ Agent 自主调用工具（collect_logs / scan_code / nacos_query / db_query / run_investigation / read_artifact）→ 流式输出结论
- **环境/主应用自动识别**：文本显式提到 sit/dev 时自动切换环境；应用/模式/业务键从描述自动解析，用户无需感知内部概念
- **应用/术语配置页**（`/config`）：应用清单（不再写死 4 个）、数据库名（空则取应用名）、业务键规则（单号→表/字段）、业务术语→应用映射；命中业务键/术语时自动带出表字段并注入排查，命中应用**优先扫描**（不排除其他应用）；保存即时生效
- **pi-web 风格界面**：左侧会话栏（按环境过滤）+ 聊天区 + 单输入框；AI 回答=最终答案+折叠的"处理详情"（中间过程+工具调用，逐个可展开）；脚注显示模型/usage/成本/时间
- **多轮追问**：同一会话延续上下文，可中途切换 dev/sit
- **单会话 10 轮上限**（门禁拦截与自动续跑不计轮次）
- **意图门禁**：只做问题排查，无关提问拦截并持久化引导语（刷新后仍可见）
- **中断续跑**：服务重启中断的排查，重新打开时显示"继续排查"横幅，点击后自动续跑
- **结论完整性校验**：回答结束时自动检查结论（缺结论/未定位缺待补线索/置信度<30%），缺则自动补救一轮（不计轮次）；仍缺则以警告横幅提示可追问
- **历史归档**：`data/runs/{run_id}/` 完整保留对话、报告、证据、中间产物（不清理、不覆盖）；`artifacts/{工具}-{序号}/` 每步产物独立

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `INV_WORKSPACE_ROOT` | `/Users/zhaoxin/code/inner` | 4 业务仓父目录（代码扫描） |
| `INV_DATA_DIR` | 项目下 `data/` | 产物根目录 |
| `INV_PI_BASE_URL` | `http://127.0.0.1:8700` | Pi sidecar 地址 |
| `INV_PI_TOOL_TOKEN` | `local-dev-token` | 工具端点鉴权 |
| `INV_LLM_MODEL` | `deepseek-v4-flash` | 门禁/分析模型 |
| `INV_IDLE_TIMEOUT_MS` | `180000` | 排查无事件看护超时（自动停止防卡死） |
| `INV_BACKEND_URL`（analysis 侧） | `http://127.0.0.1:8600` | sidecar 回调后端地址 |
| `VITE_WS_BASE`（frontend/.env.development） | `127.0.0.1:8600` | 浏览器 WS 直连后端地址（局域网共享时改本机 IP） |

LLM key 自动读 `~/.pi/agent/auth.json`（provider: opencode-go），无需配置。

## 应用/术语配置（`/config` 页面）

配置存 `data/config/apps.json`（无页面时可直接编辑，保存即时生效）：

```json
{
  "apps": {
    "lps": {
      "db_name": "",                      // 数据库名，留空 = 取应用名（再回退 env-connections schemas）
      "biz_keys": [                       // 业务键规则：单号命中 → 自动带出 表/字段
        {"pattern": "LO\\d{10,}", "table": "loan", "field": "loan_no"}
      ]
    }
  },
  "terms": [                              // 业务术语 → 应用（可多选）
    {"term": "借据号", "apps": ["lps"]}
  ]
}
```

- **识别链路**：用户消息命中业务键正则 → run 元数据记 `biz_hits`（全部命中，含 应用/表/字段），消息转发时头部注入 `[识别提示: …]`，agent 生成 db_query 计划时直接使用配置的表字段
- **扫描优先级**：命中应用在 collect_logs/scan_code 的应用清单中排序在前（优先），其余配置应用同样扫描
- **新增应用边界**：新应用除在配置页添加外，需同步 `backend/kernel/references/app-catalog.json` 注册基础元数据（primary_schema/container/nacos），否则内核校验失败

## Pi 升级 SOP

Pi（`@earendil-works/pi-coding-agent`）周更频繁，升级前必须按此流程执行。

### 依赖面（升级必核对）

| 依赖项 | 位置 | 风险 |
|---|---|---|
| `createAgentSession` / `defineTool` / `DefaultResourceLoader` / `ModelRuntime` | `analysis/src/index.ts` 入口 | 编译期报错可发现 |
| `SessionManager.create/open` + 会话 JSONL 格式 | 会话持久化（`data/pi-agent/sessions/`） | 有内置迁移，但迁移失败会丢历史 |
| **事件字段名**（message_update / text_delta / thinking_delta / tool_execution_start / tool_execution_end / message_end / agent_end） | `analysis/src/index.ts` 的 `mapEvent()` 与 `EVENT_PROTOCOL` 常量表 | ⚠️ 运行时协议，编译期发现不了，**最危险** |
| auth.json / models.json / models-store.json 格式 | 启动时自动从 `~/.pi/agent` 拷贝 | 格式变更需删除 `data/pi-agent/` 下对应文件重启重拷 |
| TypeBox（工具参数 schema） | `defineTool` 参数定义 | 0.83.0 曾出 TypeBox 破坏性变更 |

### 升级步骤

```
1. 备份 data/pi-agent/（历史会话 + 配置）
2. 读新版 CHANGELOG 的「Breaking Changes」段（node_modules/.../CHANGELOG.md 或 GitHub）
3. analysis/package.json 改版本号（精确锁定，不写 ^）→ bun install
4. 重启 sidecar，核对启动日志：
   [analysis] pi-coding-agent@<新版本> 事件协议 v1.0   ← 版本留痕
5. 验证四件事：
   ① 新会话：发消息 → 工具调用正常、流式事件到达
   ② 旧会话：打开历史 run → 能恢复对话与"处理详情"（思考内容存于会话数据，仅 UI 不展示）
   ③ 事件字段：对照 EVENT_PROTOCOL 常量表，若 pi 事件名变了更新 mapEvent
   ④ LLM 通道：opencode-go + deepseek 推理格式正常
6. 浏览器全流程走一遍 → 通过则提交（package.json + bun.lock）
7. 失败 → git checkout 回滚版本 + 恢复备份
```

### 事件协议常量表（`analysis/src/index.ts`）

升级后若页面收不到流式内容，先核对此表是否与新版 pi 事件名一致：

| 常量 | pi 事件名 | 平台事件 |
|---|---|---|
| `piMessageUpdate` / `piTextDelta` / `piThinkingDelta` | `message_update`（assistantMessageEvent.type = `text_delta` / `thinking_delta`） | `text_delta` / `thinking_delta` |
| `piToolStart` / `piToolEnd` | `tool_execution_start` / `tool_execution_end` | `tool_start` / `tool_end` |
| `piMessageEnd` / `piAgentEnd` | `message_end` / `agent_end` | `message_end` / `done` |
