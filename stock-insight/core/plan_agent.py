import ast
import re
from typing import List, Dict
from .llm_client import LLMClient
from .tools import ToolExecutor, get_realtime_quote, get_historical_data, get_financial_data, calc_indicators, get_news
from .memory import StockMemory
from .rag import InvestmentKnowledgeBase

PLAN_SYSTEM_PROMPT = """你是一个专业的投资分析规划师。你的任务是将用户的股票分析问题分解为有序的执行步骤。

## 可用工具
{available_tools}

输出一个Python列表，每个元素是一个步骤描述字符串：
```python
["步骤1: 查询实时行情", "步骤2: 查看历史K线", "步骤3: 计算技术指标", "步骤4: 获取最新新闻", "步骤5: 搜索投资知识库", "步骤6: 综合分析并给结论"]
```

请注意：
1. 步骤要具体，包含要查询的股票代码或名称
2. 先数据采集，后分析判断
3. 只输出列表，不要其他内容"""

EXECUTE_SYSTEM_PROMPT = """你是一个投资分析执行器。根据给定的步骤，使用工具完成分析。

## 当前要执行的步骤
{current_step}

## 整体计划
{full_plan}

## 可用工具
{available_tools}

## 历史结果
{history}

## 格式
如果该步骤需要调用工具：
Action: <工具名>[<参数>]
工具结果会返回给你，然后继续下一步。

如果该步骤已完成或不需要工具：
Thought: <说明已完成>
Action: Done[<该步骤的结果摘要>]

当所有步骤都完成后：
Action: Finish[<完整的投资分析报告，Markdown格式>]

现在执行当前步骤。"""


class Planner:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def plan(self, question: str, tool_descriptions: str) -> List[str]:
        prompt = PLAN_SYSTEM_PROMPT.format(available_tools=tool_descriptions)
        messages = [{"role": "user", "content": f"{prompt}\n\n用户问题: {question}"}]
        response = self.llm.think(messages=messages, temperature=0.0)
        if not response:
            return self._default_plan()

        match = re.search(r"```(?:python)?\s*(.*?)\s*```", response, re.DOTALL)
        code = match.group(1) if match else response
        try:
            return ast.literal_eval(code)
        except (ValueError, SyntaxError):
            return self._default_plan()

    def _default_plan(self) -> List[str]:
        return [
            "查询实时行情，了解最新价格和涨跌幅",
            "查看近60个交易日K线数据，分析趋势",
            "计算技术指标(MA/MACD/RSI/布林带)",
            "获取最新相关新闻",
            "搜索投资知识库获取估值参考",
            "综合分析并给出投资建议",
        ]


class Executor:
    def __init__(self, llm: LLMClient, executor: ToolExecutor):
        self.llm = llm
        self.executor = executor

    def execute(self, question: str, plan: List[str]) -> str:
        history = ""
        tool_descriptions = self.executor.get_descriptions()

        for step in plan:
            prompt = EXECUTE_SYSTEM_PROMPT.format(
                current_step=step,
                full_plan="\n".join(f"- {s}" for s in plan),
                available_tools=tool_descriptions,
                history=history,
            )

            for _ in range(3):
                response = self.llm.think([{"role": "user", "content": prompt}])
                if not response:
                    break

                thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", response, re.DOTALL)
                action_match = re.search(r"Action:\s*(.*?)$", response, re.MULTILINE)
                thought = thought_match.group(1).strip() if thought_match else ""
                action = action_match.group(1).strip() if action_match else ""

                if action.lower().startswith("done"):
                    result = action[action.find("[")+1:action.rfind("]")] if "[" in action else action[5:]
                    history += f"\n[{step}] {result}"
                    break

                if action.lower().startswith("finish"):
                    result = action[action.find("[")+1:action.rfind("]")] if "[" in action else action[7:]
                    history += f"\n[最终报告]\n{result}"
                    return result

                tool_match = re.match(r"(\w+)\[(.*)\]", action, re.DOTALL)
                if tool_match:
                    tool_name, query = tool_match.group(1), tool_match.group(2).strip()
                    observation = self.executor.run(tool_name, query)
                    history += f"\n[{step}] {action}\n结果: {observation}"
                    prompt += f"\n\n工具结果:\n{observation}"
                else:
                    history += f"\n[{step}] 无法解析动作: {action}"
                    break

        final_prompt = f"""基于以下分析结果，给出最终投资分析报告。

## 原始问题
{question}

## 分析过程
{history}

请输出Markdown格式的完整分析报告，包含：行情概况、技术面分析、基本面分析、新闻舆情、风险提示、综合建议。"""
        final_response = self.llm.think([{"role": "user", "content": final_prompt}], temperature=0.3)
        return final_response or "分析完成，但LLM未能生成最终报告"


class PlanSolveAgent:
    def __init__(self, llm: LLMClient, memory: StockMemory = None, knowledge: InvestmentKnowledgeBase = None):
        self.llm = llm
        self.memory = memory or StockMemory()
        self.knowledge = knowledge or InvestmentKnowledgeBase()
        self.planner = Planner(llm)
        self._setup_executor()

    def _setup_executor(self):
        executor = ToolExecutor()
        executor.register("GetRealtimeQuote", "获取股票实时行情", get_realtime_quote)
        executor.register("GetHistoricalData", "获取历史K线。格式: 代码|daily|天数", get_historical_data)
        executor.register("GetFinancialData", "获取财务数据", get_financial_data)
        executor.register("CalcIndicators", "计算技术指标。格式: 代码|daily|天数", calc_indicators)
        executor.register("GetNews", "获取最新新闻", get_news)
        executor.register("SearchKnowledge", "搜索投资知识库", self.knowledge.search)
        self.executor = Executor(self.llm, executor)

    def run(self, question: str) -> str:
        tool_descriptions = """GetRealtimeQuote: 获取股票实时行情。
GetHistoricalData: 获取历史K线。格式: 代码|daily|天数。
GetFinancialData: 获取财务数据。
CalcIndicators: 计算技术指标。格式: 代码|daily|天数。
GetNews: 获取最新新闻。
SearchKnowledge: 搜索投资知识库。"""
        plan = self.planner.plan(question, tool_descriptions)
        result = self.executor.execute(question, plan)
        return result
