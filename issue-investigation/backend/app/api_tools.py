"""工具端点（agent sidecar 回调执行内核）+ 事件接收端点。"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from . import config
from . import events, store
from . import tools_exec
from .kernel_io import sanitize

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
        # 清洗（DB 行可能含 datetime/Decimal），防止事件推送/响应序列化崩溃
        result = sanitize(result)
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
    """agent sidecar 推送会话事件（支持单条或批量 {events: [...]}）。"""
    _check_token(x_tool_token)
    batch = body.get("events")
    if isinstance(batch, list):
        for ev in batch:
            if isinstance(ev, dict):
                await events.publish(run_id, ev)
                if ev.get("type") in ("done", "error"):
                    store.set_pending(run_id, False)
        if any(ev.get("type") == "done" for ev in batch if isinstance(ev, dict)):
            await _snapshot_conclusion(run_id)
    else:
        await events.publish(run_id, body)
        if body.get("type") in ("done", "error"):
            store.set_pending(run_id, False)
        if body.get("type") == "done":
            await _snapshot_conclusion(run_id)
    return {"ok": True}


async def _snapshot_conclusion(run_id: str) -> None:
    """done 时把「问题 → 最终结论」结构化快照写入 run.json 的 conclusion 字段。

    供后续排查知识库直接使用：问题/环境/应用/结论/轮次/本轮工具数/usage。
    """
    import re
    import time

    from . import agent_engine as sidecar

    def clean_question(text: str) -> str:
        """去掉注入前缀（[识别提示:…] / [当前排查环境:…] / 用户消息:），还原原始问题。"""
        t = re.sub(r"^\[识别提示:[^\]]*\]\s*", "", text or "")
        t = re.sub(r"^\[当前排查环境:[^\]]*\]\s*", "", t)
        t = re.sub(r"^用户消息:\s*", "", t)
        return t.strip()

    try:
        run = store.get_run(run_id)
        if run is None:
            return
        msgs = await sidecar.get_messages(store.run_engine(run), run_id)
        first_user = next((m.get("text", "") for m in msgs if m.get("role") == "user"), "")
        last_ai = next(
            (m for m in reversed(msgs) if m.get("role") == "assistant" and not m.get("incomplete")),
            None,
        )
        if not last_ai or not (last_ai.get("text") or "").strip():
            return
        snapshot = {
            "question": clean_question(first_user)[:500],
            "answer": last_ai.get("text", "")[:20000],
            "env": run.get("env"),
            "app": run.get("app"),
            "mode": run.get("mode"),
            "rounds": run.get("message_count") or 0,
            "tools_used": len(last_ai.get("tool_calls") or []),
            "usage": last_ai.get("usage"),
            "satisfaction": store.get_satisfaction(run_id),
            "ts": time.time(),
        }
        store.update_run(run_id, {"conclusion": snapshot})
    except Exception as exc:  # noqa: BLE001
        print(f"[conclusion snapshot] {run_id}: {exc}")


@router.get("/envs")
async def list_envs():
    return {"envs": ["dev", "sit"], "model": config.LLM_MODEL}
