"""事件桥：每个 run 一个 asyncio.Queue，pi sidecar 推送事件，WebSocket 订阅者消费。

事件格式统一为 dict：
{"type": "text_delta"|"tool_start"|"tool_end"|"done"|"error"|..., "data": {...}}
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
_lock = asyncio.Lock()


async def subscribe(run_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    async with _lock:
        _queues[run_id].append(q)
    return q


async def unsubscribe(run_id: str, q: asyncio.Queue) -> None:
    async with _lock:
        queues = _queues.get(run_id, [])
        if q in queues:
            queues.remove(q)
        if not queues:
            _queues.pop(run_id, None)


async def publish(run_id: str, event: dict) -> None:
    queues = list(_queues.get(run_id, []))
    for q in queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
