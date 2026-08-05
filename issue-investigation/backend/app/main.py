"""问题排查平台后端入口。"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api_config import router as config_router
from .api_runs import router as runs_router
from .api_tools import router as tools_router
from .api_ws import router as ws_router


class _IgnoreEventsPathFilter(logging.Filter):
    """屏蔽 pi 事件流的高频访问日志（/events/...），其余路径照常记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        return "/events/" not in msg


_logger = logging.getLogger("uvicorn.access")
_logger.addFilter(_IgnoreEventsPathFilter())

app = FastAPI(title="Issue Investigation Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(runs_router)
app.include_router(tools_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok", "data_dir": str(config.DATA_DIR)}


@app.get("/")
async def root():
    return {
        "name": "Issue Investigation Platform",
        "message": "这是后端服务，请使用前端界面：http://localhost:5178",
        "frontend": "http://localhost:5178",
        "docs": "/docs",
        "health": "/health",
    }
