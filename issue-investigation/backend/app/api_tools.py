"""工具端点（pi sidecar 回调执行内核）+ 事件接收端点。"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from . import config
from . import events, store
from . import tools_exec

router = APIRouter(tags=["tools"])

_TOOL_SEQ: dict[str, int] = {}


def _check_token(x_token: str | None) -> None:
    if not config.PI_TOOL_TOKEN:
        return
    if x_token != config.PI_TOOL_TOKEN:
        raise HTTPException(401, "invalid token")


def _next_seq(run_id: str, tool: str) -> int:
    key = f"{run_id}/{tool}"
    _TOOL_SEQ[key] = _TOOL_SEQ.get(key, 0) + 1
    return _TOOL_SEQ[key]


@router.post("/tools/{tool_name}")
async def run_tool(tool_name: str, body: dict, x_tool_token: str | None = Header(default=None)):
    _check_token(x_tool_token)
    run_id = str(body.get("run_id") or "system")
    params = body.get("params") or {}
    env = str(body.get("env") or params.get("env") or "dev")

    if store.get_run(run_id) is None and run_id != "system":
        raise HTTPException(404, "run not found")

    tool = getattr(tools_exec, tool_name, None)
    if tool is None:
        raise HTTPException(404, f"unknown tool: {tool_name}")

    seq = _next_seq(run_id, tool_name)
    await events.publish(run_id, {
        "type": "tool_start",
        "data": {"tool": tool_name, "params": params},
    })
    try:
        result = await _run_in_executor(tool, run_id, seq, params)
        await events.publish(run_id, {
            "type": "tool_end",
            "data": {"tool": tool_name, "result": result},
        })
        return result
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        await events.publish(run_id, {"type": "tool_error", "data": {"tool": tool_name, "error": msg}})
        raise HTTPException(500, msg)


async def _run_in_executor(tool, run_id: str, seq: int, params: dict):
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: tool(run_id, seq, params))


@router.post("/events/{run_id}")
async def post_event(run_id: str, body: dict, x_tool_token: str | None = Header(default=None)):
    """pi sidecar 推送会话事件（text_delta / thinking / done / error）。"""
    _check_token(x_tool_token)
    await events.publish(run_id, body)
    return {"ok": True}


@router.get("/envs")
async def list_envs():
    return {"envs": ["dev", "sit"]}
