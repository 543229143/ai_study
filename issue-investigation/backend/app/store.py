"""run 存储：runs/{run_id}/ 目录 + run.json 状态机，纯文件无数据库。"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .kernel_io import read_json, write_json

_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")

ARTIFACT_NAMES = (
    "investigation-report.md",
    "evidence.json",
    "receipt.json",
    "agent_db_plan.json",
    "context.json",
    "logs.json",
    "nacos.json",
    "db.json",
)


def now_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def run_dir(run_id: str) -> Path:
    return config.RUNS_DIR / run_id


def create_run(meta: dict) -> dict:
    rid = now_run_id()
    d = run_dir(rid)
    d.mkdir(parents=True, exist_ok=False)
    now = time.time()
    run = {
        "id": rid,
        "title": meta.get("title") or "问题排查",
        "env": meta.get("env", "dev"),
        "app": meta.get("app", "lps"),
        "mode": meta.get("mode", "trace_id"),
        "trace_id": meta.get("trace_id") or "",
        "alert": meta.get("alert") or "",
        "biz_key": meta.get("biz_key") or "",
        "phenomenon": meta.get("phenomenon") or "",
        "scope": meta.get("scope", "primary_only"),
        "custom_apps": meta.get("custom_apps") or [],
        "biz_hits": meta.get("biz_hits") or [],
        "priority_apps": meta.get("priority_apps") or [],
        "status": "created",
        "message_count": 0,
        "turn_limit": config.TURN_LIMIT,
        "pending": False,           # 是否有进行中的排查（转发消息后置 True，done/error/abort 后置 False）
        "pending_since": None,      # 置 pending 的时间戳
        "pi_session_id": "",
        "created_at": now,
        "updated_at": now,
        "timeline": [{"t": now, "event": "created", "detail": "会话创建"}],
    }
    write_json(d / "run.json", run)
    return run


def get_run(run_id: str) -> dict | None:
    p = run_dir(run_id) / "run.json"
    if not p.is_file():
        return None
    return read_json(p)


def update_run(run_id: str, patch: dict) -> dict:
    run = get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    run.update(patch)
    run["updated_at"] = time.time()
    write_json(run_dir(run_id) / "run.json", run)
    return run


def append_timeline(run_id: str, event: str, detail: str = "") -> dict:
    run = get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    run.setdefault("timeline", []).append(
        {"t": time.time(), "event": event, "detail": detail}
    )
    run["updated_at"] = time.time()
    write_json(run_dir(run_id) / "run.json", run)
    return run


def list_runs() -> list[dict]:
    out = []
    for d in sorted(config.RUNS_DIR.iterdir(), reverse=True):
        if not d.is_dir() or not _RUN_ID_RE.match(d.name):
            continue
        run = read_json(d / "run.json")
        if run:
            out.append(run)
    return out


def run_artifact_paths(run_id: str) -> dict[str, Path]:
    """已存在的产物路径（绝对路径）。"""
    d = run_dir(run_id)
    return {
        name: d / name
        for name in ARTIFACT_NAMES
        if (d / name).is_file()
    }


def update_env(run_id: str, env: str) -> dict:
    append_timeline(run_id, "env_switched", f"切换环境 → {env}")
    return update_run(run_id, {"env": env})


def has_turn_quota(run: dict) -> bool:
    return (run.get("message_count") or 0) < (run.get("turn_limit") or config.TURN_LIMIT)


def set_pending(run_id: str, pending: bool) -> None:
    """标记 run 是否有进行中的排查（转发消息置 True；done/error/abort 置 False）。"""
    run = get_run(run_id)
    if run is None:
        return
    patch = {"pending": pending}
    if pending:
        patch["pending_since"] = time.time()
    else:
        patch["pending_since"] = None
    update_run(run_id, patch)


def rejected_path(run_id: str) -> Path:
    return run_dir(run_id) / "rejected.json"


def list_rejected(run_id: str) -> list[dict]:
    """门禁拦截的对话记录（持久化，刷新后仍可见）。"""
    data = read_json(rejected_path(run_id), [])
    return data if isinstance(data, list) else []


def append_rejected(run_id: str, user_text: str, reply: str) -> None:
    """记录一次门禁拦截：用户原话 + 引导语，按时间排序与正常消息合并展示。"""
    now_ms = int(time.time() * 1000)
    entries = list_rejected(run_id)
    entries.append({"role": "user", "text": user_text, "ts": now_ms})
    entries.append({"role": "assistant", "text": reply, "ts": now_ms + 1})
    write_json(rejected_path(run_id), entries)


def satisfaction_path(run_id: str) -> Path:
    return run_dir(run_id) / "satisfaction.json"


def get_satisfaction(run_id: str) -> dict | None:
    """读取满意度评价（run 级单次）。"""
    data = read_json(satisfaction_path(run_id), None)
    return data if isinstance(data, dict) else None


def save_satisfaction(run_id: str, stars: int, reason: str, round_n: int, forced: bool = False) -> dict:
    """保存满意度评价（覆盖写，同一 run 只保留最新一次）。"""
    entry = {
        "stars": stars,
        "reason": reason,
        "round": round_n,
        "forced": forced,
        "ts": time.time(),
    }
    write_json(satisfaction_path(run_id), entry)
    return entry
