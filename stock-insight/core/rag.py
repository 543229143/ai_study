import re
import math
from collections import Counter
from typing import List, Dict, Tuple


class InvestmentKnowledgeBase:
    def __init__(self):
        self._documents: List[Dict] = []
        self._chunks: List[str] = []
        self._initialize_knowledge()

    def _initialize_knowledge(self):
        self.add_text("""## 估值方法
PE（市盈率）: 股价/每股收益。PE<15 低估，15-25 合理，25-35 高估，>35 泡沫。
PB（市净率）: 股价/每股净资产。PB<1 破净，1-3 合理，>5 高估。银行/保险等重资产行业看PB为主。
PEG: PE/盈利增长率。PEG<1 被低估，1-2 合理，>2 高估。适合成长股估值。

## 技术指标解读
MACD金叉: DIF上穿DEA，看涨信号；MACD死叉: DIF下穿DEA，看跌信号。
RSI>70: 超买区域，短期可能回调；RSI<30: 超卖区域，短期可能反弹。
布林带: 价格触及上轨可能超买，触及下轨可能超卖；带宽收窄预示变盘。
均线多头排列: MA5>MA10>MA20>MA60，上升趋势；均线空头排列则相反。

## 仓位管理
单只股票仓位不超过总资产的20%。
行业仓位不超过总资产的40%。
永远保留至少10%的现金仓位。
亏损10%止损，盈利20%可考虑分批止盈。
不要在亏损时加仓（拒绝摊平心态）。

## 止损原则
固定止损: 买入价下跌10%无条件卖出。
移动止损: 股价上涨后，止损线上移至成本价或关键支撑位。
时间止损: 买入后20个交易日内未达预期收益，重新评估。
事件止损: 公司出现重大负面消息（财务造假、高管被查等），立即卖出。

## A股交易规则
交易时间: 周一至周五 9:30-11:30, 13:00-15:00。
T+1交易: 当日买入次日才能卖出。
涨跌幅限制: 主板±10%，科创板/创业板±20%，ST股票±5%。
交易费用: 佣金约万2.5，印花税卖出千1（单边征收）。

## 风险提示
投资有风险，入市需谨慎。以上内容为通用方法论，不构成投资建议。实际决策需结合个人风险承受能力、市场环境、个股基本面综合判断。""")

    def add_text(self, text: str):
        self._documents.append({"content": text, "chunks": self._chunk_text(text)})

    def _chunk_text(self, text: str, max_length: int = 300) -> List[str]:
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            if len(current) + len(p) < max_length:
                current += p + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = p + "\n\n"
        if current:
            chunks.append(current.strip())
        return chunks

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        text = re.sub(r'[^\u4e00-\u9fff\w\s]', ' ', text)
        chinese_tokens = re.findall(r'[\u4e00-\u9fff]{1,2}', text)
        words = text.split()
        return chinese_tokens + [w for w in words if len(w) > 1]

    def search(self, query: str, top_k: int = 5) -> str:
        all_chunks = []
        for doc in self._documents:
            for chunk in doc["chunks"]:
                all_chunks.append(chunk)

        if not all_chunks:
            return "知识库为空"

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return "无法解析查询"

        doc_freq = Counter()
        for chunk in all_chunks:
            tok_set = set(self._tokenize(chunk))
            for t in tok_set:
                doc_freq[t] += 1

        N = len(all_chunks)
        scores = []
        for i, chunk in enumerate(all_chunks):
            chunk_tokens = self._tokenize(chunk)
            score = 0
            for qt in query_tokens:
                if qt in chunk_tokens:
                    tf = chunk_tokens.count(qt) / max(len(chunk_tokens), 1)
                    df = doc_freq.get(qt, 1)
                    idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                    score += tf * idf
            if score > 0:
                scores.append((i, score, chunk))

        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:top_k]

        if not top:
            return "未找到相关知识"

        lines = []
        for i, (idx, score, chunk) in enumerate(top, 1):
            lines.append(f"{i}. (相关度 {score:.2f})\n{chunk[:300]}")
        return "\n\n".join(lines)

    def stats(self) -> str:
        total_chunks = sum(len(d["chunks"]) for d in self._documents)
        return f"知识库: {len(self._documents)} 篇文档, {total_chunks} 个片段"

    def import_file(self, filepath: str) -> str:
        try:
            with open(filepath, "r") as f:
                self.add_text(f.read())
            return f"已导入: {filepath}"
        except Exception as e:
            return f"导入失败: {e}"
