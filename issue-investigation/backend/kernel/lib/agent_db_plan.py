"""Agent 库表佐证计划：由 Agent 分析日志后写出，脚本只校验并执行只读 SQL。

不再用业务场景正则（如 interestRateMap）写死查什么表。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lib.common import load_platform_config, read_json, write_json
from lib.db_probe import _escape_sql_value
from lib.env_config import get_schema_name
from lib.evidence_slim import DB_SELECT_ROW_LIMIT, ensure_select_limit

_ALLOWED_SQL_PREFIX = ("SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN")
_MAX_QUERIES = 5
_BIZ_COL = {
    "apply_no": "apply_no",
    "acct_no": "acct_no",
    "cust_no": "cust_no",
    "loan_no": "loan_no",
    "order_no": "order_no",
    "appl_no": "appl_no",
}


def plan_path(run_dir: Path) -> Path:
    return Path(run_dir) / "agent_db_plan.json"


def suggest_plan_path(run_dir: Path) -> Path:
    return Path(run_dir) / "agent_db_plan.SUGGEST.json"


def empty_plan(*, reason: str = "日志分析无需库表佐证") -> dict[str, Any]:
    return {
        "source": "agent",
        "need_db": False,
        "reason": reason,
        "queries": [],
    }


# 日志 JSON/文本中常见业务键 → 默认可查表（只作建议，不自动执行）
_LOG_KEY_TO_QUERIES: list[tuple[re.Pattern[str], str, str, str]] = [
    # (pattern capturing value, app, table, where_column)
    (re.compile(r'"creditReqNo"\s*:\s*"([^"]+)"', re.I), "lps", "ap_fund_appl", "credit_apply_no"),
    (re.compile(r'"creditReqNo"\s*:\s*"([^"]+)"', re.I), "lps", "ap_fund_appl", "appl_no"),
    (re.compile(r'"applyNo"\s*:\s*"([^"]+)"', re.I), "lps", "ap_fund_appl", "appl_no"),
    (re.compile(r'"apply_no"\s*:\s*"([^"]+)"', re.I), "ams", "ac_pilot_prd_term_fee", "apply_no"),
    (re.compile(r'\b(CR\d{10,})\b'), "ams", "ac_pilot_prd_term_fee", "apply_no"),
    (re.compile(r'"loanNo"\s*:\s*"([^"]+)"', re.I), "lcs", "pilot_loan", "loan_no"),
    (re.compile(r'"loan_no"\s*:\s*"([^"]+)"', re.I), "lcs", "pilot_loan", "loan_no"),
    (re.compile(r'\b(L\d{12,})\b'), "lcs", "pilot_loan", "loan_no"),
]


_NEED_DB_MSG = re.compile(
    r"未获取到|查无|不存在|无记录|未落库|0\s*行|Duplicate|SQLException|"
    r"interestRateMap|获取不到|数据缺失",
    re.I,
)


def build_suggest_plan(
    evidence: dict[str, Any] | None,
    *,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据日志/推断生成只读候选计划（不自动执行）。"""
    evidence = evidence or {}
    ctx = ctx or evidence.get("context") or {}
    primary = (ctx.get("app") or "lps").strip().lower()
    apps = list(ctx.get("apps") or [primary])
    logs = evidence.get("logs") or {}
    db_inf = evidence.get("db_inference") or ctx.get("db_inference") or {}

    messages: list[str] = []
    for block in (logs.get("by_app") or {}).values():
        for e in block.get("entries") or []:
            messages.append(e.get("message") or "")
    for e in logs.get("entries") or []:
        messages.append(e.get("message") or "")
    blob = "\n".join(messages)

    queries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(app: str, table: str, col: str, val: str, why: str) -> None:
        if not val or len(val) < 4 or "*" in val:
            return
        if app not in set(apps) | {primary, "ams", "goa", "lcs", "lps"}:
            return
        key = f"{app}|{table}|{col}|{val}"
        if key in seen:
            return
        seen.add(key)
        queries.append({
            "app": app,
            "table": table,
            "where_column": col,
            "where_value": val,
            "why": why,
        })

    for pat, app, table, col in _LOG_KEY_TO_QUERIES:
        for m in pat.finditer(blob):
            val = m.group(1)
            _add(app, table, col, val, f"日志字段命中，建议核对 {app}.{table}.{col}")

    for c in (db_inf.get("biz_key_candidates") or [])[:5]:
        kind = (c.get("kind") or "").strip().lower()
        val = str(c.get("value") or "").strip()
        if kind in ("apply_no", "appl_no") and val:
            _add("ams", "ac_pilot_prd_term_fee", "apply_no", val, "db_inference 业务键")
            _add("lps", "ap_fund_appl", "appl_no", val, "db_inference 业务键")
        elif kind in ("loan_no",) and val:
            _add("lcs", "pilot_loan", "loan_no", val, "db_inference 业务键")
        elif kind in ("credit_apply_no", "credit_req_no") and val:
            _add("lps", "ap_fund_appl", "credit_apply_no", val, "db_inference 业务键")

    # 跨服务提示：对端指向 ams/lcs 数据缺口
    try:
        from lib.infer_db_signals import detect_cross_app_sql_hints

        hints = detect_cross_app_sql_hints(logs, investigation_apps=apps)
        for target, reasons in (hints or {}).items():
            if target == "goa":
                continue
            # 已有具体 query 则只补充 reason；否则不硬猜表
            if any(q.get("app") == target for q in queries):
                for q in queries:
                    if q.get("app") == target and reasons:
                        q["why"] = f"{q.get('why')}; {reasons[0]}"
    except Exception:
        pass

    queries = queries[:_MAX_QUERIES]
    need = bool(queries) and bool(_NEED_DB_MSG.search(blob) or queries)
    if not queries:
        return {
            "source": "suggest",
            "need_db": False,
            "reason": "未从日志自动抽出可核对的表键；可无需查库或自行补充",
            "queries": [],
            "note": "本文件仅建议，不会被自动执行。确认后复制到 agent_db_plan.json",
        }
    return {
        "source": "suggest",
        "need_db": need,
        "reason": "根据日志业务键自动生成的候选库表计划（只读建议）",
        "queries": queries,
        "note": "本文件仅建议，不会被自动执行。可复制为 agent_db_plan.json 微调后执行",
    }


def write_suggest_plan(
    run_dir: Path,
    evidence: dict[str, Any] | None = None,
    *,
    ctx: dict[str, Any] | None = None,
) -> Path:
    plan = build_suggest_plan(evidence, ctx=ctx)
    path = suggest_plan_path(run_dir)
    write_json(path, plan)
    return path


def load_agent_db_plan(run_dir: Path) -> dict[str, Any] | None:
    path = plan_path(run_dir)
    if not path.is_file():
        return None
    raw = read_json(path, {})
    return raw if isinstance(raw, dict) else None


def save_agent_db_plan(run_dir: Path, plan: dict[str, Any]) -> Path:
    path = plan_path(run_dir)
    write_json(path, plan)
    return path


def _safe_ident(name: str) -> str:
    n = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n):
        raise ValueError(f"非法标识符: {name!r}")
    return n


def _normalize_query(item: dict[str, Any], env: str) -> dict[str, Any]:
    """将 Agent 条目规范为可执行 {app, sql, why}。"""
    why = (item.get("why") or item.get("reason") or item.get("description") or "").strip()
    app = (item.get("app") or "").strip().lower()
    sql = (item.get("sql") or "").strip()

    if sql:
        upper = sql.lstrip().upper()
        if not upper.startswith(_ALLOWED_SQL_PREFIX):
            raise ValueError(f"禁止非只读 SQL: {sql[:80]}")
        if ";" in sql.rstrip().rstrip(";"):
            raise ValueError("禁止一次提交多条 SQL")
        if not app:
            # 尝试从 `schema`.`table` 推断
            m = re.search(r"FROM\s+`?([a-zA-Z0-9_]+)`?\.", sql, re.I)
            if m:
                app = m.group(1).lower()
        if not app:
            raise ValueError("SQL 查询缺少 app 字段")
        sql = ensure_select_limit(sql)
        return {"app": app, "sql": sql, "why": why or "Agent 指定查询"}

    # 结构化：app + table + where_column + where_value
    table = _safe_ident(item.get("table") or "")
    col = (item.get("where_column") or item.get("column") or "").strip()
    if col in _BIZ_COL:
        col = _BIZ_COL[col]
    col = _safe_ident(col)
    val = str(item.get("where_value") or item.get("value") or "").strip()
    if not app or not table or not col or not val:
        raise ValueError(
            "结构化查询需提供 app、table、where_column、where_value；或直接提供只读 sql"
        )
    if "*" in val or "…" in val or "..." in val:
        raise ValueError(f"where_value 疑似脱敏，不可用于 SQL: {val!r}")

    app_cfg = load_platform_config().get("apps", {}).get(app) or {}
    schema = get_schema_name(env, app_cfg.get("primary_schema") or app)
    schema = _safe_ident(schema)
    escaped_val = _escape_sql_value(val)
    sql = ensure_select_limit(
        f"SELECT * FROM `{schema}`.`{table}` WHERE `{col}` = '{escaped_val}'"
    )
    return {
        "app": app,
        "sql": sql,
        "why": why or f"核对 {schema}.{table}.{col}={val}",
    }


def validate_and_normalize_plan(
    plan: dict[str, Any] | None,
    *,
    env: str,
    investigation_apps: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    返回 (executable_queries, meta)。
    need_db=false 或 queries=[] → 空列表。
    """
    apps_allow = {(a or "").strip().lower() for a in (investigation_apps or []) if a}
    catalog_apps = set((load_platform_config().get("apps") or {}).keys())
    if not plan:
        return [], {"source": "none", "need_db": False, "reason": "无 agent_db_plan.json", "errors": []}

    need = plan.get("need_db")
    raw_q = list(plan.get("queries") or [])
    if need is False and not raw_q:
        return [], {
            "source": "agent",
            "need_db": False,
            "reason": plan.get("reason") or "Agent 判断无需查库",
            "errors": [],
        }

    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, item in enumerate(raw_q[:_MAX_QUERIES]):
        if not isinstance(item, dict):
            errors.append(f"queries[{i}] 不是对象")
            continue
        try:
            q = _normalize_query(item, env)
            if apps_allow and q["app"] not in apps_allow and q["app"] not in catalog_apps:
                # 允许扩大到 catalog 内服务（关联排查 ams 等）
                if q["app"] not in catalog_apps:
                    raise ValueError(f"未知 app: {q['app']}")
            elif q["app"] not in catalog_apps:
                raise ValueError(f"未知 app: {q['app']}")
            out.append(q)
        except ValueError as exc:
            errors.append(f"queries[{i}]: {exc}")

    meta = {
        "source": "agent",
        "need_db": bool(out),
        "reason": plan.get("reason") or ("有查库计划" if out else "计划无有效查询"),
        "errors": errors,
        "raw_count": len(raw_q),
        "accepted_count": len(out),
    }
    return out, meta


def queries_as_mapper_tuples(
    queries: list[dict[str, Any]],
) -> dict[str, list[tuple[str, str, str]]]:
    """转成 collect_db 的 mapper_queries_by_app: app -> [(label, sql, reason)]。"""
    by_app: dict[str, list[tuple[str, str, str]]] = {}
    for i, q in enumerate(queries, 1):
        app = q["app"]
        label = f"agent:query_{i}"
        by_app.setdefault(app, []).append((label, q["sql"], q.get("why") or "Agent 计划"))
    return by_app


def agent_plan_help_text(run_dir: Path, evidence: dict | None = None, ctx: dict | None = None) -> str:
    """写给 Agent 的计划文件说明（动态包含当前排查上下文）。"""
    lines = [
        f"优先参考同目录 `agent_db_plan.SUGGEST.json`（脚本根据日志自动生成的候选计划，**不会自动执行**）。",
        f"确认后写入 `{plan_path(run_dir)}`，或直接复制 SUGGEST 再微调。格式示例：",
        "```json",
        "{",
        '  "source": "agent",',
        '  "need_db": true,',
        '  "reason": "一句话说明为何要查库",',
        '  "queries": [',
        "    {",
        '      "app": "ams",',
        '      "why": "佐证日志中缺失的数据点",',
        '      "table": "ac_pilot_prd_term_fee",',
        '      "where_column": "apply_no",',
        '      "where_value": "CR...."',
        "    }",
        "  ]",
        "}",
        "```",
        "无需查库时：`{\"source\":\"agent\",\"need_db\":false,\"reason\":\"...\",\"queries\":[]}`",
        f"单次最多 {_MAX_QUERIES} 条只读 SELECT（每条自动 LIMIT {DB_SELECT_ROW_LIMIT}）；也可直接给 `sql` 字段。",
        "evidence.json 仅保留行预览，分析阶段请读 `investigation-report.md`，勿整读 evidence。",
    ]

    # ── 动态上下文注入 ──
    if evidence:
        logs = evidence.get("logs") or {}
        db_inf = evidence.get("db_inference") or ctx.get("db_inference") or {} if ctx else {}
        code = evidence.get("code") or {}
        apps = (evidence.get("context") or {}).get("apps") or (ctx or {}).get("apps") or []

        # 1. 日志业务键摘录
        biz_candidates = db_inf.get("biz_key_candidates") or []
        if biz_candidates:
            lines.append("")
            lines.append("## 日志提取的业务键（可直接用于 where_value）")
            for c in biz_candidates[:5]:
                src = c.get("source", "logs")
                lines.append(f"- `{c.get('kind', '?')}` = `{c.get('value', '?')}`（来源：{src}）")

        # 2. 场景推断
        scenario = db_inf.get("scenario") or "default"
        scenarios = db_inf.get("scenarios") or {}
        if scenario != "default":
            lines.append("")
            lines.append(f"## 场景推断：**{scenario}**")
            if scenarios:
                lines.append(f"各应用场景：{', '.join(f'{a}={s}' for a, s in scenarios.items())}")

        # 3. 代码扫描命中的 Mapper 类
        mapper_hits: list[str] = []
        for block in (code.get("code_hits") or []):
            kw = (block.get("keyword") or "")
            if re.search(r"Mapper|Dao|ServiceImpl|Repository", kw, re.I):
                app_tag = f"[{block.get('app', '?')}]"
                mapper_hits.append(f"{app_tag} {kw}")
        if mapper_hits:
            lines.append("")
            lines.append("## 代码扫描命中的持久化类（暗示相关表）")
            for h in mapper_hits[:6]:
                lines.append(f"- {h}")

        # 4. 可用 schema 清单（从配置页）
        from lib.common import load_platform_config as _load_cat
        cat = _load_cat()
        cat_apps = cat.get("apps") or {}
        relevant_schemas: list[str] = []
        for app in (apps or [app for app in cat_apps]):
            app_cfg = cat_apps.get(app) or {}
            schema = app_cfg.get("primary_schema") or app
            relevant_schemas.append(f"{app} → `{schema}`")
        if relevant_schemas:
            lines.append("")
            lines.append("## 可用 schema")
            for s in relevant_schemas:
                lines.append(f"- {s}")

        # 5. 跨服务 SQL 提示
        try:
            from lib.infer_db_signals import detect_cross_app_sql_hints
            hints = detect_cross_app_sql_hints(logs, investigation_apps=apps)
            if hints:
                lines.append("")
                lines.append("## 跨服务 SQL 提示（对端日志指向数据缺口）")
                for target, reasons in hints.items():
                    lines.append(f"- **{target}**：{'；'.join(reasons[:3])}")
        except ImportError:
            pass

    return "\n".join(lines)
