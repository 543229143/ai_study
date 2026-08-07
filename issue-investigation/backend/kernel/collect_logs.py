#!/usr/bin/env python3
"""
日志采集：ES 自动查询 + Kibana 深链。

  python3 collect_logs.py --app lps --env sit --query <traceId>
  python3 collect_logs.py --app lps --env dev --query <traceId> --mode es
  python3 collect_logs.py --app lps --env sit --query <traceId> --mode link
  python3 collect_logs.py --app lps --env sit --query <traceId> --mode both  # 默认
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.common import (  # noqa: E402
    assert_app_supported,
    assert_env_supported,
    default_log_time_from,
    LOG_TIME_FROM_TRACE_ID,
    write_json,
)
from lib.deps import ensure_requests  # noqa: E402
from lib.env_config import get_logs_config  # noqa: E402
from lib.kibana_link import build_discover_url  # noqa: E402


def _expand_time_window(time_from: str, query_mode: str) -> str | None:
    """当 ES 返回 0 条时，自动扩大时间窗口重试。返回新的 time_from 或 None。"""
    mode = (query_mode or "").strip().lower()
    if mode == "alert":
        # 24h → 72h
        if time_from == "now-24h":
            return "now-72h"
    elif mode == "trace_id":
        # 3d → 7d
        if time_from == "now-3d":
            return "now-7d"
    elif mode == "biz_key":
        # 7d → 30d
        if time_from == "now-7d":
            return "now-30d"
    return None


def _es_search(
    es_host: str,
    user: str,
    password: str,
    index_pattern: str,
    namespace: str,
    container: str,
    query_text: str,
    time_from: str,
    size: int,
    errors_only: bool,
    *,
    query_mode: str = "trace_id",
    alert_phrases: list[str] | None = None,
) -> dict:
    requests_lib = ensure_requests()

    url = f"{es_host.rstrip('/')}/{index_pattern}/_search"
    # 测试集群 mapping 无 .keyword 子字段，默认用原字段 term 过滤
    filters: list[dict] = [
        {"term": {"k8s_pod_namespace": namespace}},
        {"term": {"docker_container": container}},
    ]
    if time_from:
        filters.append({"range": {"@timestamp": {"gte": time_from}}})

    must: list[dict] = []
    # traceId 精确匹配用 match_phrase（比 simple_query_string 省去语法解析开销）；
    # 如果 ES mapping 有 .keyword 子字段则用 term 更快，但测试集群无，故 match_phrase
    if query_mode == "trace_id":
        must.append({"match_phrase": {"message": query_text}})
    elif query_mode == "alert" and alert_phrases:
        should = [{"match_phrase": {"message": p}} for p in alert_phrases[:6] if p]
        if query_text and query_text not in alert_phrases:
            should.append({"match_phrase": {"message": query_text}})
        must.append({"bool": {"should": should, "minimum_should_match": 1}})
    else:
        must.append(
            {
                "simple_query_string": {
                    "query": query_text,
                    "fields": ["message", "log", "msg"],
                    "default_operator": "and",
                }
            }
        )
    if errors_only and query_mode != "alert":
        must.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"message": " ERROR "}},
                        {"match_phrase": {"message": "ERROR "}},
                        {"match_phrase": {"message": "Exception"}},
                        {"term": {"level": "ERROR"}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    body = {
        "size": size,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "filter": filters,
                "must": must,
            }
        },
        "_source": ["@timestamp", "docker_container", "message", "level", "k8s_pod_namespace"],
    }

    auth = (user, password) if user else None
    resp = requests_lib.post(url, json=body, auth=auth, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    # 检查 ES 返回的 error 字段（HTTP 200 但查询层面失败）
    if isinstance(result, dict) and result.get("error"):
        err_info = result["error"]
        reason = err_info.get("reason", str(err_info)) if isinstance(err_info, dict) else str(err_info)
        raise RuntimeError(f"ES 查询错误: {reason}")
    # 检查 shard 级别失败
    shards = (result.get("_shards") or {}) if isinstance(result, dict) else {}
    if shards.get("failed", 0) > 0:
        failures = shards.get("failures") or []
        detail = "; ".join(f.get("reason", {}).get("reason", str(f)) for f in failures[:3])
        raise RuntimeError(f"ES shard 失败 ({shards['failed']}/{shards.get('total', '?')}): {detail}")
    return result


def _normalize_hits(es_result: dict) -> list[dict]:
    hits = es_result.get("hits", {}).get("hits", [])
    rows = []
    for h in hits:
        src = h.get("_source", {})
        rows.append(
            {
                "timestamp": src.get("@timestamp"),
                "container": src.get("docker_container"),
                "namespace": src.get("k8s_pod_namespace"),
                "level": src.get("level"),
                "message": src.get("message") or src.get("log") or src.get("msg") or "",
                "_id": h.get("_id"),
            }
        )
    return rows


def _entry_dedupe_key(row: dict) -> str:
    eid = (row.get("_id") or "").strip()
    if eid:
        return f"id:{eid}"
    msg = (row.get("message") or "")[:240]
    return f"{row.get('timestamp') or ''}|{msg}"


def _merge_log_entries(*groups: list[dict]) -> list[dict]:
    """多路查询结果合并去重，按 @timestamp 降序。"""
    seen: set[str] = set()
    out: list[dict] = []
    for group in groups:
        for row in group or []:
            key = _entry_dedupe_key(row)
            if key in seen:
                continue
            seen.add(key)
            clean = {k: v for k, v in row.items() if k != "_id"}
            out.append(clean)
    out.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return out


def _es_total(raw: dict, fallback: int) -> int:
    total = raw.get("hits", {}).get("total", {})
    if isinstance(total, dict):
        return int(total.get("value", fallback))
    try:
        return int(total)
    except (TypeError, ValueError):
        return fallback


def collect(
    app: str,
    env: str,
    query: str,
    *,
    mode: str = "both",
    time_from: str = LOG_TIME_FROM_TRACE_ID,
    time_to: str = "now",
    size: int = 500,
    errors_only: bool = True,
    error_guard_size: int = 50,
    query_mode: str = "trace_id",
    alert_phrases: list[str] | None = None,
    allow_time_expand: bool = True,
    output: Path | None = None,
) -> dict:
    env = assert_env_supported(env)
    app_cfg = assert_app_supported(app)
    logs_cfg = get_logs_config(env)
    namespace = logs_cfg["k8s_namespace"]
    container = app_cfg.get("container") or f"{app}-service"
    index = logs_cfg.get("index") or "filebeat"

    kibana_base = logs_cfg.get("kibana_base_url") or "http://kibana-test.xurongwl.com"
    kibana_url = build_discover_url(
        kibana_base,
        index=index,
        namespace=namespace,
        container=container,
        query=query,
        time_from=time_from,
        time_to=time_to,
    )

    result: dict = {
        "app": app,
        "env": env,
        "namespace": namespace,
        "query": query,
        "query_mode": query_mode,
        "alert_phrases": alert_phrases or [],
        "time_from": time_from,
        "mode": mode,
        "kibana_url": kibana_url,
        "entries": [],
        "total": 0,
        "es_error": None,
        "dual_query": False,
        "error_guard_count": 0,
        "context_count": 0,
    }

    # alert 模式本身已按异常短语检索，不再二次过滤 ERROR
    es_errors_only = errors_only if query_mode != "alert" else False
    # focused（全级别）默认双查：异常保底 + 全级别上下文；broad（已 errors_only）单查即可
    use_dual = (not es_errors_only) and query_mode != "alert"
    guard_size = max(1, int(error_guard_size or 50))

    if mode in ("es", "both"):
        es_host = (logs_cfg.get("es_host") or "").strip()
        es_user = logs_cfg.get("es_user") or ""
        es_password = logs_cfg.get("es_password") or ""
        index_pattern = logs_cfg.get("index_pattern") or "filebeat-*"
        if not es_host:
            result["es_error"] = (
                f"未填写 env-connections.json → {env}.logs.es_host，跳过 ES 查询；"
                "仍可使用 kibana_url 人工复核"
            )
        else:
            def _run_at(tf: str) -> tuple[list[dict], int, dict]:
                """返回 (entries, total_hint, meta)。"""
                if use_dual:
                    raw_err = _es_search(
                        es_host, es_user, es_password, index_pattern,
                        namespace, container, query, tf, guard_size, True,
                        query_mode=query_mode, alert_phrases=alert_phrases,
                    )
                    raw_all = _es_search(
                        es_host, es_user, es_password, index_pattern,
                        namespace, container, query, tf, size, False,
                        query_mode=query_mode, alert_phrases=alert_phrases,
                    )
                    err_rows = _normalize_hits(raw_err)
                    all_rows = _normalize_hits(raw_all)
                    merged = _merge_log_entries(err_rows, all_rows)
                    meta = {
                        "dual_query": True,
                        "error_guard_count": len(err_rows),
                        "context_count": len(all_rows),
                        "error_guard_size": guard_size,
                    }
                    total_hint = max(
                        _es_total(raw_err, len(err_rows)),
                        _es_total(raw_all, len(all_rows)),
                        len(merged),
                    )
                    return merged, total_hint, meta
                raw = _es_search(
                    es_host, es_user, es_password, index_pattern,
                    namespace, container, query, tf, size, es_errors_only,
                    query_mode=query_mode, alert_phrases=alert_phrases,
                )
                rows = _normalize_hits(raw)
                for r in rows:
                    r.pop("_id", None)
                return rows, _es_total(raw, len(rows)), {"dual_query": False}

            try:
                entries, total_hint, meta = _run_at(time_from)
                result["entries"] = entries
                result["total"] = total_hint
                result.update(meta)
                if allow_time_expand and not result["entries"]:
                    expanded = _expand_time_window(time_from, query_mode)
                    if expanded and expanded != time_from:
                        entries2, total2, meta2 = _run_at(expanded)
                        if entries2:
                            result["entries"] = entries2
                            result["total"] = total2
                            result.update(meta2)
                            result["time_from"] = expanded
                            result["time_window_expanded"] = True
            except Exception as exc:
                result["es_error"] = str(exc)

    if output:
        write_json(output, result)
    return result


def collect_multi(
    apps: list[str],
    env: str,
    query: str,
    *,
    mode: str = "both",
    time_from: str = LOG_TIME_FROM_TRACE_ID,
    time_to: str = "now",
    size: int = 500,
    errors_only: bool = True,
    error_guard_size: int = 50,
    query_mode: str = "trace_id",
    alert_phrases: list[str] | None = None,
    output: Path | None = None,
    log_collect_profile: str = "",
    primary_app: str = "",
) -> dict:
    """多应用日志：各 container 并行查 ES（默认 Top 500），再合并时间线。

    focused（errors_only=False）时每应用默认双查：异常保底 + 全级别上下文。

    时间窗扩窗策略：
    - 第一轮各应用均不扩窗（并行一次）。
    - 仅当主应用（或全部）0 条时，再对需要扩窗的应用重试；避免「主应用已命中、关联应用 0 条」时无意义的二次 ES。
    - trace_id：扩窗仅作用于 0 条应用，且优先主应用（trace 唯一，错 namespace 时扩窗通常无用）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    apps = [a for a in apps if a]
    primary = (primary_app or (apps[0] if apps else "")).strip().lower()
    by_app: dict[str, dict] = {}
    merged: list[dict] = []
    kibana_urls: dict[str, str] = {}
    guard = max(1, int(error_guard_size or 50))

    def _one(app: str, *, expand: bool) -> tuple[str, dict]:
        return app, collect(
            app, env, query, mode=mode, time_from=time_from, time_to=time_to,
            size=size, errors_only=errors_only, error_guard_size=guard,
            query_mode=query_mode, alert_phrases=alert_phrases, allow_time_expand=expand,
        )

    def _run_parallel(targets: list[str], *, expand: bool) -> list[tuple[str, dict]]:
        if not targets:
            return []
        if len(targets) <= 1:
            return [_one(a, expand=expand) for a in targets]
        results: list[tuple[str, dict]] = []
        workers = min(8, max(1, len(targets)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_one, a, expand=expand): a for a in targets}
            for fut in as_completed(futs):
                results.append(fut.result())
        order = {a: i for i, a in enumerate(targets)}
        results.sort(key=lambda x: order.get(x[0], 999))
        return results

    # 第一轮：全部应用，不扩窗
    for app, one in _run_parallel(apps, expand=False):
        by_app[app] = one

    # 第二轮：按策略决定是否扩窗重试
    expanded_tf = _expand_time_window(time_from, query_mode)
    primary_hits = len((by_app.get(primary) or {}).get("entries") or []) if primary else 0
    any_hits = any(len((by_app.get(a) or {}).get("entries") or []) > 0 for a in apps)

    retry_apps: list[str] = []
    if expanded_tf and expanded_tf != time_from:
        qmode = (query_mode or "").strip().lower()
        if qmode == "trace_id":
            if primary_hits == 0:
                retry_apps = [primary] if primary in by_app else [
                    a for a in apps if not (by_app.get(a) or {}).get("entries")
                ]
        else:
            if not any_hits:
                retry_apps = list(apps)
            else:
                retry_apps = [
                    a for a in apps
                    if not (by_app.get(a) or {}).get("entries")
                ]

    if retry_apps:
        for app, one in _run_parallel(retry_apps, expand=True):
            if one.get("entries") or one.get("time_window_expanded"):
                by_app[app] = one

    # 按入参 apps 顺序落盘
    order = {a: i for i, a in enumerate(apps)}
    for app in sorted(by_app.keys(), key=lambda a: order.get(a, 999)):
        one = by_app[app]
        if one.get("kibana_url"):
            kibana_urls[app] = one["kibana_url"]
        for e in one.get("entries") or []:
            row = dict(e)
            row["app"] = app
            merged.append(row)
    merged.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    # focused 双查每应用最多 size+guard；broad 仍为 size
    per_app_cap = size + (0 if errors_only else guard)
    merge_cap = per_app_cap * max(len(apps), 1)
    any_expanded = any(v.get("time_window_expanded") for v in by_app.values())
    effective_from = time_from
    for v in by_app.values():
        if v.get("time_window_expanded") and v.get("time_from"):
            effective_from = v["time_from"]
            break
    result = {
        "apps": apps,
        "env": env,
        "query": query,
        "query_mode": query_mode,
        "time_from": effective_from if any_expanded else time_from,
        "mode": mode,
        "log_collect_profile": log_collect_profile or ("broad" if len(apps) > 1 and errors_only else "focused"),
        "log_size_per_app": size,
        "log_error_guard_size": guard,
        "log_errors_only": errors_only,
        "dual_query": (not errors_only) and any(v.get("dual_query") for v in by_app.values()),
        "time_window_expanded": any_expanded,
        "by_app": by_app,
        "kibana_urls": kibana_urls,
        "kibana_url": kibana_urls.get(apps[0]) if apps else "",
        "entries": merged[:merge_cap],
        "total": len(merged),
    }
    if output:
        write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="issue-investigation 日志采集")
    parser.add_argument("--app", required=True, help="lps/lcs/goa/ams")
    parser.add_argument("--env", required=True, help="dev 或 sit（生产禁止）")
    parser.add_argument("--query", required=True, help="traceId / orderNo / 关键词")
    parser.add_argument(
        "--mode",
        choices=("es", "link", "both"),
        default="both",
        help="es=仅ES; link=仅Kibana链接; both=ES+链接",
    )
    parser.add_argument("--from-time", default=LOG_TIME_FROM_TRACE_ID, dest="time_from")
    parser.add_argument("--to-time", default="now", dest="time_to")
    parser.add_argument("--size", type=int, default=500)
    parser.add_argument(
        "--error-guard-size",
        type=int,
        default=50,
        help="focused 双查时异常保底条数（默认 50）",
    )
    parser.add_argument("--all-levels", action="store_true", help="不过滤 ERROR（启用双查）")
    parser.add_argument("--output", "-o", help="写入 JSON 文件")
    args = parser.parse_args()

    out = Path(args.output) if args.output else None
    result = collect(
        args.app,
        args.env,
        args.query,
        mode=args.mode,
        time_from=args.time_from,
        time_to=args.time_to,
        size=args.size,
        errors_only=not args.all_levels,
        error_guard_size=args.error_guard_size,
        output=out,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
