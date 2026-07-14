# AI Agent 学习项目

四个 AI Agent 项目，覆盖真实业务场景，展示多种 Agent 范式的完整实现。每个项目均支持 **SKILL.md（方案A）** 和 **opencode 子 Agent（方案B）** 两种使用方式，零框架依赖。

## 项目

| 项目 | 场景 | Agent 范式 | 核心亮点 |
|------|------|-----------|---------|
| [sre-oncall](./sre-oncall/) | SRE 告警分诊与根因调查 | Plan-and-Solve + ReAct + Reflection | 三阶段流水线，3 个告警样本 + 应急预案 |
| [stock-insight](./stock-insight/) | A 股智能多维度分析 | ReAct + PlanSolve + Reflection | 18 个工具，记忆系统，RAG 知识库，上下文管理 |
| [column-writer](./column-writer/) | 多 Agent 专栏写作 | PlanSolve + ReAct + Reflection + 独立评审 | 4 种 Agent 模式对比，树状递归写作，搜索验证 |
| [invoice-to-pay-agent](https://github.com/mshojaei77/invoice-to-pay-agent) | 应付账款自动化 | LangGraph 状态机 + HITL 中断 | 40+ 状态节点，发票解析/去重/防欺诈/合规/审批路由/ERP 过账 |

## 快速开始

```bash
# SRE On-Call
cd sre-oncall
pip install openai python-dotenv pyyaml
cp .env.example .env    # 填 LLM_API_KEY
python3 core/cli.py db_pool_exhaustion

# Stock Insight
cd stock-insight
pip install openai python-dotenv akshare numpy pandas
cp .env.example .env    # 填 LLM_API_KEY
python3 core/cli.py "分析贵州茅台" --mode react

# Column Writer
cd column-writer
pip install openai python-dotenv pydantic pydantic-settings
cp .env.example .env    # 填 LLM_API_KEY
python3 core/cli.py

# Invoice-to-Pay Agent
gh repo clone mshojaei77/invoice-to-pay-agent
cd invoice-to-pay-agent
# 参见 https://github.com/mshojaei77/invoice-to-pay-agent 完整说明
```

## 开发原则

- **零框架依赖**: 所有 Agent 纯 Python 实现，不依赖 hello-agents / LangChain / CrewAI
- **方案 AB 共存**: 每个项目的 `.cursor/skills/` 和 `.opencode/agents/` 各自维护独立入口
- **核心逻辑共享**: `core/` 目录下的 Python 代码被方案 A 和方案 B 共同使用
- **面试友好**: 每个项目均含 `INTERVIEW.md`，覆盖 15+ 面试问答

---

## 面试项目推荐

| 面试场景 | 推荐项目 | 推荐理由 |
|---------|---------|---------|
| **通用 Agent 岗位** | [stock-insight](./stock-insight/) | 功能密度最高（18 工具+记忆+RAG+上下文管理），金融背景契合，原创代码能接住任何追问 |
| **架构/系统设计岗** | [column-writer](./column-writer/) | 4 种 Agent 模式横向对比展示架构选型能力，组件解耦合（Planner/Writer/Reviewer/Revision 各司其职） |
| **运维/金融垂直岗** | [sre-oncall](./sre-oncall/) | 三阶段 SRE 流水线，场景最专业，代码最小但范式齐全，可直接接真实数据源 |
| **补充提及（不做主力）** | [invoice-to-pay-agent](https://github.com/mshojaei77/invoice-to-pay-agent) | 展示对 LangGraph 状态机和企业流程自动化的研究，但非原创代码，追问答不出细节 |

**建议策略**：主攻 **[stock-insight](./stock-insight/)**（功能最全，能聊 30 分钟），在聊"Agent 范式选型"时引入 **[column-writer](./column-writer/)** 作为多模式对比的案例。
