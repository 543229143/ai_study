# AI English Terminology

## Token
词元 / 令牌 — LLM 处理文本的最小单位，可以是一个字、一个词或一个子词片段。

## Tokenizer
分词器 — 将文本切分成 token 的工具，直接影响成本、跨语言和代码表现。

## Temperature
温度 — 控制输出概率分布的平滑度，低值更确定、高值更随机多样。

## Top-p (Nucleus Sampling)
核采样 — 只从累积概率达到 p 的 token 中采样，与 temperature 配合使用。

## Max Tokens
最大生成 token 数 — 限制模型输出长度的参数。

## Hallucination
幻觉 — 模型生成看似合理但实际错误或无依据的内容。

## Reasoning Budget
推理预算 — 模型在输出答案前愿意内部花多少计算去思考。

## Chain-of-Thought (CoT)
思维链 — 模型逐步展示推理过程的技术。

## TTFT (Time To First Token)
首 token 延迟 — 从请求发出到收到第一个输出 token 的时间，长上下文下容易变高。

## KV Cache
键值缓存 — 缓存 Transformer 注意力层的 Key/Value 矩阵，避免每步重复计算。

## Prompt Cache / Context Caching
提示缓存 — 跨请求共享固定前缀（如 system prompt）的预填充结果，避免重复 prefill。

## Prefill
预填充阶段 — 处理输入 token、生成 KV Cache 的阶段，TTFT 主要发生在此阶段。

## Prefix Caching
前缀缓存 — 缓存共享前缀的 KV Cache 或 attention 结果，提升多请求效率。

## Flash Attention
闪存注意力 — 一种高效注意力计算算法，减少显存读写，加速长上下文处理。

## PageAttention (vLLM)
分页注意力 — 类似操作系统的分页机制，高效管理 KV Cache 显存，减少碎片。

## Continuous Batching
连续批处理 — 动态调度请求进出批次，提高 GPU 利用率。

## RAG (Retrieval-Augmented Generation)
检索增强生成 — 在生成前从外部知识库检索相关信息作为上下文，弥补参数化知识的不足。

## RoPE (Rotary Position Embedding)
旋转位置编码 — 通过旋转矩阵注入位置信息，当前主流的位置编码方案。

## ALiBi (Attention with Linear Biases)
线性偏置注意力 — 另一种位置编码方案，通过线性偏置区分 token 距离。

## Transformer
变换器 — 基于自注意力机制的深度学习架构，现代 LLM 的基础。

## TPS (Throughput Per Second)
每秒吞吐量 — 衡量服务处理能力的指标。

## VRAM
显存 — GPU 上的内存，KV Cache 和模型权重都占用显存。

## Quantization
量化 — 降低模型参数精度（如 FP16 → INT8），减少显存占用和加速推理。

## RLHF (Reinforcement Learning from Human Feedback)
基于人类反馈的强化学习 — 用人类偏好对齐模型行为的微调方法。

## DPO (Direct Preference Optimization)
直接偏好优化 — 无需强化学习的对齐微调方法，通过直接优化偏好损失函数。

## Few-shot
少样本 — 在 prompt 中提供少量示例引导模型输出的技术。

## Schema
模式 / 结构 — 定义输出格式的结构化约束，如 JSON Schema。

## Lost in the Middle
中间信息丢失 — 模型对长上下文中间部分关注力下降的现象。

---

### Java 开发者视角类比

| 英文术语 | 中文释义 | Java 开发者视角类比 |
|----------|----------|---------------------|
| **Chain** | 链 | Pipeline / Flow（处理流水线） |
| **Runnable** | 可运行对象 | Interface（所有组件通用的基础接口） |
| **Prompt** | 提示词 | Template String（带有占位符的指令） |
| **Loader** | 加载器 | InputStream / FileIO（数据读入） |
| **Chunk** | 片段 | Paging / Segment（大对象的内存分段） |
| **Embedding** | 嵌入 / 向量化 | Semantic Hash（带语义信息的 Hash 值） |
| **Retriever** | 检索器 | DAO / Repository（专门负责查询的层） |
| **Vector Store** | 向量数据库 | Elasticsearch / Redis（支持相似度搜索的库） |
| **Output Parser** | 输出解析器 | Deserializer / Mapper（将 String 转为 Object） |
| **Retrieval** | 检索 | — |

---

## Agent
智能体 — 能围绕目标持续运行、决策和交互的系统

## Workflow
工作流 — 预定义路径的确定性编排

## Function Calling
函数调用 — 模型输出工具调用建议，程序负责执行的结构化协议

## Structured Outputs
结构化输出 — 确保模型输出严格符合给定 schema 的机制

## Tool Schema
工具模式 — 定义工具名称、参数、描述的结构化接口说明

## MCP (Model Context Protocol)
模型上下文协议 — 标准化的工具/能力接入协议

## A2A (Agent-to-Agent)
智能体间通信协议 — 用于智能体之间标准协作

## ReAct
推理与行动 — 交替进行思考和行动，利用观察结果推进任务

## Plan-and-Execute
规划与执行 — 先生成全局计划，再按步骤执行，必要时重规划

## CodeAct
代码行动 — 通过生成可执行代码表达动作的方式

## DAG (Directed Acyclic Graph)
有向无环图 — 表示任务依赖和并行关系的结构

## Agent Runtime
智能体运行时 — 智能体运行的底层基础设施

## Durable Execution
持久化执行 — 任务中断后能从断点继续执行，而不是从头重跑

## Session State
会话状态 — 当前任务的运行时状态（进度、临时变量）

## State Machine
状态机 — 管理阶段、转移、挂起和恢复的系统

## Human-in-the-Loop (HITL)
人工介入 — 人类在关键节点进行审批、编辑或接管

## Instruction Hierarchy
指令层级 — 不同来源指令的优先级分层体系

## Chunking
切块 — 将长文本划分为可被索引和召回的最小语义单元

## Rerank
重排序 — 对首阶段召回结果用更细粒度模型重新排序

## Overlap
重叠窗口 — 切块时保留相邻块的边界部分，防止信息被切断

## Recall@k
前 k 召回率 — 前 k 个结果中命中相关文档的比例

## MRR (Mean Reciprocal Rank)
平均倒数排名 — 第一个正确答案位置的倒数均值

## nDCG (Normalized Discounted Cumulative Gain)
归一化折损累计增益 — 衡量排序质量的指标

## Hit Rate
命中率 — 前 k 个结果中是否至少包含一个相关文档

## Agentic RAG
智能体式 RAG — 检索策略随中间结果变化的多步检索

## GraphRAG
图谱式 RAG — 基于知识图谱支持多跳推理的检索方式

## Hybrid Search
混合检索 — 结合向量检索（dense）和关键词检索（sparse），兼顾语义相似度与精确匹配

## RRF (Reciprocal Rank Fusion)
倒数排名融合 — 将多个检索结果的排名分数合并为单一排序的算法，常用于混合检索中对 dense 和 sparse 结果做融合

## ACL (Access Control List)
访问控制列表 — 控制谁能访问什么资源的权限机制

## TTL (Time To Live)
存活时间 — 缓存或记忆的有效期限

## Guardrail
护栏 / 安全约束 — 防止智能体越界的安全机制

## Dry-run
试运行 — 在执行前模拟运行以检查效果

## Checkpoint
检查点 — 保存当前状态以便后续恢复

## Verifier
验证器 — 判断当前是否应该结束、重试或升级到人工的组件

## Orchestrator
编排层 — 接收模型建议、校验、路由到正确执行方式的组件

## Aggregator
聚合器 — 统一整合多个来源的结果

## Happy Path
理想路径 — 系统正常运行时的流程

## Decomposition
任务拆解 — 将开放目标拆成可执行的管理单元

## Replanning
重规划 — 在环境变化后重新制定计划

## Self-Attention
自注意力 — Transformer 中让每个位置关注上下文的机制

## FFN (Feed-Forward Network)
前馈网络 — Transformer 中负责非线性变换的模块

## LayerNorm
层归一化 — 稳定训练过程的归一化方法

## MoE (Mixture of Experts)
混合专家模型 — 只激活部分专家以降低推理成本的架构

## Tree of Thoughts (ToT)
思维树 — 探索多个候选推理路径并剪枝的技术

## Long-term Memory
长期记忆 — 跨会话的持久化经验

## Working Memory
工作记忆 — 当前推理需要的短期信息

## Episodic Memory
情节记忆 — 系统经历过的具体事件记录

## Semantic Memory
语义记忆 — 从多次经验中抽象出来的稳定知识

## Procedural Memory
程序性记忆 — "怎么做"的经验和技能

## Skills
技能包 — 一组动作 + 指令 + 资源 + 经验的封装方法包
