import re
from typing import Dict, List
from .llm_client import LLMClient
from .tools import get_realtime_quote, get_historical_data, get_financial_data, calc_indicators, get_news

REFLECTION_PROMPT = """你是一个严谨的投资分析审核专家。请审核以下分析报告，指出问题和改进建议。

## 分析报告
{report}

## 评审维度
1. 数据完整性: 是否覆盖了行情、技术面、基本面、消息面？
2. 风险覆盖: 是否指出了主要风险点？
3. 逻辑一致性: 结论是否与分析过程中的数据一致？
4. 盲区检查: 是否遗漏了重要的分析角度（如行业对比、资金流向）？
5. 反向思考: 是否存在与当前判断相反的证据？

如果报告已经足够完善，请回复"无需改进"。
否则请列出具体的改进建议：

## 改进建议
1. ...
2. ...
"""

REFINE_PROMPT = """根据评审意见，改进分析报告。

## 原始报告
{report}

## 评审意见
{reflection}

请输出改进后的完整分析报告（Markdown格式）。"""


class ReflectionAgent:
    def __init__(self, llm: LLMClient, max_iterations: int = 2):
        self.llm = llm
        self.max_iterations = max_iterations

    def run(self, task: str) -> str:
        data = self._collect_data(task)
        if not data:
            return "数据采集失败，无法进行分析"

        init_prompt = f"""你是一个专业股票分析师。根据以下数据，写出完整的投资分析报告（Markdown格式）。

## 用户问题
{task}

## 采集到的数据
{data}

请输出完整的分析报告，包含：
1. 行情概况
2. 技术面分析
3. 基本面分析
4. 新闻舆情
5. 风险提示
6. 综合建议与操作参考"""

        report = self.llm.think([{"role": "user", "content": init_prompt}], temperature=0.3)
        if not report:
            return "分析报告生成失败"

        for i in range(self.max_iterations):
            reflection_response = self.llm.think(
                [{"role": "user", "content": REFLECTION_PROMPT.format(report=report)}],
                temperature=0.1,
            )
            if not reflection_response or "无需改进" in reflection_response:
                break

            report = self.llm.think(
                [{"role": "user", "content": REFINE_PROMPT.format(report=report, reflection=reflection_response)}],
                temperature=0.3,
            )
            if not report:
                break

        return report

    def _collect_data(self, task: str) -> str:
        parts = []
        for symbol_keyword in ["600519", "300750", "002594", "601318", "000858",
                               "贵州茅台", "宁德时代", "比亚迪", "中国平安", "五粮液"]:
            if symbol_keyword in task:
                try:
                    parts.append(f"=== 实时行情 ===\n{get_realtime_quote(symbol_keyword)}")
                except Exception as e:
                    parts.append(f"实时行情获取失败: {e}")
                try:
                    parts.append(f"\n=== 历史K线 ===\n{get_historical_data(f'{symbol_keyword}|daily|60')}")
                except Exception as e:
                    parts.append(f"历史K线获取失败: {e}")
                try:
                    parts.append(f"\n=== 技术指标 ===\n{calc_indicators(f'{symbol_keyword}|daily|120')}")
                except Exception as e:
                    parts.append(f"技术指标计算失败: {e}")
                try:
                    parts.append(f"\n=== 财务数据 ===\n{get_financial_data(symbol_keyword)}")
                except Exception as e:
                    parts.append(f"财务数据获取失败: {e}")
                try:
                    parts.append(f"\n=== 新闻 ===\n{get_news(symbol_keyword)}")
                except Exception as e:
                    parts.append(f"新闻获取失败: {e}")
                break

        return "\n".join(parts) if parts else ""
