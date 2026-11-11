#!/usr/bin/env python3
"""四种写作模式的「成本 vs 质量」对照（需要 API key，不编数字）。

思路：不重写业务代码，只在 SDK 调用外面套一层，抓 usage。
质量指标直接取 orchestrator 自带的 stats（首稿通过、返修次数），
所以这张表衡量的是"同样的成品质量，花了多少钱"。

用法：
    export LLM_API_KEY=sk-xxx
    export LLM_MODEL_ID=deepseek-chat
    python3 scripts/cost_report.py --topic "AI 时代的后端工程师" --runs 1

    # 结果直接覆盖写入 COST_COMPARISON.md
    python3 scripts/cost_report.py --write COST_COMPARISON.md
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 单位：美元 / 百万 token；可用环境变量覆盖
PRICING = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "deepseek-chat": (0.27, 1.10),
}

MODES = {
    "react": ("ReAct + 评审返修", False),
    "reflect": ("Reflection 自省", True),
}


def instrument(llm_client_cls, counter):
    """把 SDK 调用包一层，记录 usage。原 think() 不返回 usage，只能在这里抓。"""

    def think(self, messages, temperature=0.1, stream=False):
        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=temperature
            )
        except Exception as exc:  # noqa: BLE001
            counter.append({"ok": False, "error": str(exc), "latency_ms": 0, "in": 0, "out": 0})
            return None
        usage = getattr(resp, "usage", None)
        counter.append(
            {
                "ok": True,
                "latency_ms": (time.perf_counter() - t0) * 1000,
                "in": getattr(usage, "prompt_tokens", 0) or 0,
                "out": getattr(usage, "completion_tokens", 0) or 0,
            }
        )
        return resp.choices[0].message.content

    llm_client_cls.think = think


def run_mode(mode: str, topic: str, runs: int) -> dict:
    from core.agents import get_llm
    from core.llm_client import LLMClient
    from core.orchestrator import ColumnWriterOrchestrator

    counter: list = []
    instrument(LLMClient, counter)

    label, use_reflection = MODES[mode]
    results = []
    for _ in range(runs):
        counter.clear()
        t0 = time.perf_counter()
        orch = ColumnWriterOrchestrator(use_reflection_mode=use_reflection)
        out = orch.create_column(topic)
        wall = time.perf_counter() - t0
        results.append(
            {
                "wall_s": wall,
                "in": sum(c["in"] for c in counter),
                "out": sum(c["out"] for c in counter),
                "calls": len(counter),
                "failures": sum(1 for c in counter if not c["ok"]),
                "stats": dict(orch.stats),
                "words": len(str(out.get("content", ""))),
            }
        )

    model = get_llm().model
    price_in, price_out = PRICING.get(model, (None, None))
    if os.getenv("LLM_PRICE_INPUT_PER_M") and os.getenv("LLM_PRICE_OUTPUT_PER_M"):
        price_in = float(os.getenv("LLM_PRICE_INPUT_PER_M"))
        price_out = float(os.getenv("LLM_PRICE_OUTPUT_PER_M"))

    avg_in = statistics.mean(r["in"] for r in results)
    avg_out = statistics.mean(r["out"] for r in results)
    cost = None if price_in is None else (avg_in * price_in + avg_out * price_out) / 1_000_000
    stats = results[0]["stats"]
    generations = max(stats.get("total_generations", 0), 1)

    return {
        "mode": label,
        "latency_s": statistics.median(r["wall_s"] for r in results),
        "tokens": round(avg_in + avg_out),
        "cost": "未知" if cost is None else f"${cost:.4f}",
        "calls": round(statistics.mean(r["calls"] for r in results)),
        "first_pass": f"{stats.get('approved_first_try', 0)}/{generations}",
        "revisions": stats.get("total_revisions", 0),
        "model": model,
    }


def render(rows: list) -> str:
    lines = [
        "| 模式 | 中位耗时 | token | 单篇成本 | LLM 调用次数 | 首稿通过 | 返修次数 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['mode']} | {r['latency_s']:.0f}s | {r['tokens']} | {r['cost']} | "
            f"{r['calls']} | {r['first_pass']} | {r['revisions']} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="AI 时代的后端工程师")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--modes", default="react,reflect")
    parser.add_argument("--write", default="")
    args = parser.parse_args()

    if not (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("未检测到 LLM_API_KEY / OPENAI_API_KEY，已退出（不生成假数据）。")
        return 2

    rows = []
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        if mode not in MODES:
            print(f"未知模式: {mode}（可选 {list(MODES)}）")
            return 1
        print(f"\n▶ 运行模式: {MODES[mode][0]}")
        rows.append(run_mode(mode, args.topic, args.runs))

    table = render(rows)
    print("\n## 成本 / 质量对照\n")
    print(table)
    print(f"\n模型: {rows[0]['model']} ｜ 主题: {args.topic} ｜ 每种模式 {args.runs} 次取中位数")

    if args.write:
        with open(args.write, "w", encoding="utf-8") as f:
            f.write("# 四种写作模式的成本 / 质量对照\n\n")
            f.write(f"主题：{args.topic}　模型：{rows[0]['model']}　每种模式 {args.runs} 次\n\n")
            f.write(table + "\n\n")
            f.write("> 口径：单机、单轮、中位数。成本按内置价格表估算，未知模型显示“未知”。\n")
        print(f"\n已写入 {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
