"""工具执行层：pi sidecar 通过 HTTP 调用，包装内核采集函数。

每个工具调用写入 runs/{run_id}/artifacts/{tool}-{seq}/ 独立子目录，中间产物全部保留。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, config_store
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


def _ordered_apps(run_id: str, apps: list[str]) -> list[str]:
    """扫描应用清单：命中配置的应用排序在前（优先），其余配置应用也扫描（不排除）。

    最终清单 = 命中优先应用 + 全部配置应用 + agent 自定义应用（若有）。
    """
    from . import store

    run = store.get_run(run_id)
    pri = [a for a in (run or {}).get("priority_apps") or [] if a]
    cfg_apps = config_store.app_names()
    extra = [a for a in (apps or []) if a not in cfg_apps and a not in pri]
    order = pri + [a for a in cfg_apps if a not in pri] + extra
    return order or list(cfg_apps) or (apps or [])


def collect_logs(run_id: str, seq: int, params: dict) -> dict:
    """ES 日志采集。params: env, app, mode, query/alert/biz, scope, apps[]

    apps[] 显式指定 = 真实采集清单（只采这些应用，对齐 skill refetch_logs 语义）；
    不传 apps 时按 scope：all=全部配置应用（默认广扫防漏），primary_only=仅主应用。
    """
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
    requested = params.get("apps")
    if requested:
        # 显式指定 → 真实过滤（对齐 skill refetch_logs 语义）；支持逗号字符串
        raw = requested if isinstance(requested, list) else str(requested).replace("，", ",").split(",")
        apps = list(dict.fromkeys(a.strip().lower() for a in raw if str(a).strip())) or [app]
    elif (params.get("scope") or "").strip().lower() == "primary_only":
        apps = [app]
    else:
        apps = _ordered_apps(run_id, [app])
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
        for e in es[:15]:
            msg = str(e.get("message") or e.get("log") or e.get("msg") or "")[:300]
            if not msg.strip():
                continue
            out.append({
                "ts": str(e.get("@timestamp") or e.get("timestamp") or "")[:23],
                "level": str(e.get("level") or e.get("log_level") or "")[:8],
                "message": msg,
            })
        return out

    ts_list = sorted(str(e.get("@timestamp") or e.get("timestamp") or "") for e in entries if e.get("@timestamp") or e.get("timestamp"))
    time_coverage = {
        "earliest": ts_list[0] if ts_list else None,
        "latest": ts_list[-1] if ts_list else None,
        "entries": len(entries),
    }

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
        "time_coverage": time_coverage,
        "time_window_expanded": bool(result.get("time_window_expanded")),
        "time_from": result.get("time_from"),
        "dual_query": bool(result.get("dual_query")),
        "log_collect_profile": result.get("log_collect_profile"),
        "kibana_urls": result.get("kibana_urls") or {},
        "artifact": str(out),
        "cost_seconds": round(time.time() - started, 1),
    }
    return summary


def scan_code(run_id: str, seq: int, params: dict) -> dict:
    """源码扫描（Java + Mapper XML + Spring 配置 + git 变更）。"""
    _ensure_kernel()
    from scan_code_context import scan_multi

    apps = _ordered_apps(run_id, params.get("apps") or [params.get("app") or "lps"])
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
    # 调用者反向搜索（谁调用了异常类/方法）与最近 git 变更——内核已算好，工具返回给 agent
    callers: list[dict] = []
    for app, one in (result.get("by_app") or {}).items():
        for c in (one.get("callers") or []):
            callers.append({"app": app, "keyword": c.get("keyword"), "callers": c.get("callers") or []})
    recent_changes = result.get("recent_changes") or []
    return {
        "apps": list(roots.keys()),
        "hit_count": len(hits),
        "apps_hit": sorted({h.get("app") for h in hits if h.get("app")}),
        "sample_hits": hits[:8],
        "callers": callers[:10],
        "recent_changes": recent_changes[:10],
        "mapper_xml_hits": sum(len((v.get("mapper_xml_hits") or [])) for v in (result.get("by_app") or {}).values()),
        "spring_config_hits": sum(len((v.get("spring_config_hits") or [])) for v in (result.get("by_app") or {}).values()),
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


def _apply_db_name_overrides(queries: list[dict], env: str) -> list[dict]:
    """应用配置的主 schema 覆盖（apps.json primary_schema > env-connections schemas > 应用名）。

    只重写 SQL 中的库限定名 `old_schema`.xxx → `primary_schema`.xxx；未配置时原样。
    """
    _ensure_kernel()
    from lib.env_config import get_schema_name

    out = []
    for q in queries:
        app = str(q.get("app") or "").lower()
        schema_cfg = config_store.primary_schema_of(app)
        sql = q.get("sql") or ""
        if schema_cfg and sql:
            try:
                schema = get_schema_name(env, app)
            except RuntimeError:
                schema = app
            sql = sql.replace(f"`{schema}`", f"`{schema_cfg}`")
        out.append({**q, "sql": sql})
    return out


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
    normalized = _apply_db_name_overrides(normalized, env)
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
            "available_columns": q.get("available_columns") or [],
        })
    return {
        "env": env,
        "query_count": len(rows),
        "queries": rows,
        "artifact": str(out),
        "cost_seconds": round(time.time() - started, 1),
    }


def read_artifact(run_id: str, seq: int, params: dict) -> dict:
    """读取当前 run 的中间产物（只读，限 artifacts/ 目录内）。params: path(相对路径), max_chars, offset（均按字符）"""
    _ensure_kernel()
    run_dir = config.RUNS_DIR / run_id
    artifacts_dir = run_dir / "artifacts"
    path = str(params.get("path") or "").strip().lstrip("/")
    if not path:
        return {"error": "path 必填（artifacts/ 下相对路径，如 collect_logs-001/logs.json）"}
    if ".." in path.split("/"):
        return {"error": "禁止路径穿越（..）"}

    target = (artifacts_dir / path).resolve()
    try:
        target.relative_to(artifacts_dir.resolve())
    except ValueError:
        return {"error": f"路径越界: {path}"}
    if not target.is_file():
        return {"error": f"文件不存在: {path}"}

    size = target.stat().st_size
    # 安全封顶：opencode 模型层工具输出按字节截断（~61KB），日志含中文（最多 3 字节/字符），
    # 超过 40000 字符必然被截断并触发模型降窗重试——写死上限让模型一次拿到安全结果
    MAX_ARTIFACT_CHARS = 40000
    max_chars = min(MAX_ARTIFACT_CHARS, max(1, int(params.get("max_chars") or 20000)))
    offset = max(0, int(params.get("offset") or 0))
    # 字符语义：读全量后按字符切片（避免按字节 seek 切坏多字节中文）
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        full = f.read()
    text = full[offset : offset + max_chars]
    return {
        "path": path,
        "file_size": size,
        "offset": offset,
        "max_chars": max_chars,
        "returned_chars": len(text),
        "total_chars": len(full),
        "truncated": offset + len(text) < len(full),
        "content": text,
    }


def run_investigation(run_id: str, seq: int, params: dict) -> dict:
    """一键全流水线：logs（ES+代码+Nacos）→（可选 db_plan）→ 报告 §1–§4。"""
    _ensure_kernel()
    from lib.agent_db_plan import save_agent_db_plan
    from inv_runner import run_collection

    env = params["env"]
    app = params.get("app") or "lps"
    mode = params.get("mode") or "trace_id"
    # 关键：query 兜底 biz_key/alert（与 collect_logs 对齐）——此前 biz_key 模式 query 为空导致空报告
    query = params.get("query") or params.get("trace_id") or params.get("biz_key") or params.get("alert") or ""
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
