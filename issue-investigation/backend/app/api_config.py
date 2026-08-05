"""配置 API：应用清单 / 数据库名 / 业务键规则 / 业务术语（data/config/apps.json）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from . import config_store

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    return config_store.load_config()


@router.put("")
async def put_config(cfg: dict[str, Any]) -> dict[str, Any]:
    result = config_store.save_config(cfg)
    if not result["saved"]:
        return {"saved": False, "errors": result["errors"]}
    return {"saved": True, "config": result["config"]}
