# Datawhale 学习计划：AI Agent & RAG

> 周期：12 周 | 每周 3-6 小时 | 编程基础 √ | 目标：Agent + RAG

---

## 资源索引

| 资源 | 链接 | 说明 |
|------|------|------|
| hello-agents | https://hello-agents.datawhale.cc | 智能体系统教程（65.8k star） |
| all-in-rag | https://datawhalechina.github.io/all-in-rag/ | RAG 全栈指南 |
| deepagents-in-action | https://datawhalechina.github.io/deepagents-in-action/ | LangChain/LangGraph 实战 |
| llm-cookbook | https://github.com/datawhalechina/llm-cookbook | LLM 入门教程（吴恩达中文版） |
| self-llm | https://github.com/datawhalechina/self-llm | 大模型部署与微调 |

---

## Phase 1：LLM 与 RAG 基础（第 1-4 周）

> 目标：理解 LLM 工作原理，搭建完整的 RAG 系统

### 第 1 周 · LLM 基础 + 环境搭建（3h）

- [ ] 阅读 `llm-cookbook`：Prompt 基础 + 调用 LLM API
- [ ] 注册模型平台（硅基流动 / DeepSeek / 任意 API）
- [ ] 跑通第一个 LLM 调用脚本（Python）
- [ ] 熟悉 `all-in-rag` 项目结构

**产出**：能在本地用 Python 调通 LLM API

### 第 2 周 · RAG 入门（4h）

- [ ] `all-in-rag` 第一章：RAG 简介 + 四步构建 RAG
- [ ] `all-in-rag` 第二章：数据加载与文本分块
- [ ] 动手：用 LangChain 实现一个简单的文档问答

**产出**：能对本地文档做基础问答

### 第 3 周 · 索引构建与向量检索（4h）

- [ ] `all-in-rag` 第三章：向量嵌入、向量数据库、索引优化
- [ ] 动手：搭建 Milvus / Chroma 向量库
- [ ] 实践：文档分块 → 向量化 → 存储 → 检索

**产出**：一个带向量检索的 RAG 系统原型

### 第 4 周 · 检索优化与系统评估（4h）

- [ ] `all-in-rag` 第四章：混合检索、查询重构、Text2SQL
- [ ] `all-in-rag` 第六章：RAG 系统评估
- [ ] 动手：对比不同检索策略的效果

**产出**：一个可评测的 RAG 系统 + 评估报告

---

## Phase 2：RAG 项目实战（第 5-6 周）

> 目标：完成一个完整的 RAG 应用项目

### 第 5 周 · RAG 实战项目一（5h）

- [ ] `all-in-rag` 第八章：实战项目一（企业知识库问答）
- [ ] 数据准备模块 + 索引构建
- [ ] 检索优化 + 生成集成

**产出**：知识库问答系统基础版

### 第 6 周 · Graph RAG 与项目优化（5h）

- [ ] `all-in-rag` 第七章：知识图谱 RAG
- [ ] `all-in-rag` 第九章：Graph RAG 优化实战
- [ ] 对比：普通 RAG vs Graph RAG 效果差异

**产出**：带知识图谱的增强 RAG 系统

---

## Phase 3：AI Agent 入门（第 7-9 周）

> 目标：理解 AI Agent 核心范式，从零构建智能体

### 第 7 周 · Agent 基础与经典范式（4h）

- [ ] `hello-agents` 第 1-3 章：智能体定义、发展史、LLM 基础
- [ ] `hello-agents` 第 4 章：手写 ReAct、Plan-and-Solve、Reflection
- [ ] 动手：实现一个 ReAct 模式的简单 Agent

**产出**：能调用工具的多步推理 Agent

### 第 8 周 · Agent 框架与低代码平台（4h）

- [ ] `hello-agents` 第 5 章：Coze / Dify / n8n 低代码平台
- [ ] `hello-agents` 第 6 章：AutoGen / LangGraph 等框架
- [ ] `hello-agents` 第 7 章：从零构建 Agent 框架

**产出**：基于 LangGraph 的 Agent 应用

### 第 9 周 · Agent 高级主题（5h）

- [ ] `hello-agents` 第 8 章：记忆与检索系统
- [ ] `hello-agents` 第 9 章：上下文工程
- [ ] `hello-agents` 第 10 章：MCP / A2A 通信协议
- [ ] `hello-agents` 第 12 章：智能体性能评估

**产出**：带记忆系统的 Agent

---

## Phase 4：Deep Agents 与生产级实践（第 10-12 周）

> 目标：掌握生产级 Agent 开发，完成综合项目

### 第 10 周 · Deep Agents 入门（4h）

- [ ] `deepagents-in-action` 准备篇：环境搭建
- [ ] `deepagents-in-action` 第 1-2 章：理解 Agent Harness + 快速上手
- [ ] `deepagents-in-action` 第 3 章：虚拟文件系统（Context Engineering 核心）
- [ ] 动手：5 分钟构建第一个 Deep Agent

**产出**：跑通 Deep Agents 并理解其设计思想

### 第 11 周 · Deep Agents 核心能力（5h）

- [ ] `deepagents-in-action` 第 4 章：任务规划与分解
- [ ] `deepagents-in-action` 第 5 章：子 Agent 与上下文隔离
- [ ] `deepagents-in-action` 第 6 章：异步子 Agent
- [ ] `deepagents-in-action` 第 7 章：Skills（可复用能力包）

**产出**：支持任务拆分 + 子 Agent 协作的系统

### 第 12 周 · 综合项目：RAG + Agent 融合（6h）

- [ ] `deepagents-in-action` 第 8-10 章：长期记忆、HITL、沙箱执行
- [ ] 设计综合项目：RAG 知识库 + Agent 智能助手
- [ ] 参考 `hello-agents` 第 13 章（智能旅行助手）或第 14 章（DeepResearch Agent）

**交付项目**：一个完整的 RAG + Agent 融合应用（如智能文档助手 / 企业知识助手）

---

## 每周节奏建议

| 时间 | 安排 |
|------|------|
| 工作日（30min × 2天） | 阅读文档 / 看视频 / 理解概念 |
| 周末（2-3h × 1天） | 动手写代码 / 跑实验 / 做项目 |

## 学习原则

1. **先跑通再理解** — 每个项目先 clone 下来跑通，再回头看原理
2. **记实验笔记** — 记录参数、结果、踩坑，方便回顾
3. **别贪多** — 每周聚焦一个核心交付物
4. **遇到问题先看 issue** — Datawhale 仓库的 issue 区很多常见问题已有解答
5. **社区交流** — 加微信 `at-Sm1les` 进 Datawhale 交流群

## 项目交付清单

| 阶段 | 项目 | 完成 |
|------|------|------|
| W4 | 基础 RAG 问答系统 | ☐ |
| W6 | Graph RAG 知识库系统 | ☐ |
| W8 | 基于 LangGraph 的 Agent 应用 | ☐ |
| W9 | 带记忆的 Agent 系统 | ☐ |
| W11 | 多子 Agent 协作系统 | ☐ |
| W12 | RAG + Agent 综合项目 | ☐ |
