"""runs API：创建 / 列表 / 详情 / 消息发送（门禁+轮次+环境注入）/ 产物。"""
from __future__ import annotations

import re

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import config
from . import config_store, events, gate, pi_client, store
from .kernel_io import read_json, read_text
from .models import CreateRunRequest, SendMessageRequest

router = APIRouter(prefix="/runs", tags=["runs"])

_REJECT_MESSAGE = (
    "我只能帮你排查日志报错、落库异常、配置与数据问题。"
    "可以这样告诉我：粘贴 32 位 traceId、报错/异常信息，或业务单号（借据号/订单号/申请号），越具体越好。"
)
_TURN_LIMIT_MESSAGE = "本轮排查已达 10 轮沟通上限，请新建会话继续排查。"


def detect_from_text(text: str, env: str, app: str | None) -> dict:
    """从用户文本自动识别排查参数（应用清单/业务键/术语来自 data/config/apps.json）。"""
    t = text.strip()
    app_names = config_store.app_names() or ["lps"]
    hits = config_store.detect_hits(t)
    out = {
        "mode": "trace_id",
        "trace_id": "",
        "alert": "",
        "biz_key": "",
        "app": (app or "").strip().lower(),
        "scope": "primary_only",
        "biz_hits": hits["biz_hits"],
        "priority_apps": config_store.priority_apps(hits),
    }
    if out["app"] not in app_names:
        # 主应用：用户显式词 > 业务键/术语命中 > 默认
        out["app"] = (
            hits["explicit_app"]
            or (hits["biz_hits"][0]["app"] if hits["biz_hits"] else "")
            or (hits["term_apps"][0] if hits["term_apps"] else "")
            or app_names[0]
        )
    hex32 = re.search(r"\b([a-f0-9]{32})\b", t, re.I)
    if hex32:
        out["mode"] = "trace_id"
        out["trace_id"] = hex32.group(1)
        return out
    if re.search(r"Exception|ERROR|报错|告警|异常|NullPointer|timeout", t, re.I):
        out["mode"] = "alert"
        out["alert"] = t
        return out
    # 业务键模式：借据/订单/申请号等
    out["mode"] = "biz_key"
    for pat in (
        r"(?:loan[_ ]?no|loanNo|借据)[:：=]?\s*([A-Za-z0-9_-]+)",
        r"(?:order[_ ]?no|orderNo|订单)[:：=]?\s*([A-Za-z0-9_-]+)",
        r"(?:appl[_ ]?no|applNo)[:：=]?\s*([A-Za-z0-9_-]+)",
        r"(?:apply[_ ]?no|applyNo)[:：=]?\s*([A-Za-z0-9_-]+)",
        r"\b((?:LN|CR|O|L)[A-Za-z0-9]{10,})\b",
    ):
        m = re.search(pat, t, re.I)
        if m:
            out["biz_key"] = m.group(1)
            break
    return out


@router.post("")
async def create_run(req: CreateRunRequest):
    if req.text:
        # 简化入口：从文本自动识别 mode / 查询值 / 主应用
        fields = detect_from_text(req.text, req.env, req.app)
        req.mode = req.mode or fields["mode"]
        req.trace_id = req.trace_id or fields["trace_id"]
        req.alert = req.alert or fields["alert"]
        req.biz_key = req.biz_key or fields["biz_key"]
        req.app = req.app or fields["app"]
        req.scope = req.scope or fields["scope"]
    title = (
        req.trace_id
        or (req.alert or "")[:20]
        or req.biz_key
        or ((req.text or "").strip()[:20])
        or "问题排查"
    )
    run = store.create_run({
        "title": title,
        "env": req.env,
        "app": req.app,
        "mode": req.mode,
        "trace_id": req.trace_id or "",
        "alert": req.alert or "",
        "biz_key": req.biz_key or "",
        "phenomenon": req.phenomenon or "",
        "scope": req.scope,
        "custom_apps": req.custom_apps or [],
        "biz_hits": fields.get("biz_hits") if req.text else [],
        "priority_apps": fields.get("priority_apps") if req.text else [],
    })
    # Pi 会话懒创建（sidecar 首次 prompt 时自动建），此处后台预热不阻塞返回
    await _warm_pi_session(run["id"], run["env"])
    return run


async def _warm_pi_session(run_id: str, env: str) -> None:
    """后台预热 pi 会话，失败不影响 run 创建（首次 prompt 时 sidecar 会再兜底）。"""
    import asyncio

    asyncio.create_task(_warm_pi_session_task(run_id, env))


async def _warm_pi_session_task(run_id: str, env: str) -> None:
    try:
        await pi_client.create_session(run_id, env)
        store.append_timeline(run_id, "pi_session_ready", "Pi 会话已就绪")
    except Exception as exc:  # noqa: BLE001
        store.append_timeline(run_id, "pi_session_warm_failed", f"Pi 会话预热失败（首次消息将自动重试）: {exc}")


@router.get("")
async def list_runs():
    return store.list_runs()


@router.get("/{run_id}")
async def get_run(run_id: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: SendMessageRequest):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")

    if not store.has_turn_quota(run):
        await events.publish(run_id, {"type": "turn_limit", "data": {"message": _TURN_LIMIT_MESSAGE}})
        raise HTTPException(429, _TURN_LIMIT_MESSAGE)

    env = req.env or run.get("env") or "dev"
    if env != run.get("env"):
        run = store.update_env(run_id, env)

    if not req.resume:
        # 正常发送：过门禁 + 计轮次
        history = await pi_client.get_messages(run_id)
        history_texts = [m.get("text", "") for m in history if m.get("role") in ("user", "assistant")]

        verdict = gate.gate_check(req.text, is_first=(run.get("message_count") or 0) == 0, history=history_texts)
        if not verdict["allow"]:
            # 持久化拦截记录（刷新/重开会话后仍可见），再推送实时事件
            store.append_rejected(run_id, req.text, _REJECT_MESSAGE)
            await events.publish(run_id, {
                "type": "gate_rejected",
                "data": {"reason": verdict["reason"], "message": _REJECT_MESSAGE},
            })
            return {"status": "rejected", "reason": verdict["reason"]}

        store.update_run(run_id, {"message_count": (run.get("message_count") or 0) + 1, "env": env})
        store.append_timeline(run_id, "message_sent", req.text[:80])

    # 标记进行中；done/error/abort 事件到达后清除
    store.set_pending(run_id, True)
    await events.publish(run_id, {"type": "user_message", "data": {"text": req.text}})

    # 识别提示注入：本条消息命中业务键/术语时，头部附加提示供 agent 生成查询/扫描计划
    text = req.text
    hits = config_store.detect_hits(text)
    hint = config_store.build_hint(hits)
    if hint:
        text = f"[识别提示: {hint}]\n\n{text}"

    try:
        await pi_client.send_message(run_id, text, env, history=history_texts if not req.resume else None)
    except Exception as exc:  # noqa: BLE001
        store.set_pending(run_id, False)
        await events.publish(run_id, {"type": "error", "data": {"message": f"转发 Pi 失败: {exc}"}})
        raise HTTPException(502, f"Pi 转发失败: {exc}")
    return {"status": "accepted"}


@router.get("/{run_id}/status")
async def get_run_status(run_id: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    status = await pi_client.get_session_status(run_id)
    return {
        "run_id": run_id,
        "pending": bool(run.get("pending")),
        "pending_since": run.get("pending_since"),
        "processing": bool(status.get("processing")),
        "sidecar_unreachable": bool(status.get("unreachable")),
    }


@router.post("/{run_id}/abort")
async def abort_run(run_id: str):
    if store.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    try:
        await pi_client.abort_session(run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"停止失败: {exc}")
    await events.publish(run_id, {"type": "user_aborted", "data": {}})
    store.append_timeline(run_id, "aborted", "用户停止排查")
    return {"ok": True}


@router.get("/{run_id}/cost")
async def get_cost(run_id: str):
    if store.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    try:
        cost = await pi_client.get_cost(run_id)
    except Exception:  # noqa: BLE001
        cost = 0.0
    return {"run_id": run_id, "cost": cost}


class SatisfactionRequest(BaseModel):
    stars: int
    reason: Optional[str] = ""
    forced: bool = False


@router.post("/{run_id}/satisfaction")
async def submit_satisfaction(run_id: str, req: SatisfactionRequest):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if not 1 <= req.stars <= 5:
        raise HTTPException(422, "stars 必须在 1-5")
    entry = store.save_satisfaction(
        run_id, req.stars, (req.reason or "").strip(),
        (run.get("message_count") or 0), req.forced,
    )
    # 回写结论快照的满意度（知识库用：问题→结论→评价 一条链）
    if run.get("conclusion"):
        run["conclusion"]["satisfaction"] = entry
        store.update_run(run_id, {"conclusion": run["conclusion"]})
    store.append_timeline(run_id, "satisfaction", f"满意度 {entry['stars']} 星")
    return {"ok": True, "satisfaction": entry}


@router.get("/{run_id}/satisfaction")
async def get_satisfaction(run_id: str):
    if store.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return store.get_satisfaction(run_id) or {}


@router.get("/{run_id}/messages")
async def get_messages(run_id: str):
    if store.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    # 合并：pi 会话消息 + 门禁拦截记录（按时间排序，用户/引导语完整可见）
    rejected = store.list_rejected(run_id)
    if not rejected:
        try:
            return await pi_client.get_messages(run_id)
        except Exception:  # noqa: BLE001
            return []
    try:
        pi_msgs = await pi_client.get_messages(run_id)
    except Exception:  # noqa: BLE001
        pi_msgs = []
    merged = pi_msgs + rejected
    merged.sort(key=lambda m: m.get("ts") or 0)
    return merged


@router.get("/{run_id}/report", response_class=PlainTextResponse)
async def get_report(run_id: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    artifacts = store.run_artifact_paths(run_id)
    if "investigation-report.md" not in artifacts:
        return "（暂无报告：尚未执行采集）"
    return read_text(artifacts["investigation-report.md"])


@router.get("/{run_id}/artifacts")
async def list_artifacts(run_id: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    base = store.run_dir(run_id)
    out = []
    for p in sorted((base / "artifacts").glob("*")) if (base / "artifacts").is_dir() else []:
        out.append({
            "name": p.name,
            "files": sorted(f.name for f in p.iterdir() if f.is_file()),
        })
    return out


@router.get("/{run_id}/artifact/{name:path}")
async def get_artifact(run_id: str, name: str):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    p = store.run_dir(run_id) / "artifacts" / name
    if not p.is_file():
        raise HTTPException(404, "artifact not found")
    if p.name.endswith(".json"):
        return read_json(p)
    return PlainTextResponse(read_text(p))
