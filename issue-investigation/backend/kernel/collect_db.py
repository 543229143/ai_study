#!/usr/bin/env python3
"""只读 DB 取证：优先执行用户指定的 表.字段=值 排查 SQL，其次 Mapper XML 推断。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.common import assert_app_supported, assert_env_supported, write_json
from lib.db_probe import build_probe_sql, compare_expectations
from lib.deps import ensure_pymysql
from lib.env_config import get_mysql_config, get_schema_name
from lib.evidence_slim import ensure_select_limit, slim_database_block, slim_query_entry
from lib.infer_db_scope import schema_to_app
from lib.infer_db_sql import infer_queries_from_code


def _connect(env: str):
    pymysql = ensure_pymysql()

    cfg = get_mysql_config(env)
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=30,
    ), cfg


def _run_select(conn, sql: str, default_db: str) -> list[dict]:
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith(("SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN")):
        raise ValueError(f"禁止非只读 SQL: {sql[:80]}")
    with conn.cursor() as cur:
        cur.execute(f"USE `{default_db}`")
        cur.execute(sql)
        return list(cur.fetchall())


# 匹配 FROM `schema`.`table` 或 FROM `table`
_TABLE_FROM_RE = re.compile(r"FROM\s+`([^`]+)`\s*\.\s*`([^`]+)`", re.IGNORECASE)
_TABLE_FROM_SIMPLE_RE = re.compile(r"FROM\s+`([^`]+)`", re.IGNORECASE)
_COLUMN_IN_SELECT_RE = re.compile(r"SELECT\s+(.*?)\s+FROM", re.IGNORECASE | re.DOTALL)
_COLUMN_IN_WHERE_RE = re.compile(r"WHERE\s+.*?`([^`]+)`\s*=", re.IGNORECASE)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _diagnose_sql_error(conn, sql: str, default_schema: str, exc: Exception) -> str:
    """SELECT 失败后补充表/列存在性说明（lazy，避免成功路径额外往返）。"""
    msg = str(exc)
    schema = default_schema
    table = ""
    m = _TABLE_FROM_RE.search(sql or "")
    if m:
        schema, table = m.group(1), m.group(2)
    else:
        m2 = _TABLE_FROM_SIMPLE_RE.search(sql or "")
        if m2:
            table = m2.group(1)
    tips: list[str] = []
    if table and _IDENT_RE.match(schema) and _IDENT_RE.match(table):
        try:
            rows = _run_select(
                conn,
                f"SELECT COUNT(*) AS c FROM information_schema.TABLES "
                f"WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME='{table}'",
                schema,
            )
            if not rows or not int(rows[0].get("c") or 0):
                tips.append(f"表 `{schema}`.`{table}` 不存在")
            else:
                cols = {m.group(1) for m in _COLUMN_IN_WHERE_RE.finditer(sql or "")}
                # 也抓 SELECT 列表里的裸列名（简单场景）
                for col in list(cols)[:8]:
                    if not _IDENT_RE.match(col):
                        continue
                    try:
                        cr = _run_select(
                            conn,
                            f"SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                            f"WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME='{table}' "
                            f"AND COLUMN_NAME='{col}'",
                            schema,
                        )
                        if not cr or not int(cr[0].get("c") or 0):
                            tips.append(f"列 `{col}` 不存在于 `{schema}`.`{table}`")
                    except Exception:
                        pass
        except Exception as diag_exc:
            tips.append(f"诊断失败: {diag_exc}")
    return msg + (("；" + "；".join(tips)) if tips else "")


def _run_probe_queries(
    conn,
    primary_schema: str,
    db_probes: list[dict],
) -> list[dict]:
    queries: list[dict] = []
    seen_sql: set[str] = set()
    for probe in db_probes:
        label, sql = build_probe_sql(probe, primary_schema)
        norm = sql.strip().lower()
        if norm in seen_sql:
            continue
        seen_sql.add(norm)
        try:
            schema = probe.get("schema") or primary_schema
            sql = ensure_select_limit(sql)
            rows = _run_select(conn, sql, schema)
            entry = slim_query_entry({
                "file": label,
                "sql": sql,
                "rows": rows,
                "count": len(rows),
                "source": "user_probe",
                "executed": True,
                "inference_reason": "用户在表单中指定的表查",
                "probe_table": probe["table"],
                "probe_column": probe["column"],
                "probe_value": probe["value"],
            })
            # 空结果时自动获取表结构，方便 Agent 调整查询
            if not rows:
                try:
                    col_rows = _run_select(conn, f"SHOW COLUMNS FROM `{schema}`.`{probe['table']}`", schema)
                    entry["available_columns"] = [r.get("Field", "") for r in col_rows if r.get("Field")]
                except Exception:
                    pass
            queries.append(entry)
        except Exception as exc:
            queries.append({
                "file": label,
                "sql": sql,
                "rows": [],
                "count": 0,
                "source": "user_probe",
                "executed": True,
                "inference_reason": "用户在表单中指定的表查",
                "probe_table": probe["table"],
                "probe_column": probe["column"],
                "probe_value": probe["value"],
                "error": str(exc),
            })
    return queries


def collect(
    app: str,
    env: str,
    biz_key: str,
    *,
    repo_root: Path | None = None,
    biz_key_kind: str = "loan_no",
    keywords: list[str] | None = None,
    mapper_queries: list[tuple[str, str, str]] | None = None,
    db_probes: list[dict] | None = None,
    db_expectations: list[dict] | None = None,
    db_probe_hints: list[dict] | None = None,
    db_probes_skipped: list[dict] | None = None,
    db_probe_selection_note: str = "",
    mapper_queries_skipped: list[dict] | None = None,
    output: Path | None = None,
) -> dict:
    assert_env_supported(env)
    app_cfg = assert_app_supported(app)
    primary_schema = get_schema_name(env, app_cfg.get("primary_schema") or app)
    db_probes = list(db_probes or [])
    db_expectations = list(db_expectations or [])
    db_probe_hints = list(db_probe_hints or [])
    db_probes_skipped = list(db_probes_skipped or [])
    mapper_queries_skipped = list(mapper_queries_skipped or [])

    result: dict = {
        "app": app,
        "env": env,
        "biz_key": biz_key,
        "biz_key_kind": biz_key_kind,
        "schema": primary_schema,
        "db_host": None,
        "queries": [],
        "db_probes": db_probes,
        "db_expectations": db_expectations,
        "expectation_checks": [],
        "skipped": False,
        "error": None,
        "source": "mapper_xml",
        "mapper_queries_skipped": mapper_queries_skipped,
    }

    if not db_probes and not biz_key and not mapper_queries:
        result["skipped"] = True
        parts: list[str] = []
        if db_probe_hints and db_probes_skipped and not db_probes:
            parts.append(
                f"用户表查提示 {len(db_probe_hints)} 条经日志分析均未采用"
            )
        if not biz_key:
            parts.append("未从日志提取业务键")
        parts.append("跳过 DB 采集")
        if db_probe_selection_note:
            parts.insert(0, db_probe_selection_note)
        result["error"] = "；".join(parts)
        if output:
            write_json(output, result)
        return result

    generated = list(mapper_queries or [])
    if not generated and biz_key and repo_root and repo_root.is_dir():
        generated = infer_queries_from_code(
            repo_root, app, env, biz_key, biz_key_kind, keywords,
        )

    if not db_probes and not generated:
        result["skipped"] = True
        skip_parts: list[str] = []
        if mapper_queries_skipped:
            skip_parts.append(
                f"Mapper 推断 SQL {len(mapper_queries_skipped)} 条未通过日志字段绑定校验"
            )
        if not repo_root or not repo_root.is_dir():
            skip_parts.append("无本地代码仓，无法从 Mapper XML 生成 SQL")
        else:
            skip_parts.append(
                f"未在 {app} 代码仓 Mapper XML 中找到可执行的 `{biz_key_kind}` 条件 SELECT"
            )
        result["error"] = "；".join(skip_parts) if skip_parts else "未执行 DB 查询"
        if output:
            write_json(output, result)
        return result

    sources: list[str] = []
    if db_probes:
        sources.append("user_probe")
    if generated:
        if any(str(item[0]).startswith("agent:") for item in generated):
            sources.append("agent_plan")
        else:
            sources.append("mapper_xml")
    result["source"] = "+".join(sources) if sources else "none"

    try:
        conn, cfg = _connect(env)
        result["db_host"] = cfg["host"]
        if db_probes:
            result["queries"].extend(_run_probe_queries(conn, primary_schema, db_probes))

        seen_sql = {q.get("sql", "").strip().lower() for q in result["queries"]}
        for item in generated:
            label, sql = item[0], item[1]
            reason = item[2] if len(item) > 2 else ""
            norm = sql.strip().lower()
            if norm in seen_sql:
                continue
            seen_sql.add(norm)
            q_source = "agent_plan" if str(label).startswith("agent:") else "mapper_xml"
            try:
                sql = ensure_select_limit(sql)
                rows = _run_select(conn, sql, primary_schema)
                result["queries"].append(slim_query_entry({
                    "file": label,
                    "sql": sql,
                    "rows": rows,
                    "count": len(rows),
                    "source": q_source,
                    "executed": True,
                    "inference_reason": reason,
                }))
            except Exception as exc:
                err_msg = _diagnose_sql_error(conn, sql, primary_schema, exc)
                result["queries"].append({
                    "file": label,
                    "sql": sql,
                    "rows": [],
                    "count": 0,
                    "source": q_source,
                    "executed": True,
                    "inference_reason": reason,
                    "error": err_msg,
                })
        conn.close()
    except Exception as exc:
        result["error"] = str(exc)
        result["skipped"] = True

    if db_expectations and result.get("queries"):
        result["expectation_checks"] = compare_expectations(
            db_expectations,
            result["queries"],
            primary_schema,
        )

    if not result["queries"]:
        result["skipped"] = True
        if not result.get("error"):
            result["error"] = "未执行任何 DB 查询"

    if output:
        write_json(output, result)
    return result


def collect_multi(
    apps: list[str],
    env: str,
    biz_key: str,
    *,
    biz_keys: dict[str, str] | None = None,
    biz_key_kinds: dict[str, str] | None = None,
    repo_roots: dict[str, Path] | None = None,
    keywords_by_app: dict[str, list[str]] | None = None,
    mapper_queries_by_app: dict[str, list[tuple[str, str, str]]] | None = None,
    db_probes: list[dict] | None = None,
    db_expectations: list[dict] | None = None,
    db_probe_hints: list[dict] | None = None,
    db_probes_skipped: list[dict] | None = None,
    db_probe_selection_note: str = "",
    mapper_queries_skipped: list[dict] | None = None,
    db_apps_out_of_scope: list[dict] | None = None,
    investigation_apps: list[str] | None = None,
    output: Path | None = None,
) -> dict:
    """多应用 DB：各应用独立建连，并行执行只读查询。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    biz_keys = biz_keys or {}
    biz_key_kinds = biz_key_kinds or {}
    repo_roots = repo_roots or {}
    keywords_by_app = keywords_by_app or {}
    mapper_queries_by_app = mapper_queries_by_app or {}
    db_probes = list(db_probes or [])
    db_expectations = list(db_expectations or [])
    db_probe_hints = list(db_probe_hints or [])
    db_probes_skipped = list(db_probes_skipped or [])
    mapper_queries_skipped = list(mapper_queries_skipped or [])
    db_apps_out_of_scope = list(db_apps_out_of_scope or [])
    investigation_apps = list(investigation_apps or apps)
    apps = [a for a in apps if a]
    by_app: dict[str, dict] = {}
    all_queries: list[dict] = []
    primary = apps[0] if apps else ""

    def _job(app: str) -> tuple[str, dict]:
        if app == primary:
            app_probes = [
                p for p in db_probes
                if not p.get("schema")
                or schema_to_app(p.get("schema") or "", investigation_apps) in (app, None)
            ]
            app_expectations = db_expectations
            hint = db_probe_hints
            skipped = db_probes_skipped
            note = db_probe_selection_note
            skipped_mapper = mapper_queries_skipped
        else:
            app_probes = [
                p for p in db_probes
                if schema_to_app(p.get("schema") or "", investigation_apps) == app
            ]
            app_expectations = []
            hint = []
            skipped = []
            note = ""
            skipped_mapper = []
        key = (biz_keys.get(app) or biz_key or "").strip()
        kind = biz_key_kinds.get(app) or biz_key_kinds.get("_default") or "loan_no"
        one = collect(
            app, env, key,
            repo_root=repo_roots.get(app),
            biz_key_kind=kind,
            keywords=keywords_by_app.get(app),
            mapper_queries=mapper_queries_by_app.get(app),
            db_probes=app_probes,
            db_expectations=app_expectations,
            db_probe_hints=hint,
            db_probes_skipped=skipped,
            db_probe_selection_note=note,
            mapper_queries_skipped=skipped_mapper,
        )
        return app, one

    if len(apps) <= 1:
        results = [_job(a) for a in apps]
    else:
        results = []
        workers = min(8, len(apps))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_job, a): a for a in apps}
            for fut in as_completed(futs):
                results.append(fut.result())
        order = {a: i for i, a in enumerate(apps)}
        results.sort(key=lambda x: order.get(x[0], 999))

    for app, one in results:
        by_app[app] = one
        for q in one.get("queries") or []:
            all_queries.append({"app": app, **q})
        # 收集预校验告警
        pre_warns = one.get("pre_validate_warnings") or []
        if pre_warns:
            for w in pre_warns:
                all_queries.append({
                    "app": app,
                    "file": w.get("label", "pre-validate"),
                    "sql": w.get("query_sql", ""),
                    "rows": [],
                    "count": 0,
                    "source": "pre_validate",
                    "executed": False,
                    "error": w.get("warning", ""),
                })

    host = next((x.get("db_host") for x in by_app.values() if x.get("db_host")), None)
    expectation_checks = next(
        (x.get("expectation_checks") for x in by_app.values() if x.get("expectation_checks")),
        [],
    )
    result = {
        "apps": apps,
        "investigation_apps": investigation_apps,
        "db_apps": apps,
        "db_apps_out_of_scope": db_apps_out_of_scope,
        "env": env,
        "biz_key": biz_key,
        "db_host": host,
        "by_app": by_app,
        "queries": all_queries,
        "db_probes": db_probes,
        "db_probe_hints": db_probe_hints,
        "db_probes_skipped": db_probes_skipped,
        "mapper_queries_skipped": mapper_queries_skipped,
        "db_probe_selection_note": db_probe_selection_note,
        "db_expectations": db_expectations,
        "expectation_checks": expectation_checks,
        "skipped": all(x.get("skipped") for x in by_app.values()) if by_app else True,
        "error": "; ".join(
            filter(None, [x.get("error") for x in by_app.values() if x.get("error")])
        ),
        "source": by_app.get(primary, {}).get("source") if primary else "none",
    }
    result = slim_database_block(result)
    if output:
        write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="issue-investigation DB 只读（probe + Mapper XML）")
    parser.add_argument("--app", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--biz-key", default="")
    parser.add_argument("--biz-key-kind", default="loan_no")
    parser.add_argument("--repo-root", help="业务代码仓根目录，用于扫描 Mapper XML")
    parser.add_argument("--keywords", help="逗号分隔，用于 Mapper 相关性排序")
    parser.add_argument("--probe", action="append", default=[], help="表.字段=值，可重复")
    parser.add_argument("--expect", action="append", default=[], help="表.字段=期望值，可重复")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()
    out = Path(args.output) if args.output else None
    repo = Path(args.repo_root).resolve() if args.repo_root else None
    kw = [k.strip() for k in (args.keywords or "").split(",") if k.strip()]
    from lib.db_probe import parse_probe_text

    probe_text = "\n".join(f"排查: {p}" for p in args.probe)
    expect_text = "\n".join(f"错误现象: {e}" for e in args.expect)
    probes, expectations = parse_probe_text(f"{probe_text}\n{expect_text}")
    result = collect(
        args.app, args.env, args.biz_key,
        repo_root=repo,
        biz_key_kind=args.biz_key_kind,
        keywords=kw or None,
        db_probes=probes,
        db_expectations=expectations,
        output=out,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
