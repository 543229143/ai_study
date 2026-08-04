# 问题排查平台

基于 pi-agent 内核 + 排查技能内核的 Web 化问题排查工具（dev/sit 专用）。

## 架构

```
浏览器 (Vue3 + Element Plus)  ──WS/HTTP──▶  FastAPI 后端 :8000  ──HTTP──▶  Pi 分析服务 :8100
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
.venv/bin/uvicorn app.main:app --port 8000

# 2. Pi 分析服务（复用 ~/.pi/agent 的 LLM 配置，自动拷贝到 data/pi-agent/）
cd analysis
bun install
bun run src/index.ts

# 3. 前端
cd frontend
npm install
npm run dev          # http://localhost:5173
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
| `INV_PI_BASE_URL` | `http://127.0.0.1:8100` | Pi sidecar 地址 |
| `INV_PI_TOOL_TOKEN` | `local-dev-token` | 工具端点鉴权 |
| `INV_LLM_MODEL` | `deepseek-v4-flash` | 门禁/分析模型 |

LLM key 自动读 `~/.pi/agent/auth.json`（provider: opencode-go），无需配置。
