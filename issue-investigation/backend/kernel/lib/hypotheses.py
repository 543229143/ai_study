"""从日志/代码/DB 信号生成候选排查假设（供报告 §5 预填，Agent 确认或排除）。"""
from __future__ import annotations

import re
from typing import Any


_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"未获取到客户申请信息|查无.*申请|申请信息不存在", re.I),
        "本地申请/授信记录缺失",
        "回调或业务处理时按 creditReqNo/appl_no 查不到申请，优先核对 LPS 申请表是否落库",
    ),
    (
        re.compile(r"interestRateMap|获取不到.*利率|机构产品利率|定价.*(缺失|失败|为空)", re.I),
        "机构费率/定价配置缺失",
        "可借/定价链路缺少机构产品费率，优先核对 AMS 定价表或 Nacos 费率配置",
    ),
    (
        re.compile(r"Duplicate entry|DuplicateKey|唯一约束", re.I),
        "唯一键冲突（重复落库）",
        "插入时主键/唯一索引冲突，核对是否重复回调或幂等键冲突",
    ),
    (
        re.compile(r"Connection refused|connect timed out|UnknownHostException", re.I),
        "下游网络/服务不可用",
        "连不上对端或超时，核对服务发现、地址与健康状态",
    ),
    (
        re.compile(r"SQLException|MyBatisSystemException|bad SQL grammar", re.I),
        "SQL/持久化层异常",
        "执行 SQL 失败，结合堆栈 Mapper 与库表结构核对",
    ),
    (
        re.compile(r"NullPointerException", re.I),
        "空指针（逻辑未判空）",
        "多为代码路径问题；先定位 NPE 行，再判断上游是否未返回必填对象",
    ),
    (
        re.compile(r'"flag"\s*:\s*"F"|处理回调结果失败', re.I),
        "回调链路失败回传",
        "对端收到失败应答；需区分我方业务校验失败 vs 对端/mock 噪声",
    ),
]


def generate_hypotheses(evidence: dict[str, Any] | None) -> list[dict[str, str]]:
    """返回 [{id, title, detail, source}]，最多 5 条。"""
    evidence = evidence or {}
    logs = evidence.get("logs") or {}
    db = evidence.get("database") or {}
    code = evidence.get("code") or {}
    messages: list[str] = []
    for block in (logs.get("by_app") or {}).values():
        for e in block.get("entries") or []:
            messages.append(e.get("message") or "")
    for e in logs.get("entries") or []:
        messages.append(e.get("message") or "")
    blob = "\n".join(messages)

    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(title: str, detail: str, source: str) -> None:
        if title in seen:
            return
        seen.add(title)
        out.append({
            "id": f"H{len(out)+1}",
            "title": title,
            "detail": detail,
            "source": source,
        })

    for pat, title, detail in _RULES:
        if pat.search(blob):
            _add(title, detail, "logs")

    # DB 空结果
    empty_q = 0
    for q in db.get("queries") or []:
        if q.get("executed") and not q.get("error") and int(q.get("count") or 0) == 0:
            empty_q += 1
    if empty_q:
        _add(
            "库表查询为空（数据缺口）",
            f"已执行查询中有 {empty_q} 条返回 0 行，与「缺数据」类日志一致时可作强佐证",
            "database",
        )

    # 代码命中 Handler/Facade
    for block in (code.get("code_hits") or [])[:4]:
        kw = (block.get("keyword") or "").strip()
        app = block.get("app") or "?"
        if kw and re.search(r"Handler|Facade|Callback", kw, re.I):
            _add(
                f"代码锚点：{app}.{kw}",
                "日志堆栈对应业务类已命中，建议结合方法分支与入参继续定位",
                "code",
            )

    return out[:5]


def format_hypotheses_markdown(hypotheses: list[dict[str, str]]) -> list[str]:
    if not hypotheses:
        return []
    lines = [
        "### 候选假设（系统预填，请确认/排除/补充）",
        "",
    ]
    for h in hypotheses:
        lines.append(
            f"- **{h.get('id')} {h.get('title')}** — {h.get('detail')} "
            f"（来源：{h.get('source')}）"
        )
    lines.append("")
    lines.append("Agent：在 5.1 采纳或改写根因；在 5.2 写下被排除的假设及依据。")
    return lines
