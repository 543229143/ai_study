"""轻量 LLM 客户端（OpenAI 兼容，opencode-go 通道），用于意图门禁等单轮调用。"""
from __future__ import annotations

import json

from openai import OpenAI

from . import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.load_llm_api_key() or "sk-not-configured",
            base_url=config.LLM_BASE_URL,
            timeout=60.0,
        )
    return _client


def chat_json(system: str, user: str, *, max_tokens: int = 1200) -> dict:
    """单轮对话，要求模型输出 JSON 对象。失败时抛异常。"""
    resp = _get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    text = (resp.choices[0].message.content or "").strip()
    return _parse_json(text)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise
