# Agent 工程 / 后端 — 六周复习学习计划

> 面向：20 年 Java 后端背景、正在转 AI 应用 / Agent 工程岗
> 周期：6 周，每周 8~10 小时（在职节奏，不脱产）
> 目标：不是"再学一遍 Agent 是什么"，而是**把已有资产升级成能扛住追问的工程叙事**
> 制定日期：2026-11-10 ｜ 资源链接均已逐个验证可打开（见 [resources.md](./resources.md)）

---

## 一、先看清现状

你手上已经有的（不用重复造）：

| 资产 | 位置 | 覆盖能力 |
|---|---|---|
| 4 个原创 Agent 项目（零框架） | `sre-oncall/` `stock-insight/` `column-writer/` | Agent 循环、ReAct、Plan-Solve、Reflection、多 Agent、记忆、RAG |
| 概念笔记（1586 行） | `study/ai_study.md` | 推理机制、Function Calling、Memory、模型选型、多智能体 |
| 面试问答手册 | `answer/ai_answer_261105.md` 等 | 话术、踩分点 |
| 20 年 Java 微服务经验 | 本职 | 高并发、可靠性、权限审计、工程化落地 |

你的缺口也很清楚——**不在"会不会做 Agent"，在"知不知道生产级 Agent 系统长什么样"**：

| 层 | 现状 | 判断 |
|---|---|---|
| L1 概念范式 | ✅ 有 | 已足够，别再读入门文 |
| L2 编排引擎（状态机/断点/子图/并行） | ⚠️ 只有自研简化版 | **最大缺口**，面试深挖必到这一层 |
| L3 工具与协议（MCP） | ❌ 无 | 当前最热，投入产出比最高 |
| L4 模型网关（路由/降级/成本/限流） | ❌ 无 | **你的后端经验在这里能直接变现** |
| L5 可靠性（重试/超时/幂等/沙箱） | ⚠️ 零散 | 需要一次系统化 |
| L6 可观测与评测 | ❌ 无 | 面试"你怎么知道它变好了"直接答不出 |
| L7 记忆 / RAG | ✅ 有 | 保持，不用再补 |
| L8 企业落地（权限/审计/部署） | ✅ 强项 | 优势区，但要讲成体系 |

**结论**：这六周不重写项目、不刷教程，只做三件事——**补 L2/L4/L6、打通 L3、把全部经历收敛成一条主线**。

---

## 二、六周路线图

### 总览

| 周 | 主题 | 主线项目 | 产出物 | 时间 |
|---|---|---|---|---|
| W1 | 生产级 Agent 框架长什么样 | `deepagents` | 一页架构拆解 | 8h |
| W2 | 编排引擎底层 | `langgraph` | 用 LangGraph 重写一个已有流程 + 对比笔记 | 10h |
| W3 | 模型网关与调用层可靠性 | `litellm` | 一页"LLM 调用层高可用方案" | 8h |
| W4 | 可观测性与评测 | `langfuse` / OpenAI Agents tracing | 一份 10 条用例的评测报告 | 8h |
| W5 | 工具协议 | `modelcontextprotocol/python-sdk` | 可运行的 MCP server | 8h |
| W6 | 收敛与输出 | —（整合） | 简历项目描述 + 3 个面试故事 + 2 次模拟面 | 8h |

> 每周固定节奏：**周一 30 分钟定目标 → 周中 2 次 × 2 小时 → 周末 3 小时写产出**。
> 产出物不写就不算完成，这是唯一硬性纪律。
>
> **关于工时**：三个存量项目的代码改造已经做完（见第三节，共约 5~6 小时，AI 代写 + 你验证）。
> 所以 W2/W4 里的"改代码"不再是主线，**你的时间只花在三件事上：读懂、跑出真数字、讲清楚**。
> 写代码的时间省下来了，但"能讲出来"的时间省不掉——这是唯一不能被 AI 替代的部分。

---

### W1｜生产级 Agent 框架长什么样（8h）

**为什么先学这个**：你现在的 4 个项目是"零框架"的，优点是可控，缺点是一被问"生产上怎么管上下文、怎么做人工介入、子任务怎么隔离"，就答不上来。先看一眼成熟的框架级设计，后面所有讨论都有参照。

**做什么**

1. clone + 跑通 `deepagents`（LangGraph 官方"电池全包"的 agent 运行时，31k star，活跃）
2. 顺着这三层读代码，画一张图：
   - **backend**：文件系统 / 状态存储怎么抽象
   - **middleware**：上下文压缩、工具调用拦截、HITL 是怎么"插"进去的
   - **subagent**：主 agent 怎么派活，子 agent 的 message history 怎么隔离
3. 只读主干，别逐行。目标文件量控制在 2k 行以内

**产出**：`review/notes/w1-deepagents.md`（1 页，必须有自己的架构图）

**验收**：不看代码，能讲 10 分钟"这个框架解决了我自研方案里的哪三个问题"

**资源**
- https://github.com/langchain-ai/deepagents
- https://docs.langchain.com/oss/python/deepagents/overview
- https://docs.langchain.com/oss/python/deepagents/subagents
- https://docs.langchain.com/oss/python/deepagents/middleware

---

### W2｜编排引擎底层（10h）★ 本周最重要

**为什么**：这是"框架使用者"和"框架理解者"的分水岭。面试问"为什么用 LangGraph 不用自己写 while 循环"，你现在只能答"方便"；学完这周你能答到 state reducer、断点恢复、中断语义这一层。

**做什么**

1. 读懂 5 个概念（每个都要能举自己的例子）：
   - **State + reducer**：为什么并发节点写同一个 key 会丢数据，`Annotated` reducer 怎么解决
   - **Checkpointer**：按步骤落盘 → 崩溃续跑；和"重试"的本质区别
   - **Interrupt / HITL**：中断点、恢复、人工审批怎么接
   - **Subgraph**：把 analyst 做成独立子图，只回传报告，避免并行写冲突
   - **Recursion limit**：agent 死循环调用工具怎么兜底（这是个高频追问）
2. **动手**：把 `stock-insight` 的 ReAct 主循环用 LangGraph 重写一版，放 `review/demo/stock-insight-langgraph/`

**产出**
- 可运行的 LangGraph 版 demo
- `review/notes/w2-langgraph-vs-diy.md`：**对照表**——自研 while 循环 vs LangGraph，各 5 条优劣，附"什么场景我仍然选自研"

**验收**：能回答"并发 4 个 analyst，怎么保证它们的工具调用不互相污染"（提示：私有 message history + 子图 output schema）

**资源**
- https://github.com/langchain-ai/langgraph
- https://docs.langchain.com/oss/python/langgraph/overview
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/workflows-agents
- https://docs.langchain.com/oss/python/langchain/multi-agent

---

### W3｜模型网关与调用层可靠性（8h）★ 你的优势区

**为什么**：这周是把 20 年后端经验"翻译"成 AI 领域的语言。LiteLLM 本质就是一个 LLM 网关：多上游、路由、熔断、降级、配额——**你做过的东西它全做了，只是换了协议**。

**做什么**

1. 读 `Router` 的设计：deployment、健康检查、路由策略（成本优先/延迟优先/权重）、fallback 链
2. 读预算、配额、限流、缓存、虚拟 key 这几块
3. **动手**：本地起一个 proxy，配 2 个上游 + 一条 fallback，用脚本打 50 次请求，观察降级过程

**产出**：`review/notes/w3-llm-gateway.md` —— 一页"LLM 调用层高可用方案"，直接可以当面试答案：

> 多上游注册与健康探测 → 路由策略（成本/延迟/权重）→ 失败重试与跨上游降级 → 配额与预算熔断 → 结果缓存 → 全链路 trace 归因

**验收**：能把"AI 接口流量突增 10 倍"答成一套分层方案（限流 → 排队/异步 → 缓存 → 模型分级 → 降级兜底），而不是只说"加机器"

**资源**
- https://github.com/BerriAI/litellm
- https://docs.litellm.ai/
- https://docs.litellm.ai/docs/routing

---

### W4｜可观测性与评测（8h）

**为什么**：这是绝大多数转 AI 的后端最空的一块。"你怎么知道改了 prompt 之后变好了还是变差了？"——答不出这题，会被判定为"只会调 API"。

**做什么**

1. 搞清 trace 结构：一次 Agent 运行 = 一个 trace，里面多次 LLM 调用 / 工具调用 = 多个 span，每层挂 token 与成本
2. 搞清评测的三种做法与坑：规则断言 → 数据集回归 → LLM-as-judge（要讲清 judge 的偏差）
3. **动手**：给 W2 的 demo 接上 trace（Langfuse 或 OpenAI Agents 自带的 tracing），然后写 10 条用例跑一次回归，出一份报告

**产出**：`review/notes/w4-eval-report.md`（含：10 条用例、通过率、token 成本、发现的 2 个问题）

**验收**：能讲"我改了一版 prompt，用 10 条回归用例验证，通过率从 6/10 提到 9/10，单次成本降 23%"

**资源**
- https://github.com/langfuse/langfuse
- https://langfuse.com/docs
- https://openai.github.io/openai-agents-python/tracing/

---

### W5｜工具协议 MCP（8h）

**为什么**：2025 之后"工具怎么标准化接入"是必问题。你已经有 18 个工具（stock-insight），把它们协议化，是投入产出比最高的一次改造。

**做什么**

1. 读协议三件套：**tools / resources / prompts**，以及 transport（stdio vs HTTP）
2. 想清楚一个设计问题：为什么"工具描述"本身就是 prompt 的一部分，描述写不好模型就选错工具（附 Anthropic 那篇工具设计的文章）
3. **动手**：把 stock-insight 里的 2~3 个工具包成 MCP server，接入 opencode 或 deepagents 实际跑一次

**产出**：`review/demo/stock-insight-mcp/`（可运行）+ `review/notes/w5-mcp.md`

**验收**：能讲清"Function Calling 和 MCP 是什么关系"——前者是模型的输出格式，后者是工具的接入协议，两者不冲突

**资源**
- https://github.com/modelcontextprotocol/python-sdk
- https://modelcontextprotocol.io/
- https://modelcontextprotocol.io/specification/latest
- https://www.anthropic.com/engineering/writing-tools-for-agents

---

### W6｜收敛与输出（8h）★ 决定成败

前五周是输入，这周全部转成"能说出口的东西"。

**做什么**

1. **写一条主线**，把 4 个项目 + 6 周所学串成三句话：
   - 我做过完整的 Agent 应用（4 个，零框架，能讲细节）
   - 我理解生产级框架的设计取舍（deepagents / LangGraph 的 state、子图、中断）
   - 我知道怎么让它稳定运行（网关降级、可观测、评测回归）
2. **准备 3 个故事**（每个 3 分钟，STAR 结构）：
   - 故事 A：框架选型——为什么自研 / 为什么后来用 LangGraph
   - 故事 B：调用层可靠性——从限流降级讲到成本的量化结果
   - 故事 C：工具协议——把内部工具 MCP 化，复用到多个 agent
3. **更新** `answer/` 下的问答手册（对齐本期新学的 L2/L4/L6）
4. 两次模拟面试：一次自问自答录音，一次找人对着 `checklist.md` 提问

**产出**：`review/notes/w6-final-story.md` + 更新后的 `answer/`

**验收**：三个故事任意抽一个，不看稿讲满 3 分钟，且能被追问 5 层不崩

**资源**
- https://github.com/humanlayer/12-factor-agents
- https://humanlayer.dev/12-factor-agents/
- https://www.anthropic.com/engineering/building-effective-agents
- https://www.anthropic.com/research/effective-context-engineering-for-ai-agents

---

## 三、存量项目最终计划（代码已落地）

三个项目不是"再学一遍"，而是**各补一个工程维度，互不重复**：

| 项目 | 定位 | 改了什么 | 关键文件 |
|---|---|---|---|
| `stock-insight` | **主力**（质量/性能可测） | 原生 `tool_calls` 版 agent、trace（token/成本/耗时）、单测 | `core/tool_agent.py`、`core/tool_registry.py`、`core/tracing.py`、`tests/` |
| `column-writer` | **成本可控** | 成本/质量对照报表脚本 + 表模板 | `scripts/cost_report.py`、`COST_COMPARISON.md` |
| `sre-oncall` | **行为可控** | 高风险动作审批闸门 + 审计留痕 + 单测 | `core/safety/approval.py`、`core/tools/remediation.py`、`tests/` |

改造原则：**外挂式**。旧的文本协议实现原样保留（`core/agent.py`），新实现并存，
这样"两种解法的对照"才是真的，而不是把旧代码删了假装一直这么写。

### 已经测出来的真数（离线，随时可复现）

| 指标 | 结果 | 复现命令 |
|---|---|---|
| 文本协议解析鲁棒性 | 48 条样本中 **26 条**与模型意图不符（**54%**） | `python3 scripts/parse_benchmark.py` |
| 单测 | **44 个通过**（stock-insight 31 + sre-oncall 13） | `python3 -m pytest tests -q` |
| 工具描述 token | 文本 **343** → JSON Schema **1205**（+862） | `python3 scripts/prompt_size.py` |
| 6 轮累计 prompt token | 旧版 **36135** vs 新版 **41292**（新版更贵 +5157） | 同上 |

> 解析语料是**构造**的，衡量的是"某类输出一旦出现必然失败"的**结构性脆弱**，
> 不是线上失败率。面试时也要这么说，别把构造语料说成线上统计。

**这里有个和直觉相反的结论，务必记住**：换成原生 `tool_calls` 之后 token **不降反升**
（schema 固定开销 +862/次）。它买的不是成本，是**可靠性**（解析正确率 46% → 结构性 100%）。
真正的 token 优势在**可裁剪性**：消息数组能按条丢旧工具结果，旧版一整段字符串只能整体截断。

> 面试时说"我用 function calling 把 token 降了 40%"，一被追问 schema 开销就露馅；
> 说"它更贵，但换来的是解析失败从结构性不可能变成 0"，才是做过的人。

### 还没有数字的（必须你跑，脚本已备好）

| 缺什么 | 命令 | 说明 |
|---|---|---|
| 端到端延迟 / token / 成本 | `python3 scripts/benchmark.py --runs 5` | 无 key 直接退出码 2，**不生成假数据** |
| 写作模式成本表 | `python3 scripts/cost_report.py --write COST_COMPARISON.md` | 同上 |
| 工具层真实耗时 | 无脚本 | **当前机器跑不了**：`akshare` 走 `82.push2.eastmoney.com`，SSL 被重置 |

> 关于"能不能用 opencode TUI 当模型后端"：不行。本地 server（127.0.0.1:49374）
> 只提供会话/网页接口，`POST /v1/chat/completions` 返回 **405**，没有 OpenAI 兼容端点。
> 想拿真实模型延迟，必须给一个 OpenAI 兼容的 key。

### 每样改完必须能讲的（3 分钟，讲不出＝没做）

1. **tool_calls**：为什么文本协议脆弱？举 54% 里的两个具体形态（全角冒号、多行参数被截断）
2. **trace**：一次分析花多少 token、成本怎么算、为什么未知模型报"未知"而不是 0
3. **HITL**：为什么默认 `auto_deny`、审计日志里记了什么、拒绝后 agent 该退化成什么行为


## 四、选做（有余力再看，别占主线时间）

| 项目 | 什么时候看 | 理由 |
|---|---|---|
| https://github.com/openai/openai-agents-python | W2 之后 | 30k star，代码极简，1 小时读完；用来对比"最小 agent 框架"与 LangGraph 的重量级设计 |
| https://github.com/pydantic/pydantic-ai | W3 之后 | 强类型 + 依赖注入，最能体现 Python 工程素养；Java 出身的人看着最亲切 |
| https://github.com/huggingface/smolagents | 随时 | 2 小时读完，理解"code as action"范式 |
| https://github.com/All-Hands-AI/OpenHands | 想面更偏后端的岗 | 事件流 + Docker 沙箱 + 多 runtime，最像真实后端系统；但太大，只挑模块读 |
| https://github.com/TauricResearch/TradingAgents | 当阅读材料 | 架构清晰、有中文语境价值；但业务是金融，只读 `graph/` + `agents/` 即可，**别逐行** |

---

## 五、明确不做的事（防跑偏）

1. **不再二次重构存量项目**——三个项目的外挂式改造已完成（见第三节），旧实现原样保留做对照；再重构就是纯亏
2. **不读大仓库全文**（TradingAgents / crewAI / OpenHands 全读 = 一周没了，收益极低）
3. **不追新框架**：AutoGen、微软 Agent Framework、CrewAI 只需知道"定位 + 一句话差异"，写进对比表就够
4. **不刷"Agent 入门教程"**：你的 L1 已经够了，再刷是舒适区
5. **不做量化/交易类 demo**：与目标岗位无关，容易被追问夏普、过拟合而失分

---

## 六、出师线（8 条，全过才算复习完成）

- [ ] 1. 画出 deepagents 的三层架构（backend / middleware / subagent），并说出它解决了自研方案的哪个问题
- [ ] 2. 手写一个 LangGraph 图：4 个并行节点 + 1 个汇聚节点 + checkpointer，中断后能恢复
- [ ] 3. 解释 state reducer 是什么、不加会出什么 bug
- [ ] 4. 解释 recursion limit 与 agent 工具死循环的关系，给出兜底方案
- [ ] 5. 给出"LLM 调用层高可用"的六层方案（上游/路由/降级/配额/缓存/归因）
- [ ] 6. 跑过一次 ≥10 条用例的回归评测，能报出通过率与成本变化
- [ ] 7. 讲清 Function Calling 与 MCP 的关系，并有一个可运行的 MCP server
- [ ] 8. 三个面试故事，各能讲 3 分钟、被追问 5 层不崩

配套自测表见 [checklist.md](./checklist.md)，资源清单见 [resources.md](./resources.md)。

---

## 七、面试一句话收尾（背下来）

> 我不是"会调 API 的后端"，我是能把 Agent 当成一个**分布式系统**来设计的人：
> 编排层管状态与恢复，调用层管路由与降级，工具层管协议与权限，上层管可观测与回归。
> 这四层里，只有第一层是新的，后三层我做了二十年。
