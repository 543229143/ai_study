---
description: 用 cursor-agent 评审当前改动，并按策略修复
agent: build
---
当前改动的评审结果如下：

!`opencode-cr $ARGUMENTS`

处理规则：
1. blocker：必须修。若你认为不该修，单独说明理由，不许静默跳过。
2. major：先列出，等我确认再改。
3. minor：只汇报，不动代码。
4. 全部处理完后重跑一次 `opencode-cr`，最多 3 轮；出现 NO_ISSUES 就停。
