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

## Java 开发者视角：AI 概念类比

| 英文术语 | 中文释义 | Java 开发者视角类比 |
|----------|----------|---------------------|
| **Chain** | 链 | **Pipeline / Flow**（处理流水线） |
| **Runnable** | 可运行对象 | **Interface**（所有组件通用的基础接口） |
| **Prompt** | 提示词 | **Template String**（带有占位符的指令） |
| **Loader** | 加载器 | **InputStream / FileIO**（数据读入） |
| **Chunk** | 片段 | **Paging / Segment**（大对象的内存分段） |
| **Embedding** | 嵌入 / 向量化 | **Semantic Hash**（带语义信息的 Hash 值） |
| **Retriever** | 检索器 | **DAO / Repository**（专门负责查询的层） |
| **Vector Store** | 向量数据库 | **Elasticsearch / Redis**（支持相似度搜索的库） |
| **Output Parser** | 输出解析器 | **Deserializer / Mapper**（将 String 转为 Object） |
| **Retrieval** | 检索 | |
