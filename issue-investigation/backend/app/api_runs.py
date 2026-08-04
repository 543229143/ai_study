"""runs API：创建 / 列表 / 详情 / 消息发送（门禁+轮次+环境注入）/ 产物。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from . import config
from . import events, gate, pi_client, store
from .kernel_io import read_json, read_text
from .models import CreateRunRequest, SendMessageRequest

router = APIRouter(prefix="/runs", tags=["runs"])

_REJECT_MESSAGE = (
    "我只能帮你排查 dev/sit 环境的日志报错、落库异常、配置与数据问题。"
    "可以告诉我：环境（dev/sit）、主应用（lcs/goa/ams/lps）、traceId 或报错现象。"
)
_TURN_LIMIT_MESSAGE = "本轮排查已达 10 轮沟通上限，请新建会话继续排查。"


@router.post("")
async def create_run(req: CreateRunRequest):
    title = req.trace_id or (req.alert or "")[:20] or req.biz_key or "问题排查"
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
    })
    try:
        await pi_client.create_session(run["id"], run["env"])
        run = store.append_timeline(run["id"], "pi_session_ready", "Pi 会话已就绪")
    except Exception as exc:  # noqa: BLE001
        run = store.append_timeline(run["id"], "pi_session_error", f"Pi 会话创建失败: {exc}")
    return run


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

    history = await pi_client.get_messages(run_id)
    history_texts = [m.get("text", "") for m in history if m.get("role") in ("user", "assistant")]

    verdict = gate.gate_check(req.text, is_first=(run.get("message_count") or 0) == 0, history=history_texts)
    if not verdict["allow"]:
        await events.publish(run_id, {
            "type": "gate_rejected",
            "data": {"reason": verdict["reason"], "message": _REJECT_MESSAGE},
        })
        return {"status": "rejected", "reason": verdict["reason"]}

    store.update_run(run_id, {"message_count": (run.get("message_count") or 0) + 1, "env": env})
    store.append_timeline(run_id, "message_sent", req.text[:80])

    await events.publish(run_id, {"type": "user_message", "data": {"text": req.text}})

    try:
        await pi_client.send_message(run_id, req.text, env, history=history_texts)
    except Exception as exc:  # noqa: BLE001
        await events.publish(run_id, {"type": "error", "data": {"message": f"转发 Pi 失败: {exc}"}})
        raise HTTPException(502, f"Pi 转发失败: {exc}")
    return {"status": "accepted"}


@router.get("/{run_id}/messages")
async def get_messages(run_id: str):
    if store.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    try:
        return await pi_client.get_messages(run_id)
    except Exception:  # noqa: BLE001
        return []


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
