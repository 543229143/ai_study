"""原生 function calling 版的 Agent 主循环。

和 core/agent.py 的 ReActAgent 是同一个任务、两种实现，用来做对照：

    文本版（agent.py）：模型输出 "Action: Tool[a|b]"，用正则解析
    原生版（本文件）：模型输出 tool_calls，参数是 JSON，直接派发

对照的结论见 scripts/parse_benchmark.py（解析鲁棒性）与 scripts/benchmark.py（端到端）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .tool_registry import ToolRegistry
from .tracing import TraceRecorder

DEFAULT_SYSTEM_PROMPT = """你是一个专业的 A 股投资分析助理，可以使用工具获取行情、财务、技术指标和新闻。

规则：
1. 需要数据时调用工具，不要凭记忆编造数字。
2. 多个工具可以连续调用，拿到结果后再下结论。
3. 工具返回错误或空数据时，如实说明，不要假装有数据。
4. 最终用 Markdown 输出分析报告，包含：结论、依据（技术面/基本面/消息面）、风险提示。"""

WRAP_UP = "已达到工具调用上限。请基于目前掌握的信息直接输出分析报告，不要再调用工具。"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


class ToolCallingAgent:
    def __init__(
        self,
        llm: Any,
        registry: ToolRegistry,
        max_steps: int = 6,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        tracer: Optional[TraceRecorder] = None,
    ):
        self.llm = llm
        self.registry = registry
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.tracer = tracer or TraceRecorder()
        self.messages: List[Dict[str, Any]] = []
        self.steps = 0

    def run(self, question: str) -> str:
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": question},
        ]
        tools = self.registry.schema() or None

        for step in range(1, self.max_steps + 1):
            self.steps = step
            response = self._chat(tools=tools, step=step)

            tool_calls = list(getattr(response, "tool_calls", None) or [])
            if not tool_calls:
                return getattr(response, "content", "") or ""

            self.messages.append(
                {
                    "role": "assistant",
                    "content": getattr(response, "content", "") or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": _dump(call.arguments)},
                        }
                        for call in tool_calls
                    ],
                }
            )

            for call in tool_calls:
                t0 = time.perf_counter()
                observation, ok = self.registry.call_with_status(call.name, call.arguments)
                self.tracer.record_tool(
                    name=call.name,
                    arguments=call.arguments,
                    ok=ok,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    error=None if ok else observation[:200],
                )
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": observation}
                )

        # 用完步数还没收敛：让模型基于已有信息收尾，而不是丢一句"失败"
        self.messages.append({"role": "user", "content": WRAP_UP})
        response = self._chat(tools=None, step=self.max_steps + 1)
        return getattr(response, "content", "") or "已达到工具调用上限，未能给出结论。"

    # ---------- 内部 ----------

    def _chat(self, tools, step: int):
        t0 = time.perf_counter()
        try:
            response = self.llm.chat(self.messages, tools=tools, temperature=0.1)
        except Exception as exc:  # noqa: BLE001
            self.tracer.record_llm(
                model=getattr(self.llm, "model", "unknown"),
                latency_ms=(time.perf_counter() - t0) * 1000,
                ok=False,
                error=str(exc),
                step=step,
            )
            raise
        self.tracer.record_llm(
            model=getattr(response, "model", None) or getattr(self.llm, "model", "unknown"),
            usage=getattr(response, "usage", None),
            latency_ms=(time.perf_counter() - t0) * 1000,
            step=step,
        )
        return response


def _dump(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"
