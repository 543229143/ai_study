# Column Writer — 面试问答

---

## 基础概念

### Q1: 这个系统用了哪些 Agent 模式？
**A:** 4 种：Plan-and-Solve（规划专栏）、ReAct（搜索+写作）、Reflection（自我反思优化）、Independent Review（独立评审+修改）。一个系统里同时展示 4 种，面试时可以横向对比每种模式的适用场景和优劣。

### Q2: 为什么在同一个系统里用多种 Agent 模式？
**A:** 不同任务适合不同模式。规划阶段需要全局视野，Plan-and-Solve 一次性分解最优；写作过程可能需要查资料验证事实，ReAct 的 Thought→Action→Observation 循环更灵活；质量打磨需要批判性思维，Reflection 的 draft→critique→refine 更合适。这是工程决策——不是"哪种模式最好"，而是"什么任务用什么模式"。

### Q3: Plan-and-Solve 在 PlannerAgent 里怎么实现的？
**A:** 一个 prompt 让 LLM 输出完整专栏大纲（JSON 列表），用 `ast.literal_eval` 或 `JSONExtractor` 解析。如果失败了就 fallback 到硬编码单话题计划。每个步骤有文件缓存（MD5 hash key），相同 topic+step 不会重复调 LLM。

### Q4: ReAct 循环的终止条件是什么？
**A:**
1. LLM 输出 `Finish[JSON]` — 正常完成
2. 达到 `max_steps=8` — 防止无限循环
3. LLM 返回空响应 — 异常终止
4. 多策略解析：用正则从 `Finish[...]`、````json```、裸 JSON、甚至混杂文本中提取内容

### Q5: Reflection 的 critique 怎么做的？
**A:** 一个专门的 prompt 让 LLM 用第一人称（"我"）反思草稿的不足，输出 Reflections + Next Steps。然后把反思结果传给 refine prompt 做修改。最多 2 轮，除非 LLM 说"无需改进"提前结束。

---

## 工具系统

### Q6: 搜索工具怎么接的？
**A:** 优先 Tavily（推荐），降级到 SerpAPI，都不配就告诉用户"搜索不可用"。代码从原始的 `search_mcp_server.py` 提取，去掉了 FastMCP Server 的包装，改成直接在 Agent 里调用的 `SearchClient`。一个工具 4 个方法：web_search、search_recent_info、search_code_examples、verify_facts。

### Q7: 为什么不用 MCPTool 了？
**A:** MCPTool 需要额外跑一个 npx 进程，对 CLI 工具场景来说太重。直接用 Tavily/SerpAPI SDK 更轻量，不需要额外 server 进程。而且 MCP 对面试来说不如"直接调 API"好讲清楚。

---

## JSON 提取

### Q8: 为啥要写那么复杂的 JSONExtractor？
**A:** 因为 LLM 的输出格式不稳定。实测中 LLM 可能返回：`Finish[{...}]`、````json{...}```、裸 `{...}`、甚至混着聊天文本。JSONExtractor 按优先级尝试 5 种策略，最后一种是从所有大括号里暴力提取最可能的 JSON 对象。这不是"设计过度"，是生产级 LLM 应用的必修课。

### Q9: 如果 LLM 完全不按格式输出怎么办？
**A:** JSONExtractor 的 `_rebuild_json_from_fields` 方法——即使整个 JSON 解析失败，它也会用正则单独提取 title、level、content 字段，然后重新拼装成一个合法的 JSON 对象。属于最后的兜底策略。

---

## 工程决策

### Q10: 从 hello-agents 框架改到纯 Python，最大的改动是什么？
**A:** `agents.py` 一个文件。640 行里要替换 8 处框架导入（HelloAgentsLLM、ReActAgent、ReflectionAgent、PlanAndSolveAgent、SimpleAgent、MCPTool、ToolRegistry、SearchTool）。其他 7 个 py 文件零改动。结论：框架依赖完全可以避免，核心业务逻辑本质上是纯 Python。

### Q11: 为什么要缓存 Planner 的每一步？
**A:** 用户可能在规划阶段反复调整主题，缓存的 step 可以复用。用 `hashlib.md5(topic + step_index)` 做 key，JSON 文件落盘。下一步可以升级到 LRU 缓存或 SQLite。

### Q12: Reviewer 的评分逻辑怎么设计的？
**A:** 4 个维度评分（内容质量 40 分、结构逻辑 30 分、语言表达 20 分、格式规范 10 分）。总分 100 分 > 75 直接通过，60-75 需要修改，< 60 分重写。阈值通过 `APPROVAL_THRESHOLD`/`REVISION_THRESHOLD` 环境变量配置。

### Q13: 和直接调用 GPT 写文章有什么区别？
**A:** 本质区别是"Agent 不是一次调用，而是一个有反馈闭环的工作流"：
  - Planner 先分解保证结构完整
  - Writer 用 ReAct 循环可以查资料验证事实，不是凭训练数据编
  - Reviewer 加 Revision 形成质量闭环
  - Reflection 模式让 LLM 自己批判自己
  每种模式对应真实写作流程中的一个环节，不是"一次生成完事"。

---

## 深度思考

### Q14: 你觉得这个系统最大的局限性在哪？
**A:**
- **搜索质量依赖于 Tavily/SerpAPI**：免费版有限额，工业级需要接搜索引擎 API
- **文章质量缺乏结构化评估**：Reviewer 的评分是 LLM 自己打自己的，存在"看起来合理但其实错了"的风险
- **深度控制是硬限制**：`max_depth=3`，递归展开时如果 LLM 生成很多 subsection，内容量可能超出预期
- **缺乏领域知识注入**：目前全靠 LLM 训练数据，没有对接企业内部知识库

### Q15: 如果要改进成生产系统，第一步做什么？
**A:** 三个方向：
1. **Function Calling** 替换 ReAct 正则解析：更稳定、错误率更低
2. **分步确认**：每个 Agent 的输出先给用户确认再走下一步（Human-in-the-Loop），避免从头到尾生成完发现跑偏
3. **并行写作**：多个话题同时走 WriterAgent，当前是顺序的（`_write_topics_sequential`），配置里有 `enable_parallel` 但没实现
