from .llm_client import LLMClient
from .agent import ReActAgent
from .plan_agent import PlanSolveAgent
from .reflection_agent import ReflectionAgent
from .memory import StockMemory
from .rag import InvestmentKnowledgeBase
from .context_manager import ContextManager

STOCK_SYSTEM_PROMPT = """你是一个专业A股投资分析助手，基于多维度数据进行分析。

## 分析维度
- 技术面: 行情、K线、MA/MACD/RSI/布林带、支撑压力位
- 基本面: 营收、净利润、ROE、毛利率、资产负债率、每股收益
- 消息面: 近期新闻、行业动态
- 估值: PE/PB/PEG 估值区间判断
- 知识库: 投资方法论、仓位管理、止损原则、A股规则

## 风险提示
所有分析仅供参考，不构成投资建议。入市有风险，投资需谨慎。"""


class FrameworkStockAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.memory = StockMemory()
        self.knowledge = InvestmentKnowledgeBase()
        self.context = ContextManager()

    def react(self, question: str) -> str:
        agent = ReActAgent(
            llm_client=self.llm,
            memory=self.memory,
            knowledge=self.knowledge,
            context=self.context,
            max_steps=6,
        )
        return agent.run(question)

    def plan_solve(self, question: str) -> str:
        agent = PlanSolveAgent(
            llm=self.llm,
            memory=self.memory,
            knowledge=self.knowledge,
        )
        return agent.run(question)

    def reflect(self, question: str) -> str:
        agent = ReflectionAgent(
            llm=self.llm,
            max_iterations=2,
        )
        return agent.run(question)
