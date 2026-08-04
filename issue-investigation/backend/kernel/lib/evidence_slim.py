"""evidence.json 瘦身：限制 SQL 行数、落盘仅保留预览，避免 Agent 误读巨型证据。"""
from __future__ import annotations

import re
from typing import Any

# 只读 SELECT 默认行上限（注入 LIMIT；已有 LIMIT 则保留）
DB_SELECT_ROW_LIMIT = 20
# evidence 中每条查询最多保留的行预览
DB_ROWS_PREVIEW = 5
# 单条日志 message 落盘上限（字符）
LOG_MESSAGE_MAX_CHARS = 2000

_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
_RO_PREFIX = ("SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN")


def ensure_select_limit(sql: str, limit: int = DB_SELECT_ROW_LIMIT) -> str:
    """为 SELECT 注入 LIMIT；SHOW/DESC/EXPLAIN 不动；已有 LIMIT 则保留。"""
    raw = (sql or "").strip()
    if not raw:
        return raw
    body = raw.rstrip().rstrip(";")
    upper = body.lstrip().upper()
    if not upper.startswith("SELECT"):
        return raw if raw.endswith(";") else f"{body};"
    if upper.startswith(("SHOW", "DESC", "DESCRIBE", "EXPLAIN")):
        return raw if raw.endswith(";") else f"{body};"
    if _LIMIT_RE.search(body):
        return f"{body};"
    return f"{body} LIMIT {int(limit)};"


def slim_query_entry(
    entry: dict[str, Any],
    *,
    preview: int = DB_ROWS_PREVIEW,
) -> dict[str, Any]:
    """保留 count，rows 仅存前 preview 行。"""
    out = dict(entry)
    rows = out.get("rows")
    if not isinstance(rows, list):
        return out
    count = out.get("count")
    if not isinstance(count, int):
        count = len(rows)
    out["count"] = count
    if len(rows) > preview:
        out["rows"] = rows[:preview]
        out["rows_truncated"] = True
        out["rows_stored"] = preview
    else:
        out["rows_truncated"] = False
        out["rows_stored"] = len(rows)
    return out


def _slim_by_app_block(block: dict[str, Any]) -> dict[str, Any]:
    """by_app 内去掉与顶层 queries 重复的全量 rows，只留摘要。"""
    if "queries_summary" in block and "queries" not in block:
        return block
    out = {k: v for k, v in block.items() if k != "queries"}
    summaries: list[dict[str, Any]] = []
    for q in block.get("queries") or []:
        if not isinstance(q, dict):
            continue
        summaries.append(
            {
                "file": q.get("file"),
                "sql": q.get("sql"),
                "count": q.get("count"),
                "source": q.get("source"),
                "error": q.get("error"),
                "executed": q.get("executed"),
                "inference_reason": (q.get("inference_reason") or "")[:220] or None,
            }
        )
    out["queries_summary"] = summaries
    return out


def slim_database_block(db: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(db, dict):
        return {}
    out = dict(db)
    out["queries"] = [
        slim_query_entry(q) for q in (out.get("queries") or []) if isinstance(q, dict)
    ]
    by_app = out.get("by_app") or {}
    if isinstance(by_app, dict):
        slim_apps: dict[str, Any] = {}
        for app, block in by_app.items():
            if isinstance(block, dict):
                slim_apps[app] = _slim_by_app_block(block)
            else:
                slim_apps[app] = block
        out["by_app"] = slim_apps
    out["evidence_slim"] = {
        "db_select_row_limit": DB_SELECT_ROW_LIMIT,
        "db_rows_preview": DB_ROWS_PREVIEW,
        "note": "全量行未落盘；分析请读 investigation-report.md，勿整读 evidence.json",
    }
    return out


def _trim_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    msg = out.get("message")
    if isinstance(msg, str) and len(msg) > LOG_MESSAGE_MAX_CHARS:
        out["message"] = msg[:LOG_MESSAGE_MAX_CHARS] + "…(truncated)"
        out["message_truncated"] = True
    return out


def slim_logs_block(logs: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(logs, dict):
        return {}
    out = dict(logs)
    entries = out.get("entries")
    if isinstance(entries, list):
        out["entries"] = [
            _trim_log_entry(e) if isinstance(e, dict) else e for e in entries
        ]
    by_app = out.get("by_app") or {}
    if isinstance(by_app, dict):
        slim_apps: dict[str, Any] = {}
        for app, block in by_app.items():
            if not isinstance(block, dict):
                slim_apps[app] = block
                continue
            b = dict(block)
            app_entries = b.get("entries")
            if isinstance(app_entries, list):
                b["entries"] = [
                    _trim_log_entry(e) if isinstance(e, dict) else e for e in app_entries
                ]
            slim_apps[app] = b
        out["by_app"] = slim_apps
    return out


def slim_evidence(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """写入 evidence.json 前调用：瘦身 database + logs。"""
    if not isinstance(evidence, dict):
        return {}
    out = dict(evidence)
    if "database" in out:
        out["database"] = slim_database_block(out.get("database"))
    if "logs" in out:
        out["logs"] = slim_logs_block(out.get("logs"))
    return out
