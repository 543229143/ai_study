"""测试替身：不联网、不依赖 openai SDK。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FakeToolCall:
    id: str
    name: str
    arguments: Any = field(default_factory=dict)


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: List[FakeToolCall] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = "fake-model"


class FakeLLM:
    """按脚本依次返回响应；脚本用完就重复最后一个。"""

    model = "fake-model"

    def __init__(self, script: List[FakeResponse]):
        self.script = list(script)
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, tools=None, temperature=0.1, tool_choice=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self.script:
            return FakeResponse(content="(no script)")
        response = self.script[0] if len(self.script) == 1 else self.script.pop(0)
        return response

    def think(self, messages, temperature=0.1, stream=False) -> Optional[str]:
        return self.chat(messages).content
