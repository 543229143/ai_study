#!/usr/bin/env python3
"""文本协议 vs 原生 tool_calls：解析鲁棒性对照（离线，不需要 API key）。

测量对象：core/react_parser.py（旧版 agent 的解析器）。
语料：48 条模型输出样本，覆盖 9 类在"自由文本协议"下真实出现过的偏移形态。

重要说明（面试时也要这么说）：
    这组语料是**构造**的，不是从线上随机采样，所以它衡量的是
    "某类输出一旦出现，解析端是否会失败"，**不是线上失败率**。
    真实失败率用 scripts/benchmark.py 跑真实模型得到。

运行：
    python3 scripts/parse_benchmark.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.react_parser import parse_thought_action, parse_tool_call  # noqa: E402

# (分类, 模型输出, 期望工具名, 期望参数)
CASES = [
    # --- 1. 规范单行 ---
    ("规范单行", "Thought: 先看行情\nAction: GetRealtimeQuote[600519]", "GetRealtimeQuote", "600519"),
    ("规范单行", "Thought: 需要K线\nAction: GetHistoricalData[600519|daily|60]", "GetHistoricalData", "600519|daily|60"),
    ("规范单行", "Thought: 查财务\nAction: GetFinancialData[600519]", "GetFinancialData", "600519"),
    ("规范单行", "Thought: 算指标\nAction: CalcIndicators[600519|daily|120]", "CalcIndicators", "600519|daily|120"),
    ("规范单行", "Thought: 看新闻\nAction: GetNews[600519]", "GetNews", "600519"),
    ("规范单行", "Thought: 查知识\nAction: SearchKnowledge[止损原则]", "SearchKnowledge", "止损原则"),
    ("规范单行", "Thought: 看关注\nAction: GetWatchlist[]", "GetWatchlist", ""),
    ("规范单行", "Thought: 存一下\nAction: SaveAnalysis[600519|分析茅台|偏多]", "SaveAnalysis", "600519|分析茅台|偏多"),
    ("规范单行", "Thought: 结论\nAction: Finish[建议观望]", "Finish", "建议观望"),
    ("规范单行", "Thought: 行情\nAction: get_realtime_quote[600519]", "get_realtime_quote", "600519"),
    ("规范单行", "Thought: 历史\nAction: GetHistoricalData[贵州茅台|weekly|30]", "GetHistoricalData", "贵州茅台|weekly|30"),
    ("规范单行", "Thought: 新闻\nAction: GetNews[宁德时代]", "GetNews", "宁德时代"),

    # --- 2. 参数含换行（正则 DOTALL 能扛住） ---
    ("参数多行", "Thought: 保存\nAction: SaveAnalysis[600519|分析茅台\n第二段结论]", "SaveAnalysis", "600519|分析茅台\n第二段结论"),
    ("参数多行", "Thought: 保存\nAction: SaveAnalysis[600519|问题描述\n补充说明|摘要]", "SaveAnalysis", "600519|问题描述\n补充说明|摘要"),
    ("参数多行", "Thought: 检索\nAction: SearchKnowledge[仓位管理\n止损原则]", "SearchKnowledge", "仓位管理\n止损原则"),
    ("参数多行", "Thought: 结论\nAction: Finish[结论第一行\n结论第二行]", "Finish", "结论第一行\n结论第二行"),
    ("参数多行", "Thought: 行情\nAction: GetRealtimeQuote[600519\n]", "GetRealtimeQuote", "600519"),
    ("参数多行", "Thought: 新闻\nAction: GetNews[600519\n备注：看最近三天]", "GetNews", "600519\n备注：看最近三天"),

    # --- 3. 参数里带方括号 ---
    ("参数含括号", "Thought: 查新闻\nAction: GetNews[600519][补充说明]", "GetNews", "600519][补充说明"),
    ("参数含括号", "Thought: 检索\nAction: SearchKnowledge[止损[硬止损]原则]", "SearchKnowledge", "止损[硬止损]原则"),
    ("参数含括号", "Thought: 保存\nAction: SaveAnalysis[600519|分析[重点]|摘要]", "SaveAnalysis", "600519|分析[重点]|摘要"),
    ("参数含括号", "Thought: 结论\nAction: Finish[建议[观望]]", "Finish", "建议[观望]"),

    # --- 4. 全角冒号（中文输入法常见） ---
    ("全角冒号", "Thought：先看行情\nAction：GetRealtimeQuote[600519]", "GetRealtimeQuote", "600519"),
    ("全角冒号", "Thought：查财务\nAction：GetFinancialData[600519]", "GetFinancialData", "600519"),
    ("全角冒号", "Thought：看新闻\nAction：GetNews[600519]", "GetNews", "600519"),
    ("全角冒号", "Thought：算指标\nAction：CalcIndicators[600519|daily|120]", "CalcIndicators", "600519|daily|120"),
    ("全角冒号", "Thought：结论\nAction：Finish[观望]", "Finish", "观望"),

    # --- 5. 圆括号调用 ---
    ("圆括号", "Thought: 行情\nAction: GetRealtimeQuote(600519)", "GetRealtimeQuote", "600519"),
    ("圆括号", "Thought: 财务\nAction: GetFinancialData(\"600519\")", "GetFinancialData", "600519"),
    ("圆括号", "Thought: 新闻\nAction: GetNews(600519)", "GetNews", "600519"),
    ("圆括号", "Thought: 指标\nAction: CalcIndicators(600519, daily, 120)", "CalcIndicators", "600519, daily, 120"),
    ("圆括号", "Thought: 结论\nAction: Finish(观望)", "Finish", "观望"),

    # --- 6. JSON 风格 ---
    ("JSON 风格", 'Thought: 行情\nAction: {"name": "GetRealtimeQuote", "arguments": {"symbol": "600519"}}', "GetRealtimeQuote", '{"symbol": "600519"}'),
    ("JSON 风格", 'Thought: 新闻\nAction: {"tool": "GetNews", "input": "600519"}', "GetNews", "600519"),
    ("JSON 风格", 'Thought: 结论\nAction: {"finish": "观望"}', "Finish", "观望"),
    ("JSON 风格", 'Thought: 指标\nAction: GetRealtimeQuote({"symbol": "600519"})', "GetRealtimeQuote", '{"symbol": "600519"}'),

    # --- 7. 工具名与括号之间有空格 ---
    ("空格分隔", "Thought: 行情\nAction: GetRealtimeQuote [600519]", "GetRealtimeQuote", "600519"),
    ("空格分隔", "Thought: 新闻\nAction: GetNews [600519]", "GetNews", "600519"),
    ("空格分隔", "Thought: 财务\nAction: GetFinancialData  [600519]", "GetFinancialData", "600519"),
    ("空格分隔", "Thought: 结论\nAction: Finish [观望]", "Finish", "观望"),

    # --- 8. 同一轮输出多个 Action ---
    ("多 Action", "Thought: 并行查\nAction: GetRealtimeQuote[600519]\nAction: GetNews[600519]", "GetRealtimeQuote", "600519"),
    ("多 Action", "Thought: 并行查\nAction: GetNews[600519]\nAction: GetFinancialData[600519]", "GetNews", "600519"),
    ("多 Action", "Thought: 三个一起\nAction: CalcIndicators[600519|daily|120]\nAction: GetNews[600519]\nAction: GetFinancialData[600519]", "CalcIndicators", "600519|daily|120"),
    ("多 Action", "Thought: 保存并结束\nAction: SaveAnalysis[600519|问|答]\nAction: Finish[完成]", "SaveAnalysis", "600519|问|答"),

    # --- 9. 纯自然语言，没有 Action 行 ---
    ("无 Action", "Thought: 我应该先查行情，然后看财务。", "", ""),
    ("无 Action", "我先调用 GetRealtimeQuote 获取 600519 的实时行情。", "", ""),
    ("无 Action", "Thought: 直接给结论：建议观望。", "", ""),
    ("无 Action", "根据已有数据，茅台当前估值偏高，建议观望。", "", ""),
]


def parse_legacy(text: str):
    """旧版解析链：正则抽 Action → 正则拆工具名。"""
    _thought, action = parse_thought_action(text)
    if not action:
        return None, None
    if action.lower().startswith("finish"):
        return "Finish", _finish_arg(action)
    return parse_tool_call(action)


def _finish_arg(action: str) -> str:
    import re

    match = re.search(r"\[(.*)\]", action, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Finish(观望) / Finish 观望
    match = re.search(r"\((.*)\)", action, re.DOTALL)
    return match.group(1).strip() if match else action[len("Finish"):].strip()


def main() -> int:
    rows = {}
    total = passed = 0

    for category, text, want_tool, want_arg in CASES:
        got_tool, got_arg = parse_legacy(text)
        # 解析器返回 None 等价于"没识别出调用"，不算解析错误；
        # 但如果模型这一轮给了多个 Action，解析器只能返回第一个，其余被静默丢弃 —— 算失败。
        multi_action = text.count("Action:") > 1 or text.count("Action：") > 1
        ok = (got_tool or "") == (want_tool or "") and (got_arg or "") == (want_arg or "")
        if multi_action:
            ok = False
        total += 1
        passed += ok
        bucket = rows.setdefault(category, [0, 0])
        bucket[0] += ok
        bucket[1] += 1

    print("## 文本协议解析鲁棒性（离线，构造语料）\n")
    print("| 输出形态 | 样本数 | 解析正确 | 正确率 |")
    print("|---|---|---|---|")
    for category, (ok, n) in rows.items():
        print(f"| {category} | {n} | {ok} | {ok / n * 100:.0f}% |")
    print(f"| **合计** | {total} | {passed} | {passed / total * 100:.0f}% |")
    print()
    print(f"结论：{total} 条样本中 {total - passed} 条解析结果与模型意图不符（{(total - passed) / total * 100:.0f}%）。")
    print("注意：语料是构造的，衡量的是“结构性脆弱”，不是线上失败率。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
