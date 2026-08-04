"""WebSocket：/runs/{id}/stream 实时事件流。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import events, store

router = APIRouter(tags=["ws"])


@router.websocket("/runs/{run_id}/stream")
async def stream(run_id: str, ws: WebSocket):
    await ws.accept()
    if store.get_run(run_id) is None:
        await ws.send_text(json.dumps({"type": "error", "data": {"message": "run not found"}}))
        await ws.close()
        return
    q = await events.subscribe(run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
                continue
            await ws.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        await events.unsubscribe(run_id, q)
