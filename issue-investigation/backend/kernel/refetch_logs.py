"""增量补拉指定应用日志（分析阶段定位到单服务后使用）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from collect_logs import collect_multi
from lib.common import read_json, write_json, default_log_time_from
from lib.evidence_slim import slim_evidence
from lib.log_collect import LOG_SIZE_PER_APP, log_params_for_profile


def refetch_logs_for_apps(
    run_dir: Path,
    apps: list[str],
    *,
    focused: bool = True,
    merge_report: bool = True,
) -> dict:
    """
    对已有 run 补拉日志并合并进 evidence.json。
    focused=True：该服务 traceId 全级别最多 200 条；False：广扫偏 ERROR。
    """
    ctx = read_json(run_dir / "context.json")
    if not ctx:
        raise SystemExit(f"缺少 {run_dir / 'context.json'}")
    evidence = read_json(run_dir / "evidence.json", {})
    if not evidence:
        raise SystemExit(f"缺少 {run_dir / 'evidence.json'}，请先完成首轮采集")

    profile = "focused" if focused else "broad"
    params = log_params_for_profile(profile)
    env = ctx["env"]
    query = ctx["query"]
    query_mode = ctx.get("query_mode") or "trace_id"
    time_from = ctx.get("time_from") or default_log_time_from(query_mode)
    alert_phrases = ctx.get("alert_phrases") or []

    new_logs = collect_multi(
        apps,
        env,
        query,
        mode="es",
        time_from=time_from,
        size=params["log_size_per_app"],
        errors_only=params["log_errors_only"],
        error_guard_size=params.get("log_error_guard_size") or 50,
        query_mode=query_mode,
        alert_phrases=alert_phrases,
        log_collect_profile=profile,
    )

    old_logs = evidence.get("logs") or {}
    by_app = dict(old_logs.get("by_app") or {})
    refetched: list[str] = []
    for app in apps:
        if app in new_logs.get("by_app", {}):
            by_app[app] = new_logs["by_app"][app]
            refetched.append(app)

    merged: list[dict] = []
    for app, block in by_app.items():
        for e in block.get("entries") or []:
            row = dict(e)
            row["app"] = app
            merged.append(row)
    merged.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    guard = int(params.get("log_error_guard_size") or 50)
    per = int(params["log_size_per_app"]) + (0 if params["log_errors_only"] else guard)
    cap = per * max(len(by_app), 1)

    logs = {
        **old_logs,
        "by_app": by_app,
        "entries": merged[:cap],
        "total": len(merged),
        "refetched_apps": list(dict.fromkeys((old_logs.get("refetched_apps") or []) + refetched)),
        "last_refetch_at": datetime.now(timezone.utc).isoformat(),
        "last_refetch_profile": profile,
    }
    evidence["logs"] = logs
    write_json(run_dir / "logs.json", logs)
    write_json(run_dir / "evidence.json", slim_evidence(evidence))

    if merge_report and (run_dir / "investigation-report.md").is_file():
        from inv_runner import _render_report  # noqa: WPS433

        (run_dir / "investigation-report.md").write_text(
            _render_report(evidence), encoding="utf-8"
        )

    return {"refetched": refetched, "profile": profile, "by_app_counts": {a: len(by_app[a].get("entries") or []) for a in refetched}}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="补拉指定应用 traceId 日志并合并 evidence")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--apps", required=True, help="逗号分隔，如 lcs 或 lcs,goa")
    parser.add_argument(
        "--profile",
        choices=("focused", "broad"),
        default="focused",
        help="focused=全级别最多200条；broad=偏ERROR/Exception",
    )
    args = parser.parse_args()
    apps = [a.strip().lower() for a in args.apps.replace("，", ",").split(",") if a.strip()]
    result = refetch_logs_for_apps(
        Path(args.run_dir).resolve(),
        apps,
        focused=(args.profile == "focused"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
