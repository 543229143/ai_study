#!/usr/bin/env python3
"""prompt 体积对照：文本协议 vs 原生 tool_calls（离线，用 tiktoken 真分词）。

回答两个问题：
1. 把工具描述从"自然语言清单"换成 JSON Schema，prompt 是变大了还是变小了？
2. 多轮工具调用时，旧版每轮重建整段 history，token 是怎么涨的？

运行（需要 tiktoken；没有就退化成字符估算并标注）：
    python3 scripts/prompt_size.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STEPS = 6
OBSERVATION_CHARS = 800  # 一次行情/财务工具返回的典型长度


def _encoder():
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(enc.encode(text)), "tiktoken(cl100k_base)"
    except ImportError:
        return lambda text: max(1, len(text) // 4), "字符数/4 估算"


def _old_prompt_parts():
    """旧版：系统提示 + 8 个工具的文字描述。"""
    from core.agent import STOCK_SYSTEM_PROMPT
    from core.tools import (
        ToolExecutor,
        calc_indicators,
        get_financial_data,
        get_historical_data,
        get_news,
        get_realtime_quote,
    )

    executor = ToolExecutor()
    executor.register("GetRealtimeQuote", "获取股票实时行情数据。输入股票代码或名称。", get_realtime_quote)
    executor.register("GetHistoricalData", "获取历史K线数据。格式: 代码|daily|天数", get_historical_data)
    executor.register("GetFinancialData", "获取财务报表数据。输入股票代码。", get_financial_data)
    executor.register("CalcIndicators", "计算技术指标(MA/MACD/RSI/布林带/支撑压力)。格式: 代码|daily|天数", calc_indicators)
    executor.register("GetNews", "获取最新相关新闻。输入股票代码。", get_news)
    executor.register("SearchKnowledge", "搜索投资知识库。输入查询关键词。", lambda q: "")
    executor.register("GetWatchlist", "获取关注列表。", lambda q: "")
    executor.register("SaveAnalysis", "保存分析结果。格式: 代码|问题|摘要。", lambda q: "")

    return STOCK_SYSTEM_PROMPT.format(available_tools=executor.get_descriptions())


def _new_prompt_parts():
    """新版：系统提示 + JSON Schema。"""
    from core.stock_tools import build_registry
    from core.tool_agent import DEFAULT_SYSTEM_PROMPT

    registry = build_registry()
    return DEFAULT_SYSTEM_PROMPT, json.dumps(registry.schema(), ensure_ascii=False)


def main() -> int:
    count, how = _encoder()
    old_prompt = _old_prompt_parts()
    new_system, new_schema = _new_prompt_parts()

    old_tokens = count(old_prompt)
    new_tokens = count(new_system) + count(new_schema)

    print("## 工具描述的 token 成本\n")
    print(f"分词方式：{how}\n")
    print("| 方案 | 内容 | token |")
    print("|---|---|---|")
    print(f"| 旧版文本协议 | 系统提示 + 8 个工具的文字描述 | {old_tokens} |")
    print(f"| 新版 tool_calls | 系统提示 + 10 个工具的 JSON Schema | {new_tokens} |")
    print(f"| 差额 | | {new_tokens - old_tokens:+d} |")

    # 多轮对话：旧版每轮把整段 history 拼进 prompt；新版只 append 消息
    print("\n## 多轮工具调用时的累计 prompt token\n")
    print(f"假设每轮工具返回 {OBSERVATION_CHARS} 字符，共 {STEPS} 轮。\n")
    print("| 轮次 | 旧版（每轮重建 history） | 新版（append 消息） |")
    print("|---|---|---|")

    old_cum = new_cum = 0
    observation = "观" * OBSERVATION_CHARS
    history = []
    messages_tokens = new_tokens

    for step in range(1, STEPS + 1):
        turn = f"Thought: 需要查数据\nAction: GetRealtimeQuote[600519]\nObservation: {observation}"
        history.append(turn)
        old_cum += count(old_prompt) + count("\n".join(history))
        messages_tokens += count(turn)
        new_cum += messages_tokens
        print(f"| {step} | {old_cum} | {new_cum} |")

    print(f"\n累计差 {new_cum - old_cum:+d} token（新版更贵）。")
    print()
    print("## 结论（注意，和直觉相反）")
    print()
    print(f"1. **Schema 有固定开销**：{new_tokens} vs {old_tokens} token，每次调用多 {new_tokens - old_tokens}。")
    print("   工具越多、参数越细，这个开销越大。")
    print("2. **两者累计都随轮次平方增长**，因为每次调用都要重发全部上下文。")
    print("   所以 function calling 并不会自动省 token。")
    print("3. **它买的不是成本，是可靠性**：解析正确率从 46% 提升到结构性 100%（见 parse_benchmark.py）。")
    print("4. **真正的 token 优势在可裁剪性**：新版是消息数组，可以按条丢旧工具结果、只留摘要；")
    print("   旧版是一整段字符串，只能整体截断，一截就丢上下文。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
