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
# 1. 后端（首次自动装依赖）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8600

# 2. Pi 分析服务（复用 ~/.pi/agent 的 LLM 配置，自动拷贝到 data/pi-agent/）
cd analysis
bun install
bun run src/index.ts

# 3. 前端
cd frontend
npm install
npm run dev          # http://localhost:5178
```

或一键：`./dev.sh`

## 功能

- 对话式排查：用户提问（traceId/告警/数据核对）→ Agent 自主调用工具（collect_logs / scan_code / nacos_query / db_query / run_investigation）→ 流式输出结论
- 多轮追问：同一会话延续上下文，可中途切换 dev/sit
- 单会话 10 轮上限（门禁拦截不计轮次）
- 意图门禁：只做问题排查，无关提问拦截引导
- 历史归档：`data/runs/{run_id}/` 完整保留对话（session.jsonl）、报告、证据、中间产物；历史页只读回看

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `INV_WORKSPACE_ROOT` | `/Users/zhaoxin/code/inner` | 4 业务仓父目录（代码扫描） |
| `INV_DATA_DIR` | 项目下 `data/` | 产物根目录 |
| `INV_PI_BASE_URL` | `http://127.0.0.1:8700` | Pi sidecar 地址 |
| `INV_PI_TOOL_TOKEN` | `local-dev-token` | 工具端点鉴权 |
| `INV_LLM_MODEL` | `deepseek-v4-flash` | 门禁/分析模型 |

LLM key 自动读 `~/.pi/agent/auth.json`（provider: opencode-go），无需配置。

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
   ② 旧会话：打开历史 run → 能恢复对话、思考内容能读回
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
