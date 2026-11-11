"""把 core/tools.py 里的真实工具接成带 JSON Schema 的注册表。

这里才 import akshare（惰性），所以 tool_registry / tool_agent 的单测
不需要装行情依赖。
"""

from __future__ import annotations

from typing import Optional

from .tool_registry import ToolRegistry, integer_param, object_schema, string_param


def build_registry(memory=None, knowledge=None) -> ToolRegistry:
    from . import tools as t
    from .memory import StockMemory
    from .rag import InvestmentKnowledgeBase

    memory = memory or StockMemory()
    knowledge = knowledge or InvestmentKnowledgeBase()

    registry = ToolRegistry()

    registry.register(
        "GetRealtimeQuote",
        "获取股票实时行情：最新价、涨跌幅、成交量、市盈率。",
        object_schema(
            {"symbol": string_param("股票代码（6 位）或中文名称，例如 600519 / 贵州茅台")},
            ["symbol"],
        ),
        lambda a: t.get_realtime_quote(a["symbol"]),
    )

    registry.register(
        "GetHistoricalData",
        "获取历史 K 线区间统计：区间涨跌、最高最低、日均成交量。",
        object_schema(
            {
                "symbol": string_param("股票代码或中文名称"),
                "period": string_param("K 线周期", enum=["daily", "weekly", "monthly"]),
                "days": integer_param("回看的交易日数量", default=60, minimum=5),
            },
            ["symbol"],
        ),
        lambda a: t.get_historical_data(
            f"{a['symbol']}|{a.get('period', 'daily')}|{a.get('days', 60)}"
        ),
    )

    registry.register(
        "GetFinancialData",
        "获取财务报表摘要：营收、净利润、ROE、毛利率、资产负债率、EPS。",
        object_schema({"symbol": string_param("股票代码或中文名称")}, ["symbol"]),
        lambda a: t.get_financial_data(a["symbol"]),
    )

    registry.register(
        "CalcIndicators",
        "计算技术指标：MA/MACD/RSI/布林带/支撑压力位。",
        object_schema(
            {
                "symbol": string_param("股票代码或中文名称"),
                "period": string_param("K 线周期", enum=["daily", "weekly", "monthly"]),
                "days": integer_param("回看的交易日数量", default=120, minimum=20),
            },
            ["symbol"],
        ),
        lambda a: t.calc_indicators(
            f"{a['symbol']}|{a.get('period', 'daily')}|{a.get('days', 120)}"
        ),
    )

    registry.register(
        "GetNews",
        "获取该股票最近 5 条新闻标题。",
        object_schema({"symbol": string_param("股票代码或中文名称")}, ["symbol"]),
        lambda a: t.get_news(a["symbol"]),
    )

    registry.register(
        "SearchKnowledge",
        "搜索投资知识库（方法论、仓位管理、止损原则、A 股规则）。",
        object_schema({"query": string_param("检索关键词")}, ["query"]),
        lambda a: knowledge.search(a["query"]),
    )

    registry.register(
        "GetWatchlist",
        "获取用户关注列表。",
        object_schema({}, []),
        lambda _a: memory.get_watchlist(),
    )

    registry.register(
        "AddWatchlist",
        "把一只股票加入关注列表。",
        object_schema(
            {"symbol": string_param("股票代码"), "name": string_param("股票名称")},
            ["symbol", "name"],
        ),
        lambda a: memory.add_watchlist(f"{a['symbol']}|{a['name']}"),
    )

    registry.register(
        "SaveAnalysis",
        "保存本次分析结论，供以后回顾。",
        object_schema(
            {
                "symbol": string_param("股票代码"),
                "question": string_param("用户的问题"),
                "summary": string_param("结论摘要，200 字以内"),
            },
            ["symbol", "question", "summary"],
        ),
        lambda a: memory.save_analysis(f"{a['symbol']}|{a['question']}|{a['summary']}"),
    )

    registry.register(
        "GetHistory",
        "查询某只股票的历史分析记录。",
        object_schema({"symbol": string_param("股票代码")}, ["symbol"]),
        lambda a: memory.get_history(a["symbol"]),
    )

    return registry


def build_agent(llm=None, max_steps: int = 6, tracer=None, registry: Optional[ToolRegistry] = None):
    from .llm_client import LLMClient
    from .tool_agent import ToolCallingAgent

    return ToolCallingAgent(
        llm=llm or LLMClient(),
        registry=registry or build_registry(),
        max_steps=max_steps,
        tracer=tracer,
    )
