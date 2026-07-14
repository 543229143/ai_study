# Stock Insight Agent — 面试问答

---

## 基础概念

### Q1: 这个项目中实现了哪三种 Agent 范式？各适合什么场景？
**A:**
| 范式 | 流程 | 适用场景 | 速度 |
|------|------|---------|------|
| **ReAct** | Thought → Action → Observation 循环 | 日常查询、快速分析 | ~30s |
| **PlanSolve** | Planner分解 → Executor逐步执行 | 深度研究、多维度分析 | ~2min |
| **Reflection** | 生成初稿 → 自评 → 改进 | 需要批判性思考、高质量输出 | ~3min |

### Q2: ReAct 的循环终止条件是什么？
**A:**
1. LLM 输出 `Action: Finish[...]` — 认为已找到答案
2. 达到 `max_steps`（默认 6 步）上限 — 防止无限循环
3. LLM 返回空响应 — 异常终止

### Q3: PlanSolve 的 Planner 和 Executor 怎么协作的？
**A:** Planner 用一个 prompt 让 LLM 输出 Python 列表的步骤（`ast.literal_eval` 解析，失败时有默认计划），Executor 逐步执行。每步最多调 3 次工具，完成后标记 `Action: Done[...]`，全部完成后输出 `Action: Finish[...]`。这种设计的优点是"先全局规划后局部执行"，对比 ReAct 的"边走边看"更系统但更慢。

### Q4: Reflection 模式的 critique 是怎么做的？
**A:** 单独用一个 prompt（`REFLECTION_PROMPT`）让 LLM 对初稿从 5 个维度评分：数据完整性、风险覆盖、逻辑一致性、盲区检查、反向思考。如果输出"无需改进"或被改进建议，再调用 `REFINE_PROMPT` 让 LLM 根据反馈重写报告。最多迭代 2 轮。

---

## 工具系统

### Q5: 18 个工具是怎么注册和管理的？
**A:** 用 `ToolExecutor` 类实现。核心是一个 `_tools` 字典：`{name: {description, func}}`，提供 `register(name, desc, func)` 注册和 `run(name, query)` 执行。不依赖任何框架的 `ToolRegistry`。工具分为 5 类：数据（5 个）、记忆（7 个）、知识库（3 个）、上下文（3 个）。

### Q6: 技术指标是怎么算的？调了什么库？
**A:** 全部手写，不调外部指标库：
- MA: `np.mean(close[-n:])`
- MACD: `pd.Series(close).ewm(span=12).mean()` — EMA12/EMA26 做差得 DIF，DEA 是 DIF 的 9 日 EMA
- RSI: `100 - (100 / (1 + RS))`，其中 `RS = avg_gain / avg_loss`
- 布林带: `ma20 ± 2 * std20`
- 支撑/压力位: 近 60 日最低价/最高价

### Q7: akshare 是什么？如果它挂了怎么办？
**A:** akshare 是 Python 金融数据接口库，封接了东方财富、新浪、腾讯等免费数据源。每个工具函数都有 `try/except` 包裹，数据源挂掉时返回 `"{工具名}获取失败: {异常信息}"`，不会阻断整个分析流程。

---

## 记忆与知识库

### Q8: 记忆系统是怎么设计的？
**A:** JSON 文件持久化（`data/memory/` 目录），用 `threading.Lock` 保证线程安全。分三个维度：
- **关注列表**: `watchlist.json` — 用户的股票关注列表
- **分析历史**: `history.json` — 按 `{code: [{question, summary, timestamp}]}` 结构存储
- **用户偏好**: `preferences.json` — key-value 对（如 `risk_tolerance=medium`）

### Q9: RAG 知识库用了什么向量模型？
**A:** 没有用向量模型，用的是 **TF-IDF + 中文 2-gram 分词**。轻量、零依赖、无需 GPU。对中文文本用 `re.findall(r'[\u4e00-\u9fff]{1,2}', text)` 做 unigram/bigram 分词，用 `Counter` 算 TF 和 IDF，最后 cosine-like 排序。特别适合句子级别的检索（知识库内容本身不长）。

### Q10: 为什么不用 Embedding + 向量数据库？
**A:** 
- 知识库只有几百段文本，TF-IDF 精度已经够用
- 零额外依赖 — 不引入 `sentence-transformers` 等重依赖
- 面试场景适合展示算法理解 — "我没有直接调 API，我知道 TF-IDF 怎么算的"

---

## 上下文管理

### Q11: 上下文压缩是做什么的？怎么避免丢信息？
**A:** ContextManager 维护一个 `_turns` 列表。当总字符数超过 `max_tokens * 4`（简体中文约 1 token ≈ 4 chars），触发压缩：
1. 取前 N-4 轮对话
2. 每轮取前 100 字符做摘要
3. 打包成一条 `system` 消息
4. 保留最近 4 轮对话不压缩

这个设计确保最近的对话内容不会被压缩，LLM 始终保持对当前话题的理解。

---

## 工程决策

### Q12: 为什么有一份手写版一份框架版（framework_agent.py）？
**A:** `agent.py` / `plan_agent.py` / `reflection_agent.py` 是三种范式的**完整手写实现**，展示了底层原理。`framework_agent.py` 提供了统一的 `FrameworkStockAgent` 入口，对调用方屏蔽不同范式之间的差异。这是真实工程中的常见模式：内部有多个实现，外部暴露统一接口。

### Q13: framework_agent.py 和之前的 hello-agents 版本有什么区别？
**A:** 原始版本依赖 `from hello_agents import ReActAgent, PlanSolveAgent, ReflectionAgent, ToolRegistry`。重构后：
- **无任何框架依赖**，直接调用手写的三个 Agent 类
- `ToolRegistry` 被自己的 `ToolExecutor` 替代
- 代码逻辑更透明——面试时可以一行行讲清楚 ReAct 循环怎么跑的

### Q14: Token 消耗是怎么控制的？
**A:**
1. ContextManager 自动压缩（超阈值时只保留摘要 + 最近 4 轮）
2. ReAct history 只记录 Thought/Action/Observation 的精简格式
3. 数据工具返回时做截断（如 K 线只取 tail days，新闻只取 5 条）
4. `max_steps=6` 限制 ReAct 循环次数

---

## 深度思考

### Q15: 如果让你把这个项目投入生产，你会改什么？
**A:**
1. **Function Calling 替代正则解析**: 生产环境用 OpenAI tool calling 或 Claude tool_use，比正则解析 ReAct 输出更可靠
2. **数据源高可用**: akshare 是免费库，生产建议接入收费数据 API（Wind/东方财富企业版）并加熔断/降级
3. **模型选择策略化**: react → 便宜模型（deepseek-chat），plan/reflect → 强模型（claude-sonnet），省钱
4. **Gradio 改 React 前端**: 当前前端比较简单，生产需要更好的交互
5. **记忆迁移到 SQLite**: JSON 文件在并发下不安全

### Q16: 你觉得 PlanSolve 和 ReAct 哪个更好？
**A:** 取决于场景。PlanSolve 更系统（先全貌后细节），适合"全面评估"类深度分析。ReAct 更快，适合"查个行情、问个指标"的快速查询。这个项目同时实现了两种，不是为了比较优劣，而是展示"不同范式适合不同问题"的工程判断能力。

### Q17: 如果我只有 5 分钟介绍这个项目，应该讲哪三点？
**A:**
1. **三种 Agent 范式的手写实现** — 展示对 agent 原理的深层理解
2. **18 个工具的模块化设计** — 数据/记忆/RAG/上下文四层分离
3. **从框架依赖到完全剥离的重构过程** — 展示架构决策能力
