# Agent 学习计划

> 目标：从理解设计原理到能自己写一个完整 Agent
> 基础：已有 SKILL.md 实战经验，理解工具调用基本概念
> ⚠️ 链接说明：以下链接均已验证可访问。GitHub 仓库链接需科学上网。

---



## 阶段二：跑通最小 Agent（第 2-3 天）

### 必看代码

| 仓库 | 看什么 | 做什么 |
|------|--------|--------|

| https://github.com/openai/openai-agents-python | `examples/basic/` 目录 | 看官方推荐的 Agent 写法，含 gardrail、handoff 等 |

### 自己动手写

```python
# 写一个最小 Agent，支持 3 个工具：
# 1. query_weather(city) → 查天气
# 2. create_reminder(time, content) → 设提醒
# 3. search_web(query) → 搜索

# 核心循环只要 20 行
# 能跑起来、能调工具、能回退给 LLM
```

### 验证标准

- 说"北京天气怎么样" → 自动调 query_weather → 返回结果
- 说"明天下午提醒我开会" → 自动调 create_reminder
- 工具参数不全 → AI 自动反问用户

---

## 阶段三：理解工程化（第 4-5 天）

### 精读项目

| 项目 | 星数 | 推荐理由 |
|------|------|---------|
| https://github.com/earendil-works/pi | ⭐ 65.5k | **最适合入门完整体验 AgentHarness 架构**：TypeScript 单体仓库，packages 分层清晰（pi-ai → pi-agent-core → pi-coding-agent），从底层 LLM API 抽象、agent loop、TUI 到 coding agent CLI 一应俱全。AgentLoop（Query Loop）在这里就是核心循环，读完就理解 AgentHarness 全貌 |
| https://github.com/OpenHands/OpenHands | ⭐ 76.5k | **目前最流行的 AI 开发 Agent 平台**：有 SDK（Python 库）、CLI（命令行）、GUI（Web 界面）、Cloud 部署、Enterprise 版，也有自己的 skills 系统。完整程度最高，社区活跃 |
| https://github.com/openai/openai-agents-python | ⭐ 27.1k | **OpenAI 官方出品，五脏俱全**：多 agent 编排、tool calling、guardrail、human-in-the-loop、tracing、session 管理、realtime。代码极规范，Python 最佳实践 |
| https://github.com/nicepkg/gpt-runner | ⭐ 380 | 和你的 SKILL.md 理念最像，xxx.gpt.md 预设文件 + 多平台（CLI/VSCode/Web）|

### Pi Agent 重点看什么

```
packages/
  pi-ai/               → 统一多厂商 LLM API（OpenAI/Anthropic/Google），理解 LLM 抽象层
  pi-agent-core/       → Agent 核心运行时（AgentLoop、tool calling、state management）— 核心！
  pi-coding-agent/     → 交互式 coding agent CLI + TUI，extension 系统、hooks、skills
  pi-tui/              → 终端 UI 库
```

Pi Agent 是理解 **AgentHarness** 架构的最佳入门：
- `pi-agent-core` 里的 AgentLoop 就是 Loop Engineering 的具体实现
- 项目本身就是 AgentHarness：LLM API 抽象 + 核心循环 + 工程化 CLI + 扩展系统
- 相比 CrewAI 的高层编排抽象，Pi Agent 让你能看到 loop 底层怎么转

### OpenHands 重点看什么

```
openhands/
  core/               → Agent 核心逻辑（循环、工具调用）
  skills/             → skill 系统（和你 SKILL.md 概念一致！）
  cli/                → CLI 实现
  frontend/           → Web GUI 实现
  server/             → 后端 API 服务
containers/           → 沙箱执行环境（安全隔离）
```

OpenHands 有 3 个使用方式：`SDK`（写代码控制）、`CLI`（命令行）、`GUI`（Web 界面）。推荐从 CLI 入手，`pip install openhands` 就能跑。

### openai/openai-agents-python 重点看什么

```
src/agents/
  agent.py          → Agent 定义（instructions、tools、handoffs）
  runner.py         → 执行循环（核心！看它怎么调 LLM 和处理 tool calls）
  handoffs.py       → 多 agent 怎么交接任务
  guardrails.py     → 输入/输出守卫
  tracing/          → 链路追踪（生产环境必备）
```

### nicepkg/gpt-runner 重点看什么

```
packages/
  gpt-runner-cli/        → CLI 入口，理解命令行 Agent
  gpt-runner-vscode/     → IDE 插件，和你现在的 Cursor 方式最像
```

### 关注点

- 怎么管理多轮对话（记忆）
- 怎么处理工具调用异常
- 怎么让用户选择文件（你的 SKILL.md 也是这个需求）
- xxx.gpt.md 预设文件的加载和执行（和你的 SKILL.md 同理）

---

## 阶段四：写自己的 Agent（第 6-7 天）

### 选题建议（选一个）

| 选题 | 业务价值 | 难度 |
|------|---------|------|
| 把现有 SKILL.md 套 HTTP 服务独立部署 | 可直接用于团队 | ⭐⭐ |
| 写一个代码审查 Agent（Code Review） | 配合你现在的工作流 | ⭐⭐ |
| 写一个数据分析 Agent（自然语言→SQL→报表） | 通用性强 | ⭐⭐⭐ |
| 参考 OpenAI Agents SDK 写一个最小多 Agent 编排 | 深入理解架构 | ⭐⭐⭐ |

### 架构模板

```
用户输入
  ↓
LLM 推理（ReAct 循环）
  ↓
工具调用 → 执行你写的函数 → 结果回填
  ↓
LLM 生成最终回答
  ↓
返回给用户
```

### 要求

- 至少 3 个工具
- 支持多轮对话（上下文记忆）
- 异常处理（工具调用失败、LLM 输出格式错误）
- 可以 CLI 启动，也可以 HTTP 部署

---

## 推荐资源索引（全链接已验证）

| 类别 | 名称 | 链接 |
|------|------|------|
| **设计** | Building effective agents | https://www.anthropic.com/engineering/building-effective-agents |
| **设计** | OpenAI Function Calling | https://platform.openai.com/docs/guides/function-calling |
| **设计** | ReAct 论文 | https://arxiv.org/abs/2210.03629 |
| **代码** | openai-cookbook | https://github.com/openai/openai-cookbook |
| **代码** | anthropic-cookbook | https://github.com/anthropics/claude-cookbooks |
| **完整项目** | Pi Agent（⭐ 65.5k） | https://github.com/earendil-works/pi |
| **完整项目** | OpenHands（⭐ 76.5k） | https://github.com/OpenHands/OpenHands |
| **完整项目** | openai/openai-agents-python（⭐ 27.1k） | https://github.com/openai/openai-agents-python |
| **完整项目** | nicepkg/gpt-runner（⭐ 380） | https://github.com/nicepkg/gpt-runner |
| **框架** | LangGraph | https://github.com/langchain-ai/langgraph |
| **框架** | AutoGen | https://github.com/microsoft/autogen |
| **框架** | CrewAI | https://github.com/crewAIInc/crewAI |

---

## Agent 框架选型（按代码复杂度排序）

| 项目 | 复杂度 | 学什么 |
|------|--------|--------|
| **Pi Agent** https://github.com/earendil-works/pi | ⭐ 代码分层极清晰，从 LLM API → Agent Core → CLI 一目了然，最适合第一次完整读一个 agent 源码 | 理解 AgentHarness 全貌：LLM 抽象层、AgentLoop、tool calling、TUI、extension/hooks 系统 |
| **CrewAI** https://github.com/crewAIInc/crewAI | ⭐⭐ 代码组织干净，多 agent 编排，比 AutoGPT 复杂但结构清晰 | 多 agent 分层规划与任务委派 |
| **SWE-agent** https://github.com/princeton-nlp/SWE-agent | ⭐⭐⭐ CodeAct 落地，涉及沙箱管理、代码执行、工具集成，复杂度再高一档 | CodeAct 范式在软件工程里的实际落地 |
| **LangGraph** https://github.com/langchain-ai/langgraph | ⭐⭐⭐⭐ 最复杂，完整的状态机/DAG 引擎、checkpoint/并行/重试/回滚全部实现 | DAG 编排、replanning、human-in-the-loop、checkpoint |

## 学习原则

1. **不贪多** — 前两个阶段只跑通最小示例，别一上来就用框架
2. **先抄后写** — 先跑通别人的代码，再自己写
3. **带着问题读代码** — 别从头看，想问"对话记忆怎么做的"再去搜
4. **和 SKILL.md 对照** — 每个新概念都想想"这个在我 SKILL.md 方案里对应什么"
