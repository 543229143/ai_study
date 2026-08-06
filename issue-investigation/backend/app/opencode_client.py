"""opencode sidecar 客户端：发送用户消息、拉取会话消息（带 agent 参数）。"""
from __future__ import annotations

import httpx

from . import config


async def send_message(run_id: str, text: str, env: str, history: list[str] | None = None, agent: str | None = None) -> dict:
    """将用户消息转发给 opencode sidecar（prompt 内注入当前环境与 agent）。"""
    payload = {
        "run_id": run_id,
        "text": text,
        "env": env,
        "history": history,
        "agent": agent or "investigation",
    }
    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(f"{config.OPENCODE_BASE_URL}/sessions/{run_id}/prompt", json=payload)
        resp.raise_for_status()
        return resp.json()


async def get_messages(run_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{config.OPENCODE_BASE_URL}/sessions/{run_id}/messages")
        resp.raise_for_status()
        return resp.json()


async def get_cost(run_id: str) -> float:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{config.OPENCODE_BASE_URL}/sessions/{run_id}/cost")
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("cost") or 0)


async def abort_session(run_id: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{config.OPENCODE_BASE_URL}/sessions/{run_id}/abort")
        resp.raise_for_status()


async def get_session_status(run_id: str) -> dict:
    """查询 opencode 侧会话运行状态：{processing, has_session}。失败按未运行处理。"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{config.OPENCODE_BASE_URL}/sessions/{run_id}/status")
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return {"processing": False, "has_session": False, "unreachable": True}


async def create_session(run_id: str, env: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{config.OPENCODE_BASE_URL}/sessions/{run_id}",
            json={"run_id": run_id, "env": env},
        )
        resp.raise_for_status()
        return resp.json()
