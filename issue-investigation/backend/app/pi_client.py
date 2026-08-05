"""pi sidecar 客户端：发送用户消息、拉取会话消息。"""
from __future__ import annotations

import httpx

from . import config


async def send_message(run_id: str, text: str, env: str, history: list[str] | None = None) -> dict:
    """将用户消息转发给 pi sidecar（prompt 内注入当前环境）。"""
    payload = {
        "run_id": run_id,
        "text": text,
        "env": env,
        "history": history,
    }
    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(f"{config.PI_BASE_URL}/sessions/{run_id}/prompt", json=payload)
        resp.raise_for_status()
        return resp.json()


async def get_messages(run_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{config.PI_BASE_URL}/sessions/{run_id}/messages")
        resp.raise_for_status()
        return resp.json()


async def get_cost(run_id: str) -> float:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{config.PI_BASE_URL}/sessions/{run_id}/cost")
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("cost") or 0)


async def create_session(run_id: str, env: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{config.PI_BASE_URL}/sessions/{run_id}",
            json={"run_id": run_id, "env": env},
        )
        resp.raise_for_status()
        return resp.json()
