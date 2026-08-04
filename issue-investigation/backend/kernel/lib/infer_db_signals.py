"""从日志与排查上下文判断是否需要 SQL 辅助（按需触发，非固定流水线）。"""
from __future__ import annotations

import re
from typing import Any

# 日志中出现下列模式 → 可能需要查库核对数据/状态
_NEED_PATTERNS: list[tuple[str, str, int]] = [
    (r"未落库|未写入|无记录|查无|不存在|not\s*found|NoSuch\w+", "数据缺失/不存在", 3),
    (r"落库失败|保存.*失败|写入.*失败|insert\s+failed|update\s+failed|DuplicateKey|唯一约束|duplicate", "持久化失败", 4),
    (r"SQLException|MyBatis|Mapper\.|\.insert\(|\.update\(|\.select\(|jdbc", "持久化层异常/调用", 3),
    (r"状态.*(异常|不一致|不对)|status.*(invalid|mismatch)", "状态核对", 2),
    (r"0\s*行|count\s*=\s*0|empty\s+result|查询为空", "查询结果为空", 3),
    # 业务字段/配置缺失（日志已点名缺什么，通常应对数据源服务查库）
    (
        r"获取不到|字段缺失|指标异常|数据异常.*机构|"
        r"机构产品利率|interestRateMap|定价.*(失败|异常|缺失|为空)|"
        r"费率.*(缺失|为空|异常)|缺少.*(?:费率|利率|定价)|"
        r"可借列表存在机构获取不到",
        "字段/指标缺失",
        4,
    ),
    (r"排查:\s*\S+\.\S+\s*=", "用户表查", 5),
    (r"错误现象:", "用户期望核对", 5),
]

# 他方日志指向本服务数据缺口 → 对本服务触发 SQL（跨服务）
# (pattern_on_any_log, target_app, reason)
_CROSS_PEER_DATA_GAP: list[tuple[str, str, str]] = [
    (
        r"获取不到.*利率|interestRateMap|机构产品利率|定价信息|"
        r"queryAccountPrdTermFee|PrdTermFee|账户产品定价|批量查询定价",
        "ams",
        "对端日志指向 AMS 账户定价/费率数据缺口",
    ),
    (
        r"调用ams.*(失败|异常|为空)|AmsPilotAccount.*(失败|异常)|ams.*(定价|feeRate).*(失败|异常|缺失)",
        "ams",
        "对端调用 AMS 失败/异常，需核对 AMS 库表",
    ),
    (
        r"调用lcs.*(失败|异常|为空)|LcsDrawClient.*(失败|异常|为空)|"
        r"LcsLoan.*(失败|异常)|pilot_loan.*(无记录|不存在|查无)",
        "lcs",
        "对端调用 LCS 失败/异常，需核对 LCS 库表",
    ),
    (
        r"调用goa.*(失败|异常)|FundCallback.*(失败|异常)",
        "goa",
        "对端调用 GOA 失败/异常（goa 通常无落库 Mapper，仅记录信号）",
    ),
]

# 堆栈/类名：日志里出现本服务 Mapper/Dao 且伴随失败语义
_PERSISTENCE_CLASS = re.compile(
    r"\b(\w+(?:Mapper|Dao|Repository|ServiceImpl))\b",
    re.I,
)
_FAIL_NEAR = re.compile(
    r"失败|异常|error|exception|failed|rollback",
    re.I,
)

# 仅有下列情况且无明显持久化问题时，通常不必查库（辅助降权）
_CODE_ONLY_PATTERNS: list[str] = [
    r"日期转换异常",
    r"NullPointerException",
    r"NumberFormatException",
    r"timeout|timed\s*out|连接超时",
    r"mock|MockAspect",
]

_BIZ_KEY_IN_LOG = re.compile(
    r"tranProcNo|tran_req_no|loan_no|loanNo|order_no|orderNo|"
    r"appl_no|applNo|applyNo|apply_no|acctNo|acct_no|custNo|cust_no|"
    r"fund_\w+|\"fundCode\"|\bCR\d{10,}\b",
    re.I,
)

_PERSISTENCE_REASON_KEYS = (
    "持久化",
    "数据缺失",
    "表查",
    "用户",
    "期望",
    "查询结果",
    "状态核对",
    "字段/指标缺失",
    "对端",
    "ERROR 且含业务键",
)


def _app_messages(logs: dict[str, Any], app: str) -> list[str]:
    block = (logs.get("by_app") or {}).get(app) or {}
    return [e.get("message") or "" for e in block.get("entries") or [] if e.get("message")]


def _all_messages(logs: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for app, block in (logs.get("by_app") or {}).items():
        for e in block.get("entries") or []:
            msg = e.get("message") or ""
            if msg:
                out.append(msg)
    if out:
        return out
    return [e.get("message") or "" for e in (logs.get("entries") or []) if e.get("message")]


def _code_persistence_hints(code: dict[str, Any], app: str) -> set[str]:
    hints: set[str] = set()
    for block in code.get("code_hits") or []:
        if block.get("app") != app:
            continue
        kw = block.get("keyword") or ""
        if re.search(r"Mapper|Dao|ServiceImpl|Repository", kw, re.I):
            hints.add(kw)
        for h in (block.get("class_definitions") or []):
            text = h.get("text") or ""
            m = _PERSISTENCE_CLASS.search(text)
            if m:
                hints.add(m.group(1))
    return hints


def detect_cross_app_sql_hints(
    logs: dict[str, Any],
    investigation_apps: list[str] | None = None,
) -> dict[str, list[str]]:
    """
    扫描全链路日志：若对端已点名某服务的数据/调用缺口，则对该服务给出 SQL 触发理由。

    典型场景：LPS ERROR「获取不到机构产品利率」+ interestRateMap + applyNo，
    AMS 本服务日志却是成功 INFO → 仍应对 AMS 连库核对定价表。
    """
    apps = {(a or "").strip().lower() for a in (investigation_apps or []) if a}
    blob = "\n".join(_all_messages(logs))
    if not blob:
        return {}
    hints: dict[str, list[str]] = {}
    for pat, target, reason in _CROSS_PEER_DATA_GAP:
        target = target.lower()
        if apps and target not in apps:
            continue
        if re.search(pat, blob, re.I):
            hints.setdefault(target, [])
            if reason not in hints[target]:
                hints[target].append(reason)
    return hints


def assess_sql_need_for_app(
    app: str,
    logs: dict[str, Any],
    code: dict[str, Any] | None = None,
    *,
    user_biz_key: str = "",
    db_probes: list[dict] | None = None,
    query_mode: str = "trace_id",
    phenomenon: str = "",
    is_primary: bool = False,
    min_score: int = 2,
    cross_peer_reasons: list[str] | None = None,
    verification_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    判断该服务本轮是否需要 SQL 辅助。

    核心：**有可佐证假设（claim）或用户表查**才查库。
    仅有 ERROR/ServiceImpl 命中、却说不清要核对哪张表时 → 不查。
    """
    code = code or {}
    db_probes = list(db_probes or [])
    app = (app or "").strip().lower()
    messages = _app_messages(logs, app)
    blob = "\n".join(messages)
    reasons: list[str] = []
    score = 0

    app_claims = [
        c for c in (verification_claims or [])
        if app in {(x or "").strip().lower() for x in (c.get("target_apps") or [])}
    ]
    app_probes = [p for p in db_probes if p]

    if app_probes:
        score += 5
        reasons.append(f"用户指定表查 {len(app_probes)} 条")

    if query_mode in ("biz_key", "db_probe"):
        score += 5
        reasons.append(f"检索模式 `{query_mode}` 需查库")

    if app_claims:
        score += 6
        for c in app_claims[:3]:
            desc = (c.get("description") or c.get("id") or "claim").strip()
            reasons.append(f"假设佐证: {desc[:80]}")

    if user_biz_key and is_primary and (app_probes or query_mode in ("biz_key", "db_probe")):
        score += 2
        reasons.append("用户指定业务键")

    if phenomenon and re.search(
        r"表|库|落库|未保存|不存在|重复|状态|plan|loan|order|privilege|利率|定价|fee",
        phenomenon,
        re.I,
    ):
        score += 1
        reasons.append("问题描述涉及数据/表")

    # 以下仅作「线索分」，不足以单独触发查库（须同时有 claim / probe / 模式）
    for pat, label, pts in _NEED_PATTERNS:
        if re.search(pat, blob, re.I):
            score += max(1, pts // 2)
            if label not in reasons:
                reasons.append(f"日志线索: {label}")

    for reason in cross_peer_reasons or []:
        if reason not in reasons:
            reasons.append(reason)

    if not messages and not app_probes and not app_claims:
        return {
            "app": app,
            "needed": False,
            "score": 0,
            "reasons": [],
            "skip_reason": "无该服务日志且无针对该服务的查库假设",
        }

    needed = bool(app_probes) or query_mode in ("biz_key", "db_probe") or bool(app_claims)
    skip_reason = ""
    if not needed:
        if any("日志线索" in r or "字段" in r or "ERROR" in r for r in reasons):
            skip_reason = (
                "日志有异常线索，但未形成「需用某张表佐证」的假设"
                "（例如说不清缺哪条/哪张表），跳过 SQL，避免按 biz_key 广扫 Mapper"
            )
        else:
            skip_reason = "无需要库表佐证的分析假设，不执行 SQL"

    return {
        "app": app,
        "needed": needed,
        "score": score if needed else min(score, 1),
        "reasons": reasons,
        "skip_reason": skip_reason,
        "claims": [c.get("id") for c in app_claims],
    }
