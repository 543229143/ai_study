#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.framework_agent import FrameworkStockAgent

MODES = ("react", "plan", "reflect", "tool")
MODE_LABELS = {
    "react": "ReAct（文本解析版）",
    "plan": "PlanSolve",
    "reflect": "Reflection",
    "tool": "原生 function calling",
}


def parse_args(argv):
    mode = "react"
    trace = False
    words = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1].lower()
            i += 2
            continue
        if token == "--trace":
            trace = True
            i += 1
            continue
        words.append(token)
        i += 1
    return mode, trace, " ".join(words).strip()


def main():
    agent = FrameworkStockAgent()
    mode, trace, question = parse_args(sys.argv[1:])

    if not question:
        print("Stock Insight Agent — A股智能分析助手")
        print("支持模式: react / plan / reflect / tool（原生 function calling）")
        print("示例: python3 core/cli.py 分析贵州茅台 --mode tool --trace")
        print("输入 'exit' 退出\n")
        question = input("Stock> ").strip()
        if not question or question.lower() == "exit":
            return

    if mode not in MODES:
        print(f"Unknown mode: {mode}, using react")
        mode = "react"

    print(f"\n📊 分析模式: {MODE_LABELS[mode]} | 问题: {question}\n")

    tracer = None
    if trace:
        from core.tracing import TraceRecorder

        tracer = TraceRecorder()

    if mode == "react":
        result = agent.react(question)
    elif mode == "plan":
        result = agent.plan_solve(question)
    elif mode == "reflect":
        result = agent.reflect(question)
    else:
        result = agent.tool_calling(question, tracer=tracer)

    print(result)

    if tracer is not None:
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
        summary_path = tracer.save(os.path.join(out_dir, "trace.jsonl"))
        print(f"\n📈 Trace 汇总: {summary_path}")
        print(tracer.render_row())


if __name__ == "__main__":
    main()
