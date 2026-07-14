---
name: stock-insight
description: >-
  A股智能多维度分析。从技术面、基本面、消息面三维度综合分析股票。
  支持三种分析范式：ReAct反应式、PlanSolve规划式、Reflection反思式。
  内置记忆系统、投资知识库、上下文管理。
---

# Stock Insight Agent

当用户提出股票分析、行情查询、技术指标、估值分析等需求时使用本 skill。

## 运行方式

```bash
# 交互式
python3 core/cli.py

# 命令行
python3 core/cli.py "分析贵州茅台的估值和风险" --mode react
python3 core/cli.py "全面评估比亚迪" --mode plan
python3 core/cli.py "中国平安现在是否值得买入" --mode reflect
```

## 三种分析范式

| 模式 | 速度 | 深度 | 适用场景 |
|------|------|------|---------|
| `react` | ~30s | 中等 | 快速分析、日常查询 |
| `plan` | ~2min | 深 | 需要多维度系统性分析 |
| `reflect` | ~3min | 最深 | 需要批判性思考、质量打磨 |

## 18个可用工具

- 数据工具: GetRealtimeQuote, GetHistoricalData, GetFinancialData, CalcIndicators, GetNews
- 记忆工具: AddToWatchlist, RemoveFromWatchlist, GetWatchlist, SaveAnalysis, GetHistory, SetPreference, GetPreferences
- 知识库: SearchKnowledge, ImportDocument, KnowledgeStats
- 上下文: ContextStats, ContextClear, ContextSummarize
