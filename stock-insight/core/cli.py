#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.framework_agent import FrameworkStockAgent


def main():
    agent = FrameworkStockAgent()

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        print("Stock Insight Agent — A股智能分析助手")
        print("支持三种分析模式: react / plan / reflect")
        print("输入 'exit' 退出\n")
        question = input("Stock> ").strip()
        if not question or question.lower() == "exit":
            return

    mode = "react"
    if "--mode" in question:
        parts = question.split("--mode")
        question = parts[0].strip()
        mode = parts[1].strip().split()[0] if parts[1].strip() else "react"

    mode = mode.lower()
    if mode not in ("react", "plan", "reflect"):
        print(f"Unknown mode: {mode}, using react")
        mode = "react"

    mode_labels = {"react": "ReAct", "plan": "PlanSolve", "reflect": "Reflection"}
    print(f"\n📊 分析模式: {mode_labels[mode]} | 问题: {question}\n")

    if mode == "react":
        result = agent.react(question)
    elif mode == "plan":
        result = agent.plan_solve(question)
    else:
        result = agent.reflect(question)

    print(result)


if __name__ == "__main__":
    main()
