"""Agent 引擎客户端：按 run 的 engine 动态路由（同一功能不混放在一个文件）。

- opencode_client.py：opencode 引擎（:8700，prompt 带 agent 参数）
- pi_client.py：pi 引擎（:8701，无 agent 概念）
- 本模块统一入口：调用方传 run 的 engine，自动选择对应客户端。
"""
from __future__ import annotations

from . import opencode_client, pi_client


def client_for(engine: str):
    return pi_client if engine == "pi" else opencode_client


async def create_session(engine: str, run_id: str, env: str) -> dict:
    return await client_for(engine).create_session(run_id, env)


async def send_message(
    engine: str,
    run_id: str,
    text: str,
    env: str,
    history: list[str] | None = None,
    agent: str | None = None,
) -> dict:
    if engine == "pi":
        return await pi_client.send_message(run_id, text, env, history=history)
    return await opencode_client.send_message(run_id, text, env, history=history, agent=agent)


async def get_messages(engine: str, run_id: str) -> list[dict]:
    return await client_for(engine).get_messages(run_id)


async def get_cost(engine: str, run_id: str) -> float:
    return await client_for(engine).get_cost(run_id)


async def abort_session(engine: str, run_id: str) -> None:
    return await client_for(engine).abort_session(run_id)


async def get_session_status(engine: str, run_id: str) -> dict:
    return await client_for(engine).get_session_status(run_id)
