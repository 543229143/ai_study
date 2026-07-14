---
title: "Attention Is All You Need - 论文摘要"
date_created: 2026-06-12
date_modified: 2026-06-12
summary: "Google 团队提出 Transformer 架构，完全基于注意力机制，摒弃了 RNN/CNN，成为后续 BERT/GPT 等模型的基础。"
tags: [tech-learning, nlp, transformer, attention]
type: source
status: draft
source_url: https://arxiv.org/abs/1706.03762
---

# Attention Is All You Need

## 核心观点
Transformer 证明了**纯注意力机制**足以替代循环和卷积结构，且在并行计算和长距离依赖建模上更有优势。

## 关键概念
- [[scaled-dot-product-attention]]：Q·K^T / sqrt(d_k)，防止 softmax 进入梯度饱和区
- [[multi-head-attention]]：多个注意力头并行，捕捉不同子空间的表示
- [[positional-encoding]]：用正弦/余弦函数编码位置信息
- [[transformer-architecture]]：Encoder-Decoder 结构，各 6 层
- [[self-attention]]：序列内每个位置关注所有其他位置

## 后续影响
Transformer 启发了 [[BERT]]、[[GPT]]、[[T5]] 等模型，并扩展到视觉（[[ViT]]）、语音等领域。
