# 资源清单（链接已逐个验证）

> 验证时间：2026-11-10 ｜ 全部返回 HTTP 200
> star 数、状态均为该日快照，后续会变，但链接可用性已验证

---

## 一、主线（六周计划必用）

| 资源 | 链接 | 快照 | 状态 | 用法 |
|---|---|---|---|---|
| deepagents | https://github.com/langchain-ai/deepagents | 31.2k ⭐ | 活跃 | **W1 主线**，LangGraph 官方的 agent 运行时 |
| deepagents 文档·总览 | https://docs.langchain.com/oss/python/deepagents/overview | — | 可用 | 先看这个再读代码 |
| deepagents 文档·子智能体 | https://docs.langchain.com/oss/python/deepagents/subagents | — | 可用 | 理解子 agent 隔离 |
| deepagents 文档·中间件 | https://docs.langchain.com/oss/python/deepagents/middleware | — | 可用 | 理解上下文压缩/HITL 怎么插 |
| langgraph | https://github.com/langchain-ai/langgraph | 44.7k ⭐ | 活跃 | **W2 主线**，只看 state/checkpoint/interrupt |
| LangGraph 文档·总览 | https://docs.langchain.com/oss/python/langgraph/overview | — | 可用 | 概念地图 |
| LangGraph·持久化 | https://docs.langchain.com/oss/python/langgraph/persistence | — | 可用 | 断点恢复的核心 |
| LangGraph·中断 | https://docs.langchain.com/oss/python/langgraph/interrupts | — | 可用 | 人工审批 HITL |
| LangGraph·工作流与 Agent | https://docs.langchain.com/oss/python/langgraph/workflows-agents | — | 可用 | 编排范式对照 |
| LangChain·多智能体 | https://docs.langchain.com/oss/python/langchain/multi-agent | — | 可用 | 多 agent 拓扑 |
| litellm | https://github.com/BerriAI/litellm | 63.0k ⭐ | 活跃 | **W3 主线**，LLM 网关 |
| LiteLLM 文档 | https://docs.litellm.ai/ | — | 可用 | 入口 |
| LiteLLM·路由 | https://docs.litellm.ai/docs/routing | — | 可用 | 重点：deployment/健康/策略/fallback |
| langfuse | https://github.com/langfuse/langfuse | 37.2k ⭐ | 活跃 | **W4 主线**，trace + 评测 |
| Langfuse 文档 | https://langfuse.com/docs | — | 可用 | trace 结构与数据集评测 |
| OpenAI Agents·tracing | https://openai.github.io/openai-agents-python/tracing/ | — | 可用 | 不想装 Langfuse 就用这个，最轻 |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | 24.8k ⭐ | 活跃 | **W5 主线** |
| MCP 官网 | https://modelcontextprotocol.io/ | — | 可用 | 概念 |
| MCP 协议规范 | https://modelcontextprotocol.io/specification/latest | — | 可用 | tools/resources/prompts/transport |

---

## 二、思想与方法论（读文字，不写代码，收益极高）

| 资源 | 链接 | 快照 | 用法 |
|---|---|---|---|
| 12-Factor Agents | https://github.com/humanlayer/12-factor-agents | 27.1k ⭐ | **W6 必读**，两天读完，面试金句来源 |
| 12-Factor Agents 站点 | https://humanlayer.dev/12-factor-agents/ | — | 排版更好，手机也能读 |
| Anthropic·Building effective agents | https://www.anthropic.com/engineering/building-effective-agents | — | 范式定义的标准出处（workflow vs agent） |
| Anthropic·上下文工程 | https://www.anthropic.com/research/effective-context-engineering-for-ai-agents | — | 讲清"上下文是稀缺资源" |
| Anthropic·为 Agent 写工具 | https://www.anthropic.com/engineering/writing-tools-for-agents | — | W5 配套，工具描述怎么写 |

---

## 三、选做 / 对比阅读

| 资源 | 链接 | 快照 | 说明 |
|---|---|---|---|
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | 30.6k ⭐ | 代码极简，1h 读完，适合做"轻量 vs 重量"对比 |
| OpenAI Agents 文档 | https://openai.github.io/openai-agents-python/ | — | handoff/tracing 概念清楚 |
| OpenAI Agents·handoffs | https://openai.github.io/openai-agents-python/handoffs/ | — | 交接式多 agent |
| Pydantic AI | https://github.com/pydantic/pydantic-ai | 21.1k ⭐ | 强类型 + DI，Java 背景的人最亲切 |
| Pydantic AI 文档·Agents | https://ai.pydantic.dev/agents/ | — | 看它的依赖注入设计 |
| smolagents | https://github.com/huggingface/smolagents | 30.3k ⭐ | "code as action" 范式，2h 读完 |
| smolagents 文档 | https://huggingface.co/docs/smolagents/index | — | 入门最快的框架 |
| OpenHands | https://github.com/All-Hands-AI/OpenHands | 93.1k ⭐ | 最像真实后端系统：事件流 + Docker 沙箱；只挑模块读 |
| OpenHands 文档 | https://docs.all-hands.dev/ | — | 架构说明 |
| TradingAgents | https://github.com/TauricResearch/TradingAgents | 121.6k ⭐ | 只读 `graph/` 与 `agents/`，当阅读材料 |
| TradingAgents 论文 | https://arxiv.org/abs/2412.20138 | — | 想看设计动机再读，非必读 |

---

## 四、已知失效 / 不推荐

| 资源 | 问题 |
|---|---|
| `langchain-ai/open_deep_research` https://github.com/langchain-ai/open_deep_research | **已归档（archived）**，最后更新 2026-08。内容仍可读，但别当主线，它的能力已并入 deepagents |
| `humanlayer.github.io/12-factor-agents` | **404 已失效**，改用它上面的 `humanlayer.dev` 站点或 GitHub 仓库 |
| `docs.langchain.com/.../langgraph/multi-agent` | **404**，多智能体内容已迁到 `/oss/python/langchain/multi-agent` |
| TradingAgents 全文精读 | 不推荐：业务是金融，与目标岗位无关，10k 行读完成本极高 |
| CrewAI 源码精读 | 不推荐：抽象最浅，面试价值低；只需知道"角色扮演式编排"一句话定位 |
| AutoGen / 微软 Agent Framework | 不推荐投入：新旧交替期，知道定位即可 |
