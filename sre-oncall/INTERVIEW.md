# SRE On-Call Agent — 面试问答

---

## 基础概念

### Q1: 这个 Agent 的架构是怎样的？
**A:** 三阶段流水线：Triage（Plan-and-Solve 生成排查计划）→ Investigation（ReAct 循环执工具）→ Postmortem（Reflection 生成并打磨复盘报告）。每个阶段是独立的 Agent 类，通过 `pipeline.py` 编排。

### Q2: 什么是 ReAct 模式？在这个项目里怎么实现的？
**A:** ReAct = Reasoning + Acting。LLM 每一步输出 Thought（推理当前应该做什么）+ Action（调具体工具+参数），拿到 Observation（工具返回值）后继续下一轮，直到输出 Finish[] 结束。本项目用正则 `Thought:\s*(.*?)Action:\s*(.*?)$` 解析 ReAct 输出，不依赖 function calling。

### Q3: Plan-and-Solve 和 ReAct 的区别？
**A:** Plan-and-Solve 是"先做完计划再执行"，ReAct 是"想一步做一步"。TriageAgent 先用一个 prompt 让 LLM 输出完整排查步骤列表（`[{tool, query, reason}]`），InvestigationAgent 再逐步执行。前者适合有明确结构的分析，后者适合需要动态调整的探索。

### Q4: Reflection 模式怎么运作的？
**A:** Draft → Critique → Revise 循环。PostmortemAgent 先生成初稿 → 再用一个 prompt 让 LLM 自评（1-10 分 + 问题列表 + 改进建议）→ 如果分数 < 8，就用改进建议重新生成报告。最多迭代 1 轮（可通过 `max_revisions` 调整）。

### Q5: 为什么用正则解析而不是 function calling？
**A:** 
- **框架无关性**：正则解析可以在任何 LLM 上工作，不依赖特定 API 的 tool calling 机制
- **透明可控**：每一步的 Thought/Action 都记录在 history 里，方便调试
- **跨模型兼容**：换 DeepSeek / Qwen / Gemini 都不需要改工具定义格式

---

## 工具设计

### Q6: 三个工具是怎么设计的？
**A:** 每个工具遵循统一接口：`name`（标识符）、`description`（给 LLM 看的说明）、`run(query)`（执行方法）。没有抽象基类，用 convention over configuration。工具持有 incident 数据引用，查询的就是当前告警下的日志/指标/预案。

### Q7: log_search 工具怎么避免误匹配？
**A:** 用 `re.compile(query, re.IGNORECASE)` 编译查询词，如果正则编译失败就 `re.escape` 退化为普通字符串匹配。同时对 log 的 level + message + source 三个字段做匹配。

### Q8: 如果工具查不到结果怎么办？
**A:** 返回明确的 `"No matching results found"` 消息（带可用选项列表），而不是返回空字符串。这让 LLM 能判断是"没查到"而不是"工具执行异常"，并据此调整后续的 Action。

---

## 工程决策

### Q9: 为什么不用 hello-agents / LangChain / CrewAI 等框架？
**A:** 本项目所有 Agent 都是纯 Python 类，零框架依赖。原因：
- 框架引入不必要的抽象层，增加调试难度
- 教学/面试场景下，手写实现更能展示对 Agent 原理的理解
- 生产环境就一个 `openai` pip 依赖即可跑

### Q10: 历史踩坑去重是怎么做的？
**A:** InvestigationAgent 维护一个 `called_actions` set，用 `tool_name[query]` 做 key。如果 LLM 企图调用同一个 tool+query 组合，直接 skip 并在 history 里记录提示。避免推理循环（ReAct 常见陷阱）。

### Q11: Pipeline 失败时如何降级？
**A:** 
- TriageAgent: LLM 返回无法解析时，fallback 到硬编码的 5 步通用排查计划
- InvestigationAgent: LLM 返回空响应时退出循环，保留已收集的 evidence
- PostmortemAgent: critique 解析失败时直接返回初稿，不阻断流程

### Q12: 系统如何扩展新的 incident？
**A:** 
1. 在 `data/incidents/` 下新增 JSON 文件（含 logs + metrics）
2. 在 `data/runbooks/runbooks.yaml` 新增该服务的预案
3. 无需修改任何代码，按约定发现

---

## 深度思考

### Q13: 你觉得这个设计的最大局限是什么？
**A:** 
- **工具数据是静态的**：实际生产需要动态接入 Loki/CloudWatch/Prometheus 等数据源
- **ReAct 循环可能陷入死循环**：虽然做了去重，但如果 LLM 坚持用不同的 query 查同一个方向，会浪费 token
- **单实例巡检**：不支持跨服务关联分析。实际 SRE 排查通常需要关联多个服务的日志和指标

### Q14: 如果要接入真实生产数据，你会怎么改？
**A:** 
1. 工具抽象出 `DataProvider` 接口（`search_logs(query, time_range)` → `list`）
2. 实现 `MockDataProvider`（当前行为）和 `LokiDataProvider` / `CloudWatchDataProvider`
3. Pipeline 初始化时注入对应的 Provider
4. 工具不再持有 incident 数据，改为通过 Provider 动态查询

### Q15: 这个 Agent 的记忆机制在哪？为什么没加？
**A:** 没有长记忆，因为 SRE 排障是"一次性"任务——每个 incident 独立处理。但如果要加：
- 短期记忆：已有 history 字符串（ReAct 循环内累积）
- 长期记忆：可以把历史 RCA 报告向量化，新 incident 时检索相似案例 → 加速排查
