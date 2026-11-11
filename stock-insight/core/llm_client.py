"""LLM 客户端：多 provider 兼容 + 重试 + 原生 tool_calls。

相对旧版的三点改动：
1. openai SDK 改成惰性导入 —— 没装依赖时不再 import 就炸，单测可以不装。
2. 新增 chat()：返回结构化结果（content / tool_calls / usage），供原生 function calling 使用。
3. 加了有限重试：网络抖动和 5xx 不再直接返回 None。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()


class LLMError(RuntimeError):
    """模型调用最终失败（重试耗尽）。"""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""


class LLMClient:
    def __init__(self, model=None, api_key=None, base_url=None, timeout=60, max_retries=None):
        self.model = model or os.getenv("LLM_MODEL_ID") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        self.timeout = timeout
        self.max_retries = int(max_retries if max_retries is not None else os.getenv("LLM_MAX_RETRIES", "2"))

        if not self.api_key:
            raise RuntimeError("LLM_API_KEY or OPENAI_API_KEY not set in environment")

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的提示
            raise RuntimeError("需要安装 openai SDK：pip install openai") from exc

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=timeout)
        self.tracer = None  # 可选：挂上 TraceRecorder 后，think() 也会被记录

    # ---------- 新接口 ----------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.1,
        tool_choice: Optional[str] = None,
    ) -> LLMResponse:
        """一次模型调用。失败会重试，重试耗尽抛 LLMError。"""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                completion = self.client.chat.completions.create(**kwargs)
                return _to_response(completion, self.model)
            except Exception as exc:  # noqa: BLE001 - 统一在这里兜
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
        raise LLMError(f"LLM 调用失败（重试 {self.max_retries} 次）：{last_error}")

    # ---------- 旧接口，保持兼容 ----------

    def think(self, messages, temperature=0.1, stream=False) -> Optional[str]:
        """旧调用方在用（plan_agent / reflection_agent）。失败返回 None。"""
        if stream:
            try:
                return self._stream(messages, temperature)
            except Exception as e:  # noqa: BLE001
                print(f"LLM call failed: {e}")
                return None

        t0 = time.perf_counter()
        try:
            response = self.chat(messages, temperature=temperature)
        except Exception as e:  # noqa: BLE001
            if self.tracer is not None:
                self.tracer.record_llm(
                    model=self.model,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    ok=False,
                    error=str(e),
                )
            print(f"LLM call failed: {e}")
            return None

        if self.tracer is not None:
            self.tracer.record_llm(
                model=response.model or self.model,
                usage=response.usage,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        return response.content

    def _stream(self, messages, temperature) -> str:
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature, stream=True
        )
        chunks = []
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
        return "".join(chunks)


def _to_response(completion: Any, fallback_model: str) -> LLMResponse:
    choice = completion.choices[0].message
    calls: List[ToolCall] = []
    for call in getattr(choice, "tool_calls", None) or []:
        calls.append(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=_parse_arguments(call.function.arguments),
            )
        )
    usage = getattr(completion, "usage", None)
    return LLMResponse(
        content=getattr(choice, "content", None) or "",
        tool_calls=calls,
        usage={
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        } if usage else {},
        model=getattr(completion, "model", None) or fallback_model,
    )


def _parse_arguments(raw: Any) -> Dict[str, Any]:
    import json

    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"_raw": parsed}
    except json.JSONDecodeError:
        return {"_raw": raw}
