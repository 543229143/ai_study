"""文本式 ReAct 的解析器（从 core/agent.py 抽出来，便于单独测）。

这套逻辑就是"文本协议"的全部脆弱点所在：
模型必须一字不差地输出 `Thought: ...` / `Action: Tool[参数]`，
解析端靠正则去猜。猜错了，agent 就会空转。

scripts/parse_benchmark.py 用它来量化失败率。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


def parse_thought_action(text: str) -> Tuple[str, str]:
    """从模型输出里抽出 (thought, action)。抽不到就是空串。"""
    thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", text, re.DOTALL)
    action_match = re.search(r"Action:\s*(.*?)$", text, re.MULTILINE)
    thought = thought_match.group(1).strip() if thought_match else ""
    action = action_match.group(1).strip() if action_match else ""
    return thought, action


def parse_tool_call(action: str) -> Tuple[Optional[str], Optional[str]]:
    """把 `Tool[参数]` 拆成 (tool_name, query)。"""
    match = re.match(r"(\w+)\[(.*)\]", action, re.DOTALL)
    if match:
        return match.group(1), match.group(2).strip()
    return None, None


def extract_bracket(action: str) -> str:
    """取 `Finish[...]` 里的内容。"""
    match = re.search(r"\[(.*)\]", action, re.DOTALL)
    return match.group(1).strip() if match else action[len("Finish["):].strip()
