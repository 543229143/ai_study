"""用户指定的 表.字段=值 排查项 → 只读 SELECT；错误现象供报告核对。"""
from __future__ import annotations

import re
from typing import Any

_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SPEC = re.compile(
    r"^(?:(?P<schema>[a-zA-Z_][a-zA-Z0-9_]*)\.)?"
    r"(?P<table>[a-zA-Z_][a-zA-Z0-9_]*)\."
    r"(?P<column>[a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?P<value>.+)$"
)


def _escape_sql_value(val: str) -> str:
    return val.replace("\\", "\\\\").replace("'", "''")


def _parse_table_column(left: str) -> tuple[str | None, str, str]:
    """返回 (schema_or_none, table, column)。"""
    parts = left.split(".")
    if len(parts) == 2:
        return None, parts[0], parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise ValueError(f"无法解析表字段: {left}（格式: 表名.字段=值 或 schema.表名.字段=值）")


def _validate_ident(*names: str) -> None:
    for n in names:
        if not _IDENT.match(n):
            raise ValueError(f"非法标识符: {n}")


def parse_spec_line(line: str, *, kind: str) -> dict[str, Any]:
    line = line.strip()
    if not line:
        raise ValueError("空行")
    m = _SPEC.match(line)
    if not m:
        raise ValueError(f"格式应为 表名.字段=值，实际: {line}")
    schema_opt = m.group("schema")
    table = m.group("table")
    column = m.group("column")
    value = m.group("value").strip()
    _validate_ident(table, column)
    if schema_opt:
        _validate_ident(schema_opt)
    entry: dict[str, Any] = {
        "table": table,
        "column": column,
        "value": value,
        "schema": schema_opt,
        "raw": line,
        "kind": kind,
    }
    if kind == "expectation":
        entry["expected"] = value
    return entry


def parse_probe_text(
    text: str,
    *,
    collect_bad: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    解析排查/错误现象文本。支持：
    - 排查: pilot_loan.loan_no=LO...
    - 错误现象: pilot_plan.term=12
    - 块格式（排查:/错误现象: 下多行）

    collect_bad=True 时返回三元组 (probes, expectations, bad_lines)，
    bad_lines 为格式错误行的说明（原文 + 原因 + 正确格式），供表单回显提示。
    默认返回二元组，保持旧调用兼容。
    """
    probes: list[dict[str, Any]] = []
    expectations: list[dict[str, Any]] = []
    bad_lines: list[str] = []
    if not (text or "").strip():
        return (probes, expectations, bad_lines) if collect_bad else (probes, expectations)

    block_mode: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^排查\s*[:：]?\s*$", line):
            block_mode = "probe"
            continue
        if re.match(r"^错误现象\s*[:：]?\s*$", line):
            block_mode = "expectation"
            continue
        if line.startswith("排查"):
            block_mode = "probe"
            rest = re.sub(r"^排查\s*[:：]\s*", "", line).strip()
            if not rest:
                continue
            line = rest
        elif line.startswith("错误现象"):
            block_mode = "expectation"
            rest = re.sub(r"^错误现象\s*[:：]\s*", "", line).strip()
            if not rest:
                continue
            line = rest

        kind = block_mode or "probe"
        try:
            entry = parse_spec_line(line, kind=kind)
        except ValueError as exc:
            if collect_bad:
                bad_lines.append(f"「{line}」解析失败：{exc}。正确格式：表名.字段=值（如 pilot_loan.loan_no=LO1024）")
            continue
        if entry["kind"] == "expectation":
            expectations.append(entry)
        else:
            probes.append(entry)
    if collect_bad:
        return probes, expectations, bad_lines
    return probes, expectations


def build_probe_sql(
    probe: dict[str, Any],
    default_schema: str,
    *,
    limit: int | None = None,
) -> tuple[str, str]:
    from lib.evidence_slim import DB_SELECT_ROW_LIMIT, ensure_select_limit

    schema = probe.get("schema") or default_schema
    table = probe["table"]
    column = probe["column"]
    value = probe["value"]
    _validate_ident(schema, table, column)
    esc = _escape_sql_value(value)
    row_limit = DB_SELECT_ROW_LIMIT if limit is None else limit
    sql = ensure_select_limit(
        f"SELECT * FROM `{schema}`.`{table}` WHERE `{column}` = '{esc}'",
        row_limit,
    )
    label = f"probe:{schema}.{table}.{column}={value[:24]}"
    return label, sql


def merge_probe_lists(*lists: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for lst in lists:
        for p in lst or []:
            key = f"{p.get('schema') or ''}.{p['table']}.{p['column']}={p['value']}"
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def format_probe_lines(probes: list[dict], expectations: list[dict]) -> str:
    lines: list[str] = []
    if probes:
        lines.append("排查:")
        for p in probes:
            sch = p.get("schema")
            prefix = f"{sch}." if sch else ""
            lines.append(f"{prefix}{p['table']}.{p['column']}={p['value']}")
    if expectations:
        if lines:
            lines.append("")
        lines.append("错误现象:")
        for e in expectations:
            sch = e.get("schema")
            prefix = f"{sch}." if sch else ""
            lines.append(f"{prefix}{e['table']}.{e['column']}={e.get('expected', e['value'])}")
    return "\n".join(lines)


def _norm_name(name: str) -> str:
    return re.sub(r"[_\s]", "", (name or "").lower())


_SCENARIO_TABLE_HINTS: dict[str, list[str]] = {
    "privilege-plan": ["privilege_plan", "privilegeplan"],
}


def select_probes_for_log_context(
    hints: list[dict],
    log_messages: list[str],
    db_inference: dict,
    code_hits: list[dict] | None = None,
    *,
    min_score: int = 3,
) -> tuple[list[dict], list[dict], str]:
    """trace/告警：按日志与代码上下文筛选表查提示，不盲目执行。"""
    if not hints:
        return [], [], ""

    blob = "\n".join(log_messages or []).lower()
    blob_compact = _norm_name(blob)
    biz_key = (db_inference.get("biz_key") or "").strip()
    scenario = db_inference.get("scenario") or "default"
    scenario_tables = _SCENARIO_TABLE_HINTS.get(scenario) or []
    code_hits = code_hits or []

    applied: list[dict] = []
    skipped: list[dict] = []

    for p in hints:
        table = p.get("table") or ""
        column = p.get("column") or ""
        value = (p.get("value") or "").strip()
        tbl_norm = _norm_name(table)
        col_norm = _norm_name(column)
        score = 0
        reasons: list[str] = []

        if value and value.lower() in blob:
            score += 3
            reasons.append("值出现在日志")
        if biz_key and value == biz_key:
            score += 3
            reasons.append("与推断业务键一致")
        if tbl_norm and tbl_norm in blob_compact:
            score += 2
            reasons.append("表名出现在日志")
        if col_norm and col_norm in blob_compact:
            score += 1
            reasons.append("字段出现在日志")
        for st in scenario_tables:
            if st in tbl_norm or tbl_norm in _norm_name(st):
                score += 3
                reasons.append(f"与场景 {scenario} 相关")
                break
        for block in code_hits:
            kw = _norm_name(block.get("keyword") or "")
            if tbl_norm and (tbl_norm in kw or kw in tbl_norm):
                score += 2
                reasons.append("表与代码扫描命中相关")
                break

        entry = {**p, "relevance_score": score, "relevance_reasons": reasons}
        if score >= min_score:
            applied.append(entry)
        else:
            skipped.append({
                **entry,
                "skip_reason": "与当前日志/代码上下文关联不足，未采用",
            })

    note = ""
    if hints:
        note = (
            f"用户表查提示 {len(hints)} 条，经日志分析采用 {len(applied)} 条，"
            f"未采用 {len(skipped)} 条"
        )
    return applied, skipped, note


def compare_expectations(
    expectations: list[dict],
    query_results: list[dict],
    default_schema: str,
) -> list[dict]:
    """将期望与查询结果行比对，供报告展示。"""
    rows_by_table: dict[str, list[dict]] = {}
    for q in query_results:
        for row in q.get("rows") or []:
            tbl = q.get("probe_table") or ""
            if tbl:
                rows_by_table.setdefault(tbl, []).append(row)

    checks: list[dict] = []
    for exp in expectations:
        schema = exp.get("schema") or default_schema
        table = exp["table"]
        column = exp["column"]
        expected = exp.get("expected", exp.get("value", ""))
        matched_rows = rows_by_table.get(table, [])
        actual_values: list[Any] = []
        for row in matched_rows:
            if column in row:
                actual_values.append(row[column])
        ok = any(str(v) == str(expected) for v in actual_values) if actual_values else None
        checks.append({
            "schema": schema,
            "table": table,
            "column": column,
            "expected": expected,
            "actual": actual_values[:5],
            "match": ok,
            "raw": exp.get("raw", ""),
        })
    return checks
