# 四种写作模式的成本 / 质量对照

> 这张表**还没填数字**。跑下面这条命令，它会自动覆盖本文件：
>
> ```bash
> export LLM_API_KEY=sk-xxx
> export LLM_MODEL_ID=deepseek-chat        # 或 gpt-4o-mini
> python3 scripts/cost_report.py --topic "AI 时代的后端工程师" --runs 1 --write COST_COMPARISON.md
> ```

## 为什么这张表值得讲

面试官问"为什么不用最强最贵的模型"时，大多数人的回答是"成本考虑"——这是一句空话。
这张表能把它变成一次**取舍**：

- 同一主题、同一质量门槛（首稿通过率）下，两种模式的 token 差多少
- 多花的钱换来了什么（返修次数减少？还是没区别？）
- 如果没区别，那多花的钱就是浪费——**敢说自己选错了，比说选对了更可信**

## 表格（待填）

| 模式 | 中位耗时 | token | 单篇成本 | LLM 调用次数 | 首稿通过 | 返修次数 |
|---|---|---|---|---|---|---|
| ReAct + 评审返修 | — | — | — | — | — | — |
| Reflection 自省 | — | — | — | — | — | — |

## 口径说明（讲的时候要带上）

- 单机、单轮、N 次取中位数，不代表生产
- 成本按 `scripts/cost_report.py` 内置价格表估算；换模型请用 `LLM_PRICE_INPUT_PER_M` / `LLM_PRICE_OUTPUT_PER_M` 覆盖
- "首稿通过"来自 `orchestrator.stats['approved_first_try']`，是项目自带的评审阈值判定，不是人工评分
