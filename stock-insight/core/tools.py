import akshare as ak
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional


class ToolExecutor:
    def __init__(self):
        self._tools: Dict[str, Dict] = {}

    def register(self, name: str, description: str, func):
        self._tools[name] = {"description": description, "func": func}

    def run(self, name: str, query: str) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"Tool '{name}' not found. Available: {list(self._tools.keys())}"
        try:
            return str(tool["func"](query))
        except Exception as e:
            return f"Tool '{name}' execution failed: {e}"

    def get_descriptions(self) -> str:
        return "\n".join(f"- {name}: {info['description']}" for name, info in self._tools.items())


def resolve_symbol(query: str) -> Optional[str]:
    code_map = {"贵州茅台": "600519", "宁德时代": "300750", "比亚迪": "002594",
                "中国平安": "601318", "招商银行": "600036", "五粮液": "000858",
                "格力电器": "000651", "美的集团": "000333", "恒瑞医药": "600276",
                "隆基绿能": "601012", "立讯精密": "002475"}
    for name, code in code_map.items():
        if name in query:
            return code
    nums = "".join(c for c in query if c.isdigit())
    return nums if len(nums) >= 6 else None


def get_realtime_quote(query: str) -> str:
    symbol = resolve_symbol(query)
    if not symbol:
        return f"Cannot resolve symbol from: {query}"
    df = ak.stock_zh_a_spot_em()
    row = df[df["代码"] == symbol]
    if row.empty:
        return f"No data for {symbol}"
    row = row.iloc[0]
    change = float(row["涨跌幅"]) if row["涨跌幅"] != "-" else 0
    return (
        f"名称: {row['名称']} | 代码: {symbol}\n"
        f"最新价: {row['最新价']} | 涨跌幅: {change:.2f}%\n"
        f"成交量: {row['成交量']}手 | 成交额: {row['成交额']}元\n"
        f"市盈率: {row['市盈率-动态']}" if row.get('市盈率-动态') and row['市盈率-动态'] != '-' else f"市盈率: N/A"
    )


def get_historical_data(query: str) -> str:
    parts = query.strip().split("|")
    symbol_str = parts[0].strip()
    period = parts[1].strip() if len(parts) > 1 else "daily"
    days_str = parts[2].strip() if len(parts) > 2 else "60"

    symbol = resolve_symbol(symbol_str)
    if not symbol:
        return f"Cannot resolve symbol from: {symbol_str}"
    days = int(days_str)
    period_map = {"daily": "日K", "weekly": "周K", "monthly": "月K"}
    period_key = period_map.get(period, "daily")
    df = ak.stock_zh_a_hist(symbol=symbol, period=period, start_date=(pd.Timestamp.now() - pd.Timedelta(days=days*2)).strftime("%Y%m%d"), end_date=pd.Timestamp.now().strftime("%Y%m%d"), adjust="qfq")
    if df.empty:
        return f"No historical data for {symbol}"
    df = df.tail(days)
    start_price = float(df.iloc[0]["收盘"])
    end_price = float(df.iloc[-1]["收盘"])
    change_pct = ((end_price - start_price) / start_price) * 100
    high = df["最高"].max()
    low = df["最低"].min()
    vol_avg = df["成交量"].mean()
    return (
        f"{symbol} {period_key} 近{days}个交易日:\n"
        f"区间涨跌: {change_pct:.2f}%\n"
        f"最高: {high} | 最低: {low}\n"
        f"起始价: {start_price} → 结束价: {end_price}\n"
        f"日均成交量: {vol_avg/10000:.1f}万手"
    )


def get_financial_data(symbol_str: str) -> str:
    symbol = resolve_symbol(symbol_str)
    if not symbol:
        return f"Cannot resolve symbol from: {symbol_str}"
    df = ak.stock_financial_abstract_ths(symbol=symbol, indicator="按报告期")
    if df.empty:
        return "财务数据不可用（财报尚未披露或数据源无此标的）"
    latest = df.iloc[0]
    items = ["营业总收入", "净利润", "净资产收益率", "毛利率", "资产负债率", "基本每股收益"]
    lines = [f"{item}: {latest.get(item, 'N/A')}" for item in items]
    return "\n".join(lines)


def calc_indicators(query: str) -> str:
    parts = query.strip().split("|")
    symbol_str = parts[0].strip()
    period = parts[1].strip() if len(parts) > 1 else "daily"
    days_str = parts[2].strip() if len(parts) > 2 else "120"

    symbol = resolve_symbol(symbol_str)
    if not symbol:
        return f"Cannot resolve symbol from: {symbol_str}"
    days = int(days_str)
    df = ak.stock_zh_a_hist(symbol=symbol, period=period, start_date=(pd.Timestamp.now() - pd.Timedelta(days=days*2)).strftime("%Y%m%d"), end_date=pd.Timestamp.now().strftime("%Y%m%d"), adjust="qfq").tail(days)
    if df.empty:
        return f"No data for {symbol}"

    close = df["收盘"].astype(float).values
    high_vals = df["最高"].astype(float).values
    low_vals = df["最低"].astype(float).values
    vol = df["成交量"].astype(float).values

    ma5 = np.mean(close[-5:])
    ma10 = np.mean(close[-10:])
    ma20 = np.mean(close[-20:])
    ma60 = np.mean(close[-60:]) if len(close) >= 60 else np.mean(close)

    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values[-1]
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values[-1]
    dif = ema12 - ema26
    dea = pd.Series([dif]).ewm(span=9, adjust=False).mean().values[-1]
    macd_bar = 2 * (dif - dea)
    macd_signal = "金叉" if dif > dea else "死叉"

    rsi_period = 14
    if len(close) >= rsi_period:
        delta = np.diff(close[-rsi_period-1:])
        gain = np.sum(delta[delta > 0])
        loss = -np.sum(delta[delta < 0])
        rs = gain / loss if loss != 0 else float('inf')
        rsi = 100 - (100 / (1 + rs))
    else:
        rsi = 50

    bb_mid = ma20
    bb_std = np.std(close[-20:])
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    support = float(np.min(low_vals[-60:])) if len(low_vals) >= 60 else float(np.min(low_vals))
    resistance = float(np.max(high_vals[-60:])) if len(high_vals) >= 60 else float(np.max(high_vals))

    latest_close = float(close[-1])
    price_position = ((latest_close - bb_lower) / (bb_upper - bb_lower)) * 100 if bb_upper != bb_lower else 50

    return (
        f"=== {symbol} 技术指标 ===\n"
        f"最新价: {latest_close:.2f}\n"
        f"MA5: {ma5:.2f} | MA10: {ma10:.2f} | MA20: {ma20:.2f} | MA60: {ma60:.2f}\n"
        f"MACD: DIF={dif:.2f} DEA={dea:.2f} BAR={macd_bar:.2f} → {macd_signal}\n"
        f"RSI(14): {rsi:.1f} (>{70}超买, <{30}超卖)\n"
        f"布林带: 上轨={bb_upper:.2f} 中轨={bb_mid:.2f} 下轨={bb_lower:.2f} (位置{price_position:.0f}%)\n"
        f"支撑位: {support:.2f} | 压力位: {resistance:.2f}"
    )


def get_news(symbol_str: str) -> str:
    symbol = resolve_symbol(symbol_str)
    if not symbol:
        return f"Cannot resolve symbol from: {symbol_str}"
    df = ak.stock_news_em(symbol=symbol)
    if df.empty:
        return "暂无相关新闻"
    latest = df.head(5)
    lines = []
    for _, row in latest.iterrows():
        title = str(row.get("标题", row.get("title", "")))[:60]
        lines.append(f"- {title}")
    return "最新5条新闻:\n" + "\n".join(lines)
