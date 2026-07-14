---
title: "Transformer 为什么能取代 RNN — 查询结果"
date_created: 2026-06-12
date_modified: 2026-06-12
summary: "综合 wiki 中 Transformer 相关内容，分析其核心优势。"
tags: [tech-learning, query, transformer]
type: output
status: draft
---

# Transformer 为什么能取代 RNN？

综合 [[../../syntheses/transformer-architecture|Transformer 架构要点]] 和 [[../../sources/vaswani-2017-attention-is-all-you-need|Attention Is All You Need 论文]] 的内容。

## 核心原因

1. **并行计算**：RNN 必须串行处理序列（逐个 token），Transformer 通过自注意力一步看到所有 token，训练速度大幅提升。

2. **长距离依赖**：RNN 中信息需要经过多个时间步传递，容易梯度消失。缩放点积注意力直接计算任意两个位置的关联，路径长度为 1。

3. **多子空间表示**：多头注意力让模型在不同子空间同时关注不同类型的模式（语法、语义、位置等）。

4. **位置感知**：位置编码用正余弦函数注入位置信息，弥补自注意力本身不具备序列顺序感知的缺陷。

## 后续发展

Transformer 衍生出三大主流变体：
- BERT（Encoder-only）：适合理解类任务
- GPT（Decoder-only）：适合生成类任务
- T5（Encoder-Decoder）：统一框架

## 来源
- [[../../syntheses/transformer-architecture|Transformer 架构要点]]
- [[../../sources/vaswani-2017-attention-is-all-you-need|Attention Is All You Need 论文摘要]]
