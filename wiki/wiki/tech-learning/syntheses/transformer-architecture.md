---
title: "Transformer 架构要点"
date_created: 2026-06-12
date_modified: 2026-06-12
summary: "综合整理 Attention Is All You Need 论文中的核心概念。"
tags: [tech-learning, nlp, transformer]
type: synthesis
status: draft
---

# Transformer 架构要点

基于 [[vaswani-2017-attention-is-all-you-need]] 整理。

## 核心创新

Transformer 完全基于注意力机制，抛弃了 RNN/CNN，核心设计包括：

- **Scaled Dot-Product Attention**：Attention(Q,K,V) = softmax(QK^T / √d_k)V，缩放因子 √d_k 防止梯度消失
- **Multi-Head Attention**：多个注意力头并行，捕捉不同子空间的表示
- **Positional Encoding**：正弦/余弦函数编码位置信息，弥补自注意力无顺序感知的缺陷
- **Encoder-Decoder 结构**：各 6 层，每层含自注意力 + 前馈网络

## 关键优势

| 对比项 | RNN | Transformer |
|--------|-----|-------------|
| 计算方式 | 串行 | 并行 |
| 长距离路径 | O(n) | O(1) |
| 训练速度 | 慢 | 快 |

## 后续影响

启发了 BERT（Encoder-only）、GPT（Decoder-only）、T5（Encoder-Decoder）等模型。
