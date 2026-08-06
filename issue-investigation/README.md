# 问题排查平台

基于 opencode 内核 + 排查技能内核的 Web 化问题排查工具（dev/sit 专用）。

## 架构

```
浏览器 (Vue3 + Element Plus)  ──WS/HTTP──▶  FastAPI 后端 :8600  ──HTTP──▶  分析服务 :8700 ──SDK──▶ opencode serve :14100
                                                    │                          │
                                              排查内核 (kernel/)          opencode 自定义工具 (6 个)
                                              ES/MySQL/Nacos/源码           LLM (opencode/deepseek-v4-flash-free)
```

- **backend/**：FastAPI + 排查内核（kernel/，复用 issue-investigation skill 脚本）；`agent_engine.py` 选择 Agent 引擎客户端（默认 opencode，pi/opencode 双引擎共存）
- **analysis/**：分析 sidecar（Bun + `@opencode-ai/sdk`，spawn opencode serve 子进程，数据隔离到 `data/opencode/`）；opencode 相关代码在 `src/opencode/`（client.ts / events.ts）
- **config/opencode/**：opencode 统一配置目录——`opencode.json`（agent/权限/模型）+ `.opencode/tools/`（6 个 Custom Tools，回调分析服务 → 后端内核，agent 只能调这些工具）+ 公共提示词 `config/prompt.md`（opencode 与 pi 共用）
- **frontend/**：Vue3 + Element Plus 前端
- **data/**：运行时数据（会话映射、opencode DB、产物），gitignore

## 目录结构

```
issue-investigation/
├── backend/                  # FastAPI：API/WS 桥、意图门禁、工具端点、排查内核调用
│   └── app/
│       ├── agent_engine.py   # Agent 引擎选择器（INV_AGENT_ENGINE，默认 opencode）
│       ├── opencode_client.py / pi_client.py   # 引擎客户端（同一套 sidecar HTTP 契约，分文件）
│       └── kernel/           # 排查内核（复用 skill 脚本）
├── analysis/                 # 分析 sidecar（Bun）
│   ├── src/opencode/         # opencode 引擎：index.ts（HTTP/编排）+ client.ts（serve/会话映射）+ events.ts（事件协议）
│   ├── src/pi/               # pi 引擎（双引擎共存，端口 8701）
│   └── src/conclusion_check.ts   # 结论完整性校验（两引擎共用）
├── config/                   # 统一配置（入库）
│   ├── opencode/             # opencode：opencode.json（agent/权限/模型）+ .opencode/tools/（6 工具）
│   ├── pi/                   # pi 配置（双引擎共存）
│   └── prompt.md             # 公共系统提示词（两引擎共用）
├── frontend/                 # Vue3 + Element Plus
├── data/                     # 运行时（gitignore）：runs/{run_id}/ 产物、opencode/opencode.db、pi/sessions/ 映射
├── dev.sh                    # 一键启动四进程
└── opencode 相关代码/配置均以「引擎目录」划分：见名知 agent（opencode ↔ pi 不混放）
```

## 启动

```bash
# 一键启动：backend(8600) + opencode sidecar(8700) + pi sidecar(8701) + frontend(5178)
./dev.sh

# 引擎选择（默认 opencode，双引擎共存）：INV_AGENT_ENGINE=pi ./dev.sh
```

手动启动：

```bash
# 1. 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
INV_AGENT_ENGINE=opencode .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8600

# 2. 分析服务（自动拉起 opencode serve :14100；LLM key 用全局 ~/.local/share/opencode/auth.json）
cd analysis
bun install
bun run src/opencode/index.ts        # opencode 引擎（默认）；pi 引擎：bun run src/pi/index.ts

# 3. 前端（WS 直连后端，见 frontend/.env.development 的 VITE_WS_BASE）
cd frontend
npm install
npm run dev          # http://localhost:5178
```

## 配置（LLM 与 Agent）

- **LLM 通道**：opencode 全局 auth（`~/.local/share/opencode/auth.json`，provider `opencode-go`）；模型/agent 在 `config/opencode/opencode.json` 配置
- **Agent 权限**：`config/opencode/opencode.json` 的 `investigation` agent 设置 `"*": "deny"` + 6 工具 allow——模型无法执行 bash/文件读写，只能调排查工具
- **当前模型**：`opencode/deepseek-v4-flash-free`（免费档，成本 0）。注意免费档偶发空回复（最后一步无输出），平台结论校验会自动补救一轮；仍缺则警告横幅提示。如需更稳定可改回 `opencode-go/deepseek-v4-flash`（付费）
- **Agent 切换**：页面顶栏 agent 下拉（`/runs/agents` 读取 opencode.json 定义的 agent，排除 opencode 内置）；切换后左侧会话列表与历史页只显示该 agent 的会话
- 历史 `config/pi/` 仅保留给后端门禁读 key（`backend/app/config.py`），sidecar 不再使用

## 功能

- **对话式排查**：单输入框提问（traceId/告警/业务单号均可）→ Agent 自主调用工具（collect_logs / scan_code / nacos_query / db_query / run_investigation / read_artifact）→ 流式输出结论
- **环境/主应用自动识别**：文本显式提到 sit/dev 时自动切换环境；应用/模式/业务键从描述自动解析，用户无需感知内部概念
- **首轮初始采集**：首条消息时平台自动先采一轮日志（识别参数驱动，对应 skill 的 logs 阶段先行），结果摘要+artifact 引用注入「初始证据」段，agent 从证据出发决策；无命中/失败不阻塞
- **应用/术语配置页**（`/config`）：应用清单（不再写死 4 个）、数据库名（空则取应用名）、业务键规则（单号→表/字段）、业务术语→应用映射；命中业务键/术语时自动带出表字段并注入排查，命中应用**优先扫描**（不排除其他应用）；保存即时生效
- **pi-web 风格界面**：左侧会话栏（按环境过滤）+ 聊天区 + 单输入框；AI 回答=最终答案+折叠的"处理详情"（中间过程+工具调用，逐个可展开）；脚注显示模型/usage/成本/时间
- **多轮追问**：同一会话延续上下文，可中途切换 dev/sit
- **单会话 10 轮上限**（门禁拦截与自动续跑不计轮次）
- **意图门禁**：只做问题排查，无关提问拦截并持久化引导语（刷新后仍可见）
- **中断续跑**：服务重启中断的排查，重新打开时显示"继续排查"横幅，点击后自动续跑
- **结论完整性校验**：回答结束时自动检查结论（缺结论/未定位缺待补线索/置信度<30%），缺则自动补救一轮（不计轮次）；仍缺则以警告横幅提示可追问
- **满意度评价**：结论轮后五星评价，非 5 星必填原因；10 轮结束强制评价；存 `runs/{id}/satisfaction.json`
- **历史归档**：`data/runs/{run_id}/` 完整保留对话、报告、证据、中间产物（不清理、不覆盖）；`artifacts/{工具}-{序号}/` 每步产物独立

### 数据留存（知识库素材）

每次排查完成后 `run.json` 落 `conclusion` 快照（供排查知识库直接使用）：

```json
{
  "question": "原始问题（已清洗注入前缀）",
  "answer": "最终结论全文",
  "env": "sit", "app": "lps", "mode": "biz_key",
  "rounds": 3, "tools_used": 12, "usage": {"input":.., "output":.., "cost":..},
  "satisfaction": {"stars":4, "reason":"...", "forced":false}
}
```

配合 `satisfaction.json`（满意度+原因）、会话 JSONL（含思考/工具调用全过程）、`artifacts/`（日志/DB/报告），可完整重建"问题→排查过程→结论→用户评价"链路。满意度提交后自动回写快照；用户环境切换记录在 run 时间线（`env_switched`）。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `INV_WORKSPACE_ROOT` | `/Users/zhaoxin/code/inner` | 4 业务仓父目录（代码扫描） |
| `INV_DATA_DIR` | 项目下 `data/` | 产物根目录 |
| `INV_AGENT_ENGINE` | `opencode` | Agent 引擎：`opencode` \| `pi`（双引擎共存） |
| `INV_PI_BASE_URL` | `8700`（opencode 引擎）/ `8701`（pi 引擎） | 分析服务地址 |
| `INV_PI_TOOL_TOKEN` | `local-dev-token` | 工具端点鉴权 |
| `INV_LLM_MODEL` | `deepseek-v4-flash` | 门禁/分析模型 |
| `INV_IDLE_TIMEOUT_MS` | `180000` | 排查无事件看护超时（自动停止防卡死） |
| `INV_BACKEND_URL`（analysis 侧） | `http://127.0.0.1:8600` | sidecar 回调后端地址 |
| `INV_OPENCODE_PORT`（analysis 侧） | `14100` | opencode serve 端口（数据隔离到 `data/opencode/opencode.db`） |
| `VITE_WS_BASE`（frontend/.env.development） | `127.0.0.1:8600` | 浏览器 WS 直连后端地址（局域网共享时改本机 IP） |

LLM key 读全局 `~/.local/share/opencode/auth.json`（provider: opencode-go）。

## 应用/术语配置（`/config` 页面）

配置存 `config/apps.json`（无页面时可直接编辑，保存即时生效）：

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

## opencode 升级 SOP

opencode（`@opencode-ai/sdk` + `opencode serve` 二进制）迭代频繁，升级前必须按此流程执行。

### 依赖面（升级必核对）

| 依赖项 | 位置 | 风险 |
|---|---|---|
| SDK API（`session.create/messages/promptAsync/abort` 等） | `analysis/src/opencode/client.ts` | 编译期报错可发现 |
| SDK 返回信封：**所有调用结果都是 `{data, request, response}` 包了一层**，取数须 `result.data ?? result` | `analysis/src/opencode/client.ts` | 编译期不报错，运行期 undefined（曾踩坑：session_id 丢失导致无限建会话） |
| **事件字段名**（message.part.delta / message.part.updated / message.updated / session.idle / session.status / session.error） | `analysis/src/opencode/events.ts` 的 `EVENT_PROTOCOL` 常量表 | ⚠️ 运行时协议，编译期发现不了，**最危险** |
| `opencode.json` 的 agent/permission/provider 结构 | `config/opencode/` | 权限配置错误会静默放开工具 |
| 全局 auth（`~/.local/share/opencode/auth.json`） | 用户环境 | key 过期/未登录时模型调用失败 |
| 数据隔离（`OPENCODE_DB` 环境变量） | `analysis/src/opencode/client.ts` spawn 参数 | 去掉隔离后平台会话混入个人 opencode DB |

### 升级步骤

```
1. 备份 data/opencode/（opencode DB）与 data/pi/sessions/（run↔session 映射）
2. 读新版 CHANGELOG 的「Breaking Changes」段（GitHub: anomalyco/opencode）
3. analysis/package.json 改 @opencode-ai/sdk 版本号（精确锁定）→ bun install
4. 升级 opencode 二进制（opencode upgrade），重启 sidecar，核对启动日志：
   [analysis] opencode serve healthy (version <新版本>)
   [analysis] @opencode-ai/sdk@<新版本> 事件协议 v2.0   ← 版本留痕
5. 验证四件事：
   ① 新会话：发消息 → 工具调用正常、流式事件到达
   ② 旧会话：打开历史 run → 能恢复对话与"处理详情"
   ③ 事件字段：对照 EVENT_PROTOCOL 常量表，若 opencode 事件名变了更新 handleEvent
   ④ LLM 通道：opencode-go 推理格式正常
6. 浏览器全流程走一遍 → 通过则提交（package.json + bun.lock + config/opencode/ 全部文件 + analysis/src/opencode/）
7. 失败 → 回滚版本 + 恢复备份
```

### 事件协议常量表（`analysis/src/opencode/events.ts`）

升级后若页面收不到流式内容，先核对此表是否与新版 opencode 事件名一致：

| 常量 | opencode 事件 | 平台事件 |
|---|---|---|
| `ocPartDelta` | `message.part.delta`（properties.partID + field="text" + delta，text/reasoning 均走此） | `text_delta` / `thinking_delta` |
| `ocPartUpdated` | `message.part.updated`（properties.part，type=text/reasoning/tool；tool state: pending→running→completed/error，结果在 state.output） | 兜底文本 / `tool_start` / `tool_end` |
| `ocMessageUpdated` | `message.updated`（assistant + time.completed → 每步结束） | `message_end` |
| `ocSessionIdle` | `session.idle`（整轮完成 → 结论校验/补救） | `done`（cost/warning） |
| `ocSessionError` / `ocMessageError` | 会话/消息错误 | `error` |
| 成本 | `step-finish` part 的 `cost`/`tokens`（USD） | 脚注成本 |
