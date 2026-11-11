#!/usr/bin/env python3
"""端到端对照：文本协议 ReAct vs 原生 function calling（需要 API key）。

这个脚本**不编数字**：没有 key 直接退出，跑出来的数就是真实的。
建议跑法：

    export LLM_API_KEY=sk-xxx
    export LLM_BASE_URL=https://api.deepseek.com/v1
    export LLM_MODEL_ID=deepseek-chat
    python3 scripts/benchmark.py --runs 5

输出可以直接贴进 review/README.md 的 benchmark 表。
口径：单机、单轮、N 次取中位数，不代表生产。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

QUESTIONS = [
    "分析贵州茅台当前的技术面和基本面，给出明确结论",
    "600519 最近走势如何？支撑位和压力位在哪？",
    "帮我看看宁德时代现在的估值和消息面",
    "比亚迪现在适合买入吗？说说理由和风险",
    "对比一下招商银行和贵州茅台的技术指标",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5, help="每种模式跑几次（取中位数）")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()

    if not (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("未检测到 LLM_API_KEY / OPENAI_API_KEY，已退出（不生成假数据）。")
        print("用法见文件头注释。")
        return 2

    from core.llm_client import LLMClient
    from core.tracing import TraceRecorder

    results = []

    # ---- 模式 1：文本协议（旧版） ----
    legacy = _run_legacy(LLMClient(), args.runs, args.max_steps)
    results.append(legacy)

    # ---- 模式 2：原生 function calling ----
    native = _run_native(LLMClient(), args.runs, args.max_steps)
    results.append(native)

    print("\n## 端到端对照\n")
    print("| 模式 | 中位耗时 | 平均 token | 平均成本 | 工具成功率 | 解析失败 | 样本数 |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r['mode']} | {r['latency_s']:.1f}s | {r['tokens']} | {r['cost']} | "
            f"{r['tool_rate']} | {r['parse_fail']} | {r['n']} |"
        )
    print("\n口径：单机、单轮、中位数；成本按内置价格表估算，未知模型显示“未知”。")
    return 0


def _run_legacy(client, runs: int, max_steps: int) -> dict:
    from core.agent import ReActAgent

    latencies, tokens, costs, parse_fail = [], [], [], 0
    for i in range(runs):
        tracer = TraceRecorder(run_id=f"legacy-{i + 1}")
        client.tracer = tracer
        agent = ReActAgent(llm_client=client, max_steps=max_steps)
        q = QUESTIONS[i % len(QUESTIONS)]
        t0 = time.perf_counter()
        try:
            agent.run(q)
        except Exception as exc:  # noqa: BLE001
            print(f"  legacy run {i + 1} failed: {exc}")
        latencies.append((time.perf_counter() - t0) * 1000)
        s = tracer.summary()
        tokens.append(s["total_tokens"])
        if s["cost_usd"] is not None:
            costs.append(s["cost_usd"])
        parse_fail += sum(1 for h in agent.history if "无法解析" in h)

    return {
        "mode": "文本协议 ReAct",
        "latency_s": statistics.median(latencies) / 1000 if latencies else 0,
        "tokens": round(statistics.mean(tokens)) if tokens else 0,
        "cost": f"${statistics.mean(costs):.4f}" if costs else "未知",
        "tool_rate": "—",
        "parse_fail": parse_fail,
        "n": runs,
    }


def _run_native(client, runs: int, max_steps: int) -> dict:
    from core.stock_tools import build_agent

    latencies, tokens, costs, rates = [], [], [], []
    for i in range(runs):
        tracer = TraceRecorder(run_id=f"native-{i + 1}")
        agent = build_agent(llm=client, max_steps=max_steps, tracer=tracer)
        q = QUESTIONS[i % len(QUESTIONS)]
        t0 = time.perf_counter()
        try:
            agent.run(q)
        except Exception as exc:  # noqa: BLE001
            print(f"  native run {i + 1} failed: {exc}")
        latencies.append((time.perf_counter() - t0) * 1000)
        s = tracer.summary()
        tokens.append(s["total_tokens"])
        if s["cost_usd"] is not None:
            costs.append(s["cost_usd"])
        if s["tool_success_rate"] is not None:
            rates.append(s["tool_success_rate"])

    return {
        "mode": "原生 tool_calls",
        "latency_s": statistics.median(latencies) / 1000 if latencies else 0,
        "tokens": round(statistics.mean(tokens)) if tokens else 0,
        "cost": f"${statistics.mean(costs):.4f}" if costs else "未知",
        "tool_rate": f"{statistics.mean(rates) * 100:.0f}%" if rates else "—",
        "parse_fail": 0,
        "n": runs,
    }


if __name__ == "__main__":
    raise SystemExit(main())
