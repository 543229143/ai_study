import re
from typing import List, Dict
from .llm_client import LLMClient
from .tools import ToolExecutor, get_realtime_quote, get_historical_data, get_financial_data, calc_indicators, get_news
from .memory import StockMemory
from .rag import InvestmentKnowledgeBase
from .context_manager import ContextManager

STOCK_SYSTEM_PROMPT = """你是一个专业的A股投资分析助理。你可以使用以下工具：

{available_tools}

## 交互格式
分析时使用以下格式：
Thought: <你的分析和推理>
Action: <工具名>[<参数>]

分析完成后输出：
Thought: <最终结论>
Action: Finish[<完整的分析报告，使用Markdown格式>]

## 注意事项
- 技术指标均基于历史数据计算，不构成投资建议
- 分析时要同时考虑技术面、基本面和消息面
- 如果工具返回错误或空数据，诚实告知用户"""


class ReActAgent:
    def __init__(self, llm_client: LLMClient, memory: StockMemory = None, knowledge: InvestmentKnowledgeBase = None, context: ContextManager = None, max_steps: int = 6):
        self.llm = llm_client
        self.memory = memory or StockMemory()
        self.knowledge = knowledge or InvestmentKnowledgeBase()
        self.ctx = context or ContextManager()
        self.max_steps = max_steps
        self.history: List[str] = []
        self._setup_tools()

    def _setup_tools(self):
        self.executor = ToolExecutor()
        self.executor.register("GetRealtimeQuote", "获取股票实时行情数据。输入股票代码或名称。", get_realtime_quote)
        self.executor.register("GetHistoricalData", "获取历史K线数据。格式: 代码|daily|天数", get_historical_data)
        self.executor.register("GetFinancialData", "获取财务报表数据。输入股票代码。", get_financial_data)
        self.executor.register("CalcIndicators", "计算技术指标(MA/MACD/RSI/布林带/支撑压力)。格式: 代码|daily|天数", calc_indicators)
        self.executor.register("GetNews", "获取最新相关新闻。输入股票代码。", get_news)
        self.executor.register("SearchKnowledge", "搜索投资知识库。输入查询关键词。", self.knowledge.search)
        self.executor.register("GetWatchlist", "获取关注列表。", lambda _: self.memory.get_watchlist())
        self.executor.register("SaveAnalysis", "保存分析结果。格式: 代码|问题|摘要。", self.memory.save_analysis)

    def run(self, question: str) -> str:
        system_msg = STOCK_SYSTEM_PROMPT.format(available_tools=self.executor.get_descriptions())
        self.history = []

        for step in range(1, self.max_steps + 1):
            history_text = "\n".join(self.history) or "(无历史)"
            prompt = f"{system_msg}\n\n## 当前任务\n{question}\n\n## 历史\n{history_text}\n\n现在请输出 Thought 和 Action:"
            messages = [{"role": "user", "content": prompt}]

            response = self.llm.think(messages=messages, temperature=0.1)
            if not response:
                return "LLM 无响应，分析中断"

            thought, action = self._parse(response)

            if action.lower().startswith("finish"):
                result = self._extract_bracket(action)
                self.ctx.add_turn("user", question)
                self.ctx.add_turn("assistant", result[:300])
                return result

            tool_name, query = self._parse_tool(action)
            if not tool_name:
                self.history.append(f"无法解析: {action}")
                continue

            observation = self.executor.run(tool_name, query)
            self.history.append(f"Thought: {thought}")
            self.history.append(f"Action: {action}")
            self.history.append(f"Observation: {observation}")

        return "已达到最大推理步数，分析未完成。请尝试简化问题或增加 max_steps。"

    def _parse(self, text: str):
        thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", text, re.DOTALL)
        action_match = re.search(r"Action:\s*(.*?)$", text, re.MULTILINE)
        thought = thought_match.group(1).strip() if thought_match else ""
        action = action_match.group(1).strip() if action_match else ""
        return thought, action

    def _parse_tool(self, action: str):
        match = re.match(r"(\w+)\[(.*)\]", action, re.DOTALL)
        if match:
            return match.group(1), match.group(2).strip()
        return None, None

    def _extract_bracket(self, action: str):
        match = re.search(r"\[(.*)\]", action, re.DOTALL)
        return match.group(1).strip() if match else action[len("Finish["):].strip()
