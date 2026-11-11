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

---

## 五、本期改造用到的参考（2026-11-11 验证，均 200）

| 资源 | 链接 | 用在哪 |
|---|---|---|
| OpenAI · Function calling | https://platform.openai.com/docs/guides/function-calling | `stock-insight/core/tool_agent.py` 的协议依据 |
| OpenAI · Structured outputs | https://platform.openai.com/docs/guides/structured-outputs | 解释"为什么参数要 schema 化" |
| OTel · GenAI semantic conventions | https://opentelemetry.io/docs/specs/semconv/gen-ai/ | `core/tracing.py` 的字段命名参照（span / token / model） |
| OTel · GenAI spans | https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/ | 想把它接到真实 APM 时看这个 |
| Langfuse · Tracing | https://langfuse.com/docs/tracing | 自研 trace 与成熟产品的差距对比 |

## 六、本地产出物（不联网，随时可跑）

| 命令 | 作用 | 需要 key |
|---|---|---|
| `cd stock-insight && python3 scripts/parse_benchmark.py` | 文本协议解析鲁棒性（48 条样本） | 否 |
| `cd stock-insight && python3 scripts/prompt_size.py` | 工具描述 / 多轮 prompt 的 token 对比（需 tiktoken） | 否 |
| `cd stock-insight && python3 -m pytest tests -q` | 31 个单测 | 否 |
| `cd sre-oncall && python3 -m pytest tests -q` | 26 个单测 | 否 |
| `cd sre-oncall && python3 core/cli.py pending` | 查看挂起的审批（不需要装 openai/dotenv） | 否 |
| `cd sre-oncall && python3 core/cli.py answer <run_id> --yes` | 回答挂起项并续跑执行 | 否 |
| `cd stock-insight && python3 scripts/benchmark.py --runs 5` | 端到端延迟/token/成本 | 是 |
| `cd column-writer && python3 scripts/cost_report.py --write COST_COMPARISON.md` | 写作模式成本表 | 是 |
