"""Pydantic 模型：API 请求/响应。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Env = Literal["dev", "sit"]
Mode = Literal["trace_id", "alert", "biz_key"]
Scope = Literal["primary_only", "all", "custom"]


class CreateRunRequest(BaseModel):
    env: Env
    app: str = Field(default="lps", description="主应用（lcs/goa/ams/lps）")
    mode: Mode = "trace_id"
    trace_id: Optional[str] = None
    alert: Optional[str] = None
    biz_key: Optional[str] = None
    phenomenon: Optional[str] = None
    scope: Scope = "primary_only"
    custom_apps: Optional[list[str]] = None


class SendMessageRequest(BaseModel):
    text: str
    env: Optional[Env] = None  # 前端顶部当前环境，覆盖 run.env


class ToolCallRequest(BaseModel):
    """pi sidecar 调用工具端点的请求体。"""

    env: Env
    params: dict = Field(default_factory=dict)
    run_id: Optional[str] = None
