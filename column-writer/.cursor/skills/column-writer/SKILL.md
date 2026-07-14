---
name: column-writer
description: >-
  多 Agent 专栏写作系统。集成了 Plan-and-Solve（规划）、ReAct（推理写作）、
  Reflection（自我反思）、独立评审 4 种 Agent 模式。自动完成从选题规划到文章生成的完整工作流。
---

# Column Writer

当用户提出写专栏、写系列文章、内容创作等需求时使用本 skill。

## 运行方式

```bash
# 交互模式
python3 core/cli.py

# 直接指定主题
python3 core/cli.py "Python异步编程完全指南"

# 在交互界面选择 ReAct 模式（默认）或 Reflection 模式
```

## 4 种 Agent 模式

| 模式 | 用途 | 说明 |
|------|------|------|
| Plan-and-Solve | 专栏规划 | Planner 拆解主题 → CachedExecutor 逐步执行（带文件缓存） |
| ReAct | 内容写作 | Thought→Action→Observation 循环，可调搜索引擎验证事实 |
| Reflection | 自我反思 | generate→critique→refine，最多 2 轮自动优化 |
| Independent Review | 独立评审 | 评审 Agent 打分 + Revision Agent 修改，70 分以下重写 |

## 输出

生成到 `output_<timestamp>/` 目录，包含：
- 每篇文章单独 .md 文件
- 完整 column_data.json
- REPORT.md 统计报告
