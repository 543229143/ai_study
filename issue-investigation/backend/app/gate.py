"""意图门禁：判断用户消息是否属于问题排查，拦截无关提问。

策略：
- 首条消息：严格门禁（必须明确排查意图）
- 后续消息：宽松门禁（带最近对话上下文，默认放行，仅拦明显无关）
拿不准一律放行（放行是默认，拦截是例外）。
"""
from __future__ import annotations

from . import config
from . import llm

_SYSTEM = """你是问题排查平台的意图过滤器。平台只做 dev/sit 环境的问题排查：
- 日志报错/异常排查（traceId、告警信息、Exception 片段）
- 落库异常/数据核对（借据、订单、申请等业务数据查询）
- 配置疑似有误（Nacos 配置核对）
- 对当前排查的追问、补充信息、换环境再看

规则：
1. 属于上述排查类问题 → {"allow": true}
2. 明显无关内容（闲聊、编程题、其他领域技术问题、情感/天气等）→ {"allow": false}
3. 拿不准 → {"allow": true}（放行是默认）
4. 只输出 JSON，不要其他文字。"""


def _build_user_text(text: str, history: list[str] | None) -> str:
    parts = [f"用户消息: {text}"]
    if history:
        tail = history[-4:]
        parts.insert(0, "最近对话（供判断上下文，可能为空）:\n" + "\n".join(f"- {m[:200]}" for m in tail))
    parts.append("请判断是否放行进入问题排查流程。")
    return "\n".join(parts)


def gate_check(text: str, *, is_first: bool, history: list[str] | None = None) -> dict:
    """返回 {allow, reason}。LLM 失败时按放行处理（fail-open）。"""
    try:
        result = llm.chat_json(_SYSTEM, _build_user_text(text, history), max_tokens=300)
        allow = bool(result.get("allow", True))
        reason = str(result.get("reason") or "")
        return {"allow": allow, "reason": reason}
    except Exception as exc:  # noqa: BLE001
        return {"allow": True, "reason": f"门禁判定失败，默认放行: {exc}"}
