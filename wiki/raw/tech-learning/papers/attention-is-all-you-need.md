Source: https://arxiv.org/abs/1706.03762

## Attention Is All You Need

### 摘要

本文提出了 Transformer 架构，完全基于注意力机制，摒弃了传统的循环神经网络（RNN）和卷积神经网络（CNN）。Transformer 的核心是 scaled dot-product attention 和 multi-head attention，通过并行计算和位置编码实现高效的序列建模。在机器翻译任务上，Transformer 达到了当时的 SOTA 结果，训练速度远超基于 RNN 的模型。

### 核心贡献

1. 提出了纯注意力机制的序列到序列架构
2. Multi-head attention 允许模型在不同表示子空间关注不同位置的信息
3. Positional encoding 让模型感知序列中 token 的相对位置
4. 训练速度显著优于 RNN/LSTM，且效果更好

### 架构要点

- **Encoder**: 6 层，每层包含 multi-head self-attention + feed-forward
- **Decoder**: 6 层，每层包含 masked multi-head attention + cross-attention + feed-forward
- **Scaled dot-product attention**: QK^T / sqrt(d_k)，避免 softmax 梯度消失
- **Positional encoding**: 正弦/余弦函数，无需学习

### 影响

Transformer 已成为 NLP 领域的基础架构，后续的 BERT、GPT、T5 等模型都基于此架构。近年来也扩展到视觉（ViT）、语音等领域。
