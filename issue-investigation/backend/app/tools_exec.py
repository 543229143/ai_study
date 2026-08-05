"""工具执行层：pi sidecar 通过 HTTP 调用，包装内核采集函数。

每个工具调用写入 runs/{run_id}/artifacts/{tool}-{seq}/ 独立子目录，中间产物全部保留。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .kernel_io import write_json

_kernel_ready = False


def _ensure_kernel():
    global _kernel_ready
    if _kernel_ready:
        return
    config.ensure_kernel_on_path()
    _kernel_ready = True


def _artifact_dir(run_id: str, tool: str, seq: int) -> Path:
    d = config.RUNS_DIR / run_id / "artifacts" / f"{tool}-{seq:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _repo_roots(apps: list[str]) -> dict[str, Path]:
    from lib.workspace import resolve_repo_roots

    roots = resolve_repo_roots(config.KERNEL_REPO_ROOT, apps)
    return {a: Path(p) for a, p in roots.items()}


def collect_logs(run_id: str, seq: int, params: dict) -> dict:
    """ES 日志采集。params: env, app, mode, query/alert/biz, scope, apps[]"""
    _ensure_kernel()
    from lib.common import default_log_time_from
    from collect_logs import collect_multi

    env = params["env"]
    app = params.get("app") or "lps"
    mode = params.get("mode") or "trace_id"
    query = params.get("query") or params.get("trace_id") or ""
    alert = params.get("alert") or ""
    biz = params.get("biz_key") or ""
    # 关键修复：biz_key/alert 模式必须把值接进 ES 查询，否则空串必 0 命中
    if not query:
        query = biz or alert or ""
    time_from = params.get("time_from") or default_log_time_from(mode)
    apps = params.get("apps") or [app]
    out = _artifact_dir(run_id, "collect_logs", seq) / "logs.json"

    started = time.time()
    result = collect_multi(
        apps, env, query,
        mode="both",
        time_from=time_from,
        errors_only=False,
        query_mode=mode,
        alert_phrases=[alert] if alert else None,
        output=out,
        primary_app=app,
    )
    entries = result.get("entries") or []
    by_app = result.get("by_app") or {}

    def _sample(es: list) -> list:
        out = []
        for e in es[:8]:
            msg = str(e.get("message") or e.get("log") or e.get("msg") or "")[:300]
            if not msg.strip():
                continue
            out.append({
                "ts": str(e.get("@timestamp") or e.get("timestamp") or "")[:23],
                "level": str(e.get("level") or e.get("log_level") or "")[:8],
                "message": msg,
            })
        return out

    summary = {
        "env": env,
        "apps": apps,
        "total_entries": len(entries),
        "by_app": {
            a: {
                "count": len((b.get("entries") or [])),
                "error_count": b.get("error_count") or 0,
            }
            for a, b in by_app.items()
        },
        "sample_entries": _sample(entries),
        "sample_by_app": {a: _sample(b.get("entries") or []) for a, b in by_app.items()},
        "kibana_urls": result.get("kibana_urls") or {},
        "artifact": str(out),
        "cost_seconds": round(time.time() - started, 1),
    }
    return summary


def scan_code(run_id: str, seq: int, params: dict) -> dict:
    """源码扫描（Java + Mapper XML + Spring 配置 + git 变更）。"""
    _ensure_kernel()
    from scan_code_context import scan_multi

    apps = params.get("apps") or [params.get("app") or "lps"]
    keywords = params.get("keywords") or []
    log_messages = params.get("log_messages") or None
    out = _artifact_dir(run_id, "scan_code", seq) / "scan.json"

    roots = _repo_roots(apps)
    started = time.time()
    result = scan_multi(
        roots,
        log_messages=log_messages,
        keywords=keywords or None,
        output=out,
    )
    hits = result.get("merged_hits") or []
    return {
        "apps": list(roots.keys()),
        "hit_count": len(hits),
        "apps_hit": sorted({h.get("app") for h in hits if h.get("app")}),
        "sample_hits": hits[:8],
        "artifact": str(out),
        "cost_seconds": round(time.time() - started, 1),
    }


def nacos_query(run_id: str, seq: int, params: dict) -> dict:
    """Nacos 指定 key 查询。params: env, app, keys[]"""
    _ensure_kernel()
    from collect_nacos import collect_multi

    env = params["env"]
    apps = params.get("apps") or [params.get("app") or "lps"]
    keys = params.get("keys") or []
    out = _artifact_dir(run_id, "nacos_query", seq) / "nacos.json"

    roots = _repo_roots(apps)
    started = time.time()
    result = collect_multi(apps, env, repo_roots=roots, keys=keys or None, output=out)
    by_app = result.get("by_app") or {}
    return {
        "env": env,
        "apps": apps,
        "keys": keys,
        "by_app": {
            a: {
                "found": list(b.get("configs") or {}),
                "configs": b.get("configs") or {},
            }
            for a, b in by_app.items()
        },
        "artifact": str(out),
        "cost_seconds": round(time.time() - started, 1),
    }


def db_query(run_id: str, seq: int, params: dict) -> dict:
    """只读 DB 查询。params: env, plan(json)，plan 结构同 agent_db_plan.json。"""
    _ensure_kernel()
    from lib.agent_db_plan import save_agent_db_plan, validate_and_normalize_plan
    from inv_runner import run_collection

    env = params["env"]
    plan = params.get("plan") or {}
    out = _artifact_dir(run_id, "db_query", seq)
    if not plan or plan.get("need_db") is False:
        return {"need_db": False, "note": "无需查库"}

    normalized, plan_meta = validate_and_normalize_plan(plan, env=env)
    save_agent_db_plan(out, {
        "source": plan_meta.get("source") or "agent",
        "need_db": bool(normalized),
        "reason": plan_meta.get("reason") or "",
        "queries": normalized,
    })

    ctx = {
        "env": env,
        "app": params.get("app") or "lps",
        "query": params.get("query") or "",
        "query_mode": params.get("mode") or "trace_id",
        "scope": "primary_only",
        "scenario": "default",
    }
    # 内核 db 阶段要求 run_dir 已有 evidence.json（含 context），此处补最小骨架
    write_json(out / "evidence.json", {"context": ctx})
    started = time.time()
    evidence = run_collection(config.KERNEL_REPO_ROOT, ctx, out, phase="db")
    db = evidence.get("database") or {}
    queries = db.get("queries") or []
    rows = []
    for q in queries:
        rows.append({
            "app": q.get("app"),
            "table": q.get("table"),
            "sql": q.get("sql"),
            "row_count": len(q.get("rows") or []),
            "error": q.get("error"),
            "rows": (q.get("rows") or [])[:5],
        })
    return {
        "env": env,
        "query_count": len(rows),
        "queries": rows,
        "artifact": str(out),
        "cost_seconds": round(time.time() - started, 1),
    }


def run_investigation(run_id: str, seq: int, params: dict) -> dict:
    """一键全流水线：logs（ES+代码+Nacos）→（可选 db_plan）→ 报告 §1–§4。"""
    _ensure_kernel()
    from lib.agent_db_plan import save_agent_db_plan
    from inv_runner import run_collection

    env = params["env"]
    app = params.get("app") or "lps"
    mode = params.get("mode") or "trace_id"
    query = params.get("query") or params.get("trace_id") or ""
    scope = params.get("scope") or "primary_only"
    out = _artifact_dir(run_id, "run_investigation", seq)

    ctx = {
        "env": env,
        "app": app,
        "query": query,
        "query_mode": mode,
        "scope": scope,
        "scenario": "default",
    }
    for k in ("alert", "biz_key", "phenomenon"):
        if params.get(k):
            ctx[k] = params[k]
    db_plan = params.get("db_plan")
    if isinstance(db_plan, dict) and db_plan.get("need_db") is not False:
        save_agent_db_plan(out, db_plan)

    started = time.time()
    evidence = run_collection(config.KERNEL_REPO_ROOT, ctx, out, phase="all")
    report_path = out / "investigation-report.md"
    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    return {
        "env": env,
        "apps": evidence.get("context", {}).get("apps"),
        "report_md": report_text[:12000],
        "report_path": str(report_path),
        "evidence_path": str(out / "evidence.json"),
        "cost_seconds": round(time.time() - started, 1),
    }
