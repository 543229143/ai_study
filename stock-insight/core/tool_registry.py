"""工具注册表：把工具描述成 JSON Schema，交给模型的原生 function calling 使用。

和 core/tools.py 的区别：
- tools.py 里是"文本工具"，模型只能输出 `Tool[参数|参数]` 这种字符串，靠正则解析；
- 这里的工具带结构化参数，模型输出 tool_calls，参数是 JSON，不需要解析。

本模块不依赖 akshare / pandas，方便单测。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema 的 object
    func: Callable[[Dict[str, Any]], Any]


class ToolRegistry:
    """注册 + 生成 schema + 派发。"""

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
        func: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> "ToolRegistry":
        if func is None:
            raise ValueError(f"tool '{name}' 缺少 func")
        schema = parameters or {"type": "object", "properties": {}, "required": []}
        self._tools[name] = ToolSpec(name, description, schema, func)
        return self

    def names(self) -> List[str]:
        return list(self._tools)

    def schema(self) -> List[Dict[str, Any]]:
        """OpenAI `tools` 参数格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def call(self, name: str, arguments: Any = None) -> str:
        """执行工具，永远返回字符串，不抛异常。"""
        return self.call_with_status(name, arguments)[0]

    def call_with_status(self, name: str, arguments: Any = None) -> tuple:
        """执行工具，返回 (observation, ok)。

        模型给什么参数是不可控的：缺字段、类型错、名字编造，都要变成
        一条能被模型读懂的 observation，而不是把整个 run 炸掉。
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Tool '{name}' not found. Available: {self.names()}", False

        args = _coerce_arguments(arguments)
        if isinstance(args, str):  # JSON 解析失败
            return f"Tool '{name}' argument error: {args}", False

        missing = [k for k in tool.parameters.get("required", []) if k not in args]
        if missing:
            return f"Tool '{name}' missing required argument(s): {missing}", False

        try:
            return str(tool.func(args)), True
        except Exception as exc:  # noqa: BLE001 - 工具失败要变成 observation
            return f"Tool '{name}' failed: {exc}", False


def _coerce_arguments(arguments: Any) -> Any:
    """兼容 dict / JSON 字符串 / None 三种形态。"""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return f"invalid JSON ({exc})"
        return parsed if isinstance(parsed, dict) else f"expected a JSON object, got {type(parsed).__name__}"
    return f"unsupported argument type {type(arguments).__name__}"


def object_schema(properties: Dict[str, Dict[str, Any]], required: Optional[List[str]] = None) -> Dict[str, Any]:
    """拼一个 object schema，省得每个工具手写三行。"""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def string_param(description: str, enum: Optional[List[str]] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "string", "description": description}
    if enum:
        schema["enum"] = enum
    return schema


def integer_param(description: str, default: Optional[int] = None, minimum: Optional[int] = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "integer", "description": description}
    if default is not None:
        schema["default"] = default
    if minimum is not None:
        schema["minimum"] = minimum
    return schema
