"""轻量 tracing：记录每次 LLM / 工具调用的 token、成本、耗时。

目标不是做一个 Langfuse，而是让每次分析可度量：
一次 run 对应一个 TraceRecorder，落一份 JSONL，最后给一行汇总。

用法：
    tracer = TraceRecorder()
    tracer.record_llm(model="gpt-4o-mini", usage={"prompt_tokens": 1200, ...}, latency_ms=830)
    tracer.record_tool("GetRealtimeQuote", {"symbol": "600519"}, ok=True, latency_ms=210)
    print(tracer.summary())
    tracer.save("results/trace.jsonl")
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# 单位：美元 / 百万 token。
# 注意：价格会变，这张表只是兜底，优先用环境变量覆盖。
#   LLM_PRICE_INPUT_PER_M / LLM_PRICE_OUTPUT_PER_M
DEFAULT_PRICING: Dict[str, tuple] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "deepseek-chat": (0.27, 1.10),
}


@dataclass
class TraceEvent:
    kind: str  # "llm" | "tool"
    name: str
    latency_ms: float
    ok: bool = True
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Optional[float] = None
    detail: Dict[str, Any] = field(default_factory=dict)
    ts: str = ""


class TraceRecorder:
    """一次 run 的记录器。线程不安全，一个 run 用一个实例。"""

    def __init__(self, run_id: Optional[str] = None, pricing: Optional[Dict[str, tuple]] = None):
        self.run_id = run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
        self.events: List[TraceEvent] = []
        self._pricing = dict(DEFAULT_PRICING)
        if pricing:
            self._pricing.update(pricing)
        self._env_in = _env_float("LLM_PRICE_INPUT_PER_M")
        self._env_out = _env_float("LLM_PRICE_OUTPUT_PER_M")
        self._t0 = time.perf_counter()

    # ---------- 记录 ----------

    def record_llm(
        self,
        model: str,
        usage: Optional[Dict[str, int]] = None,
        latency_ms: Optional[float] = None,
        ok: bool = True,
        error: Optional[str] = None,
        step: Optional[int] = None,
    ) -> TraceEvent:
        usage = usage or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        event = TraceEvent(
            kind="llm",
            name=model,
            latency_ms=latency_ms if latency_ms is not None else 0.0,
            ok=ok,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=self._cost(model, prompt_tokens, completion_tokens),
            detail={"step": step, "error": error} if (step is not None or error) else {},
            ts=datetime.now().isoformat(timespec="seconds"),
        )
        self.events.append(event)
        return event

    def record_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        ok: bool = True,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> TraceEvent:
        event = TraceEvent(
            kind="tool",
            name=name,
            latency_ms=latency_ms if latency_ms is not None else 0.0,
            ok=ok,
            detail={"arguments": arguments or {}, **({"error": error} if error else {})},
            ts=datetime.now().isoformat(timespec="seconds"),
        )
        self.events.append(event)
        return event

    # ---------- 汇总 ----------

    def summary(self) -> Dict[str, Any]:
        llm = [e for e in self.events if e.kind == "llm"]
        tool = [e for e in self.events if e.kind == "tool"]
        costs = [e.cost_usd for e in llm if e.cost_usd is not None]
        return {
            "run_id": self.run_id,
            "llm_calls": len(llm),
            "llm_failures": sum(1 for e in llm if not e.ok),
            "tool_calls": len(tool),
            "tool_failures": sum(1 for e in tool if not e.ok),
            "tool_success_rate": round(
                (len(tool) - sum(1 for e in tool if not e.ok)) / len(tool), 4
            ) if tool else None,
            "prompt_tokens": sum(e.prompt_tokens for e in llm),
            "completion_tokens": sum(e.completion_tokens for e in llm),
            "total_tokens": sum(e.prompt_tokens + e.completion_tokens for e in llm),
            "llm_latency_ms": round(sum(e.latency_ms for e in llm), 1),
            "tool_latency_ms": round(sum(e.latency_ms for e in tool), 1),
            "wall_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            # None 表示有调用的模型不在价格表里，别拿 0 冒充
            "cost_usd": round(sum(costs), 6) if costs else None,
            "cost_unknown_calls": sum(1 for e in llm if e.cost_usd is None),
        }

    def render_row(self) -> str:
        """输出 markdown 表格的一行，方便直接贴进 benchmark 表。"""
        s = self.summary()
        cost = "未知" if s["cost_usd"] is None else f"${s['cost_usd']:.4f}"
        rate = "—" if s["tool_success_rate"] is None else f"{s['tool_success_rate'] * 100:.0f}%"
        return (
            f"| {self.run_id} | {s['wall_ms'] / 1000:.1f}s | {s['total_tokens']} | "
            f"{cost} | {rate} | {s['llm_calls']} |"
        )

    # ---------- 落盘 ----------

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        summary_path = f"{path}.summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(self.summary(), f, ensure_ascii=False, indent=2)
        return summary_path

    # ---------- 内部 ----------

    def _cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
        if self._env_in is not None and self._env_out is not None:
            price_in, price_out = self._env_in, self._env_out
        elif model in self._pricing:
            price_in, price_out = self._pricing[model]
        else:
            return None
        return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000


def _env_float(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
