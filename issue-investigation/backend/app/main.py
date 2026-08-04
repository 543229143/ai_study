"""问题排查平台后端入口。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api_runs import router as runs_router
from .api_tools import router as tools_router
from .api_ws import router as ws_router

app = FastAPI(title="Issue Investigation Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
