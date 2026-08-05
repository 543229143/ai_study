"""Pydantic 模型：API 请求/响应。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Env = Literal["dev", "sit"]
Mode = Literal["trace_id", "alert", "biz_key"]
Scope = Literal["primary_only", "all", "custom"]

class CreateRunRequest(BaseModel):
    env: Env = "dev"
    app: Optional[str] = None
    mode: Optional[Mode] = None
    trace_id: Optional[str] = None
    alert: Optional[str] = None
    biz_key: Optional[str] = None
    phenomenon: Optional[str] = None
    scope: Optional[Scope] = None
    custom_apps: Optional[list[str]] = None
    text: Optional[str] = None  # 提供时自动识别 mode/app/查询值（简化入口）


class SendMessageRequest(BaseModel):
    text: str
    env: Optional[Env] = None  # 前端顶部当前环境，覆盖 run.env
    resume: bool = False  # 自动续跑：跳过门禁、不计轮次（重启中断后重发最后一条消息）


class ToolCallRequest(BaseModel):
    """pi sidecar 调用工具端点的请求体。"""

    env: Env
    params: dict = Field(default_factory=dict)
    run_id: Optional[str] = None
