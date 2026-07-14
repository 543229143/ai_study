"""mini_agent — 从 20 行核心循环演进到三层架构的 Agent 教学实现"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════
# Layer 0: 类型系统 (Day 1 / Day 4)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Message:
    role: str        # system / user / assistant / tool
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AgentTool:
    def __init__(self, name: str, description: str, parameters: dict, fn: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema
        self.fn = fn

    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, **kwargs) -> str:
        try:
            result = self.fn(**kwargs)
            return json.dumps({"success": True, "data": result}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e), "retryable": True}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════
# Layer 1: LLM Provider 抽象 (Day 2 / Day 3)
# ═══════════════════════════════════════════════════════════════════

class LLMProvider(ABC):
    @abstractmethod
    def stream_chat(self, model: str, messages: list[dict], tools: list[dict] | None):
        ...


class OpenAIProvider(LLMProvider):
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()

    def stream_chat(self, model: str, messages: list[dict], tools: list[dict] | None):
        return self.client.chat.completions.create(
            model=model, messages=messages, tools=tools, stream=True
        )


# ═══════════════════════════════════════════════════════════════════
# Layer 2: Agent 核心 (Day 5 / Day 6)
# — 事件驱动设计：AgentLoop 发事件 → Agent 消费事件更新状态
# — 双层循环：内层(tool+steering) / 外层(followUp)
# — currentContext vs newMessages 分离
# ═══════════════════════════════════════════════════════════════════

class AgentEvent:
    """AgentLoop 发出的事件，Agent 消费"""
    def __init__(self, type_: str, **data):
        self.type = type_
        self.data = data


class Agent:
    def __init__(self, provider: LLMProvider, model: str, tools: list[AgentTool]):
        self.provider = provider
        self.model = model
        self.tools = tools
        self.messages: list[Message] = []  # currentContext — 完整上下文
        self.listeners: list[Callable] = []

    def subscribe(self, fn: Callable):
        self.listeners.append(fn)

    def _emit(self, event: AgentEvent):
        for fn in self.listeners:
            fn(event)

    def prompt(self, user_input: str) -> str:
        """外层入口：接受用户输入，进入 agentLoop"""
        self.messages.append(Message(role="user", content=user_input))
        return self._run_loop()

    def continue_(self) -> str:
        """继续已有对话（外层循环）"""
        return self._run_loop()

    def _run_loop(self) -> str:
        """内层循环：tool calling + steering 打断处理"""
        self._emit(AgentEvent("agent_start"))

        while True:
            # 1. 调 LLM
            assistant_msg = self._call_llm()
            self.messages.append(assistant_msg)
            self._emit(AgentEvent("turn_end", message=assistant_msg))

            # 2. 检查是否有工具调用
            if not assistant_msg.tool_calls:
                # 没有工具调用 → 结束内层循环
                final = assistant_msg.content or ""
                self._emit(AgentEvent("agent_end", result=final))
                return final

            # 3. 执行工具
            new_msgs: list[Message] = []  # newMessages — 本次增量
            for tc in assistant_msg.tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                tool = next((t for t in self.tools if t.name == name), None)
                if not tool:
                    result = json.dumps({"success": False, "error": f"Unknown tool: {name}", "retryable": False})
                else:
                    result = tool.execute(**args)

                new_msgs.append(Message(role="tool", tool_call_id=tc["id"], name=name, content=result))

            # 4. 工具结果回灌到上下文
            self.messages.extend(new_msgs)
            self._emit(AgentEvent("tool_results", messages=new_msgs))
            # 内层循环继续（回到步骤 1）

    def _call_llm(self) -> Message:
        """调 LLM，流式拼接结果"""
        raw_messages = [
            {"role": m.role, "content": m.content}
            for m in self.messages if m.content
        ]
        tool_defs = [t.to_openai_tool() for t in self.tools]

        stream = self.provider.stream_chat(self.model, raw_messages, tool_defs)

        content_chunks: list[str] = []
        tool_calls: dict[int, dict] = {}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            if delta.content:
                content_chunks.append(delta.content)
                self._emit(AgentEvent("text_delta", text=delta.content))

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    if tc.id:
                        tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls[idx]["function"]["arguments"] += tc.function.arguments

        content = "".join(content_chunks) or None
        calls = list(tool_calls.values()) if tool_calls else None

        return Message(role="assistant", content=content, tool_calls=calls)


# ═══════════════════════════════════════════════════════════════════
# Layer 3: AgentHarness (Day 7 / Day 9 / Day 10 / Day 11)
# — Session 持久化、Compaction、System Prompt 组装
# ═══════════════════════════════════════════════════════════════════

class SessionStore:
    """JSON 文件持久化（Day 11）"""
    def __init__(self, path: str):
        self.path = path

    def save(self, messages: list[Message]):
        data = [
            {"role": m.role, "content": m.content, "tool_call_id": m.tool_call_id, "name": m.name}
            for m in messages
        ]
        with open(self.path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self) -> list[Message]:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            data = json.load(f)
        return [Message(**m) for m in data]


def build_system_prompt(has_tools: bool, context: str = "") -> str:
    """System Prompt 组装工厂（Day 10）"""
    parts = ["你是 AI 助手。如果需求不明确，主动反问获取缺失信息。"]

    if has_tools:
        parts.append("你可以调用工具来完成任务。工具参数不全时不要编造，先问清楚。")

    if context:
        parts.append(f"\n上下文信息：\n{context}")

    parts.append("\n回答时做到：\n- 工具执行的结果用自然语言组织后返回\n- 如果工具执行失败，告诉用户发生了什么")
    return "\n".join(parts)


def compact_messages(messages: list[Message], max_count: int = 20, summary_fn=None) -> list[Message]:
    """Compaction（Day 9）：消息太多时压缩早期对话"""
    if len(messages) <= max_count:
        return messages

    early = messages[1:max_count // 2]  # 跳过 system
    keep = [messages[0]] + messages[max_count // 2:]

    if summary_fn:
        # 用 LLM 总结
        text_to_summarize = "\n".join(
            f"{m.role}: {m.content}" for m in early if m.content
        )
        summary = summary_fn(text_to_summarize)
    else:
        summary = f"[压缩摘要：已合并 {len(early)} 条早期消息]"

    keep.insert(1, Message(role="system", content=f"早期对话摘要：{summary}"))
    return keep


class AgentHarness:
    """协调 Agent + Session + Compaction"""
    def __init__(self, agent: Agent, session_path: str, max_messages: int = 20):
        self.agent = agent
        self.store = SessionStore(session_path)
        self.max_messages = max_messages

        # 从 session 恢复
        restored = self.store.load()
        if restored:
            agent.messages = restored

    def prompt(self, user_input: str) -> str:
        # 构建 system prompt
        has_tools = len(self.agent.tools) > 0
        sys_prompt = build_system_prompt(has_tools)

        # 只在首次注入 system
        if not any(m.role == "system" for m in self.agent.messages):
            self.agent.messages.insert(0, Message(role="system", content=sys_prompt))

        # 执行
        result = self.agent.prompt(user_input)

        # compaction
        self.agent.messages = compact_messages(self.agent.messages, self.max_messages)

        # 持久化
        self.store.save(self.agent.messages)

        return result


# ═══════════════════════════════════════════════════════════════════
# 工具定义（Day 8）
# ═══════════════════════════════════════════════════════════════════

def query_weather(city: str):
    return f"{city}今日天气：晴，22-28°C，微风"


def create_reminder(time: str, content: str):
    return f"已设置提醒：{time} {content}"


def search_web(query: str):
    return f"关于「{query}」的搜索结果：共找到 42 条相关结果"


TOOLS = [
    AgentTool(
        name="query_weather",
        description="查询指定城市的实时天气",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如 北京、上海"}
            },
            "required": ["city"],
        },
        fn=query_weather,
    ),
    AgentTool(
        name="create_reminder",
        description="创建提醒事项",
        parameters={
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "提醒时间，如 明天下午3点"},
                "content": {"type": "string", "description": "提醒内容，如 开会"},
            },
            "required": ["time", "content"],
        },
        fn=create_reminder,
    ),
    AgentTool(
        name="search_web",
        description="搜索网络信息",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"}
            },
            "required": ["query"],
        },
        fn=search_web,
    ),
]


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

def main():
    provider = OpenAIProvider()
    agent = Agent(provider=provider, model="gpt-4o", tools=TOOLS)

    # 订阅事件 — 打印工具调用
    def on_event(event: AgentEvent):
        if event.type == "tool_results":
            for m in event.data["messages"]:
                print(f"  → 工具 [{m.name}] 返回: {m.content}")
        elif event.type == "text_delta":
            print(event.data["text"], end="", flush=True)

    agent.subscribe(on_event)

    harness = AgentHarness(agent, session_path="/tmp/mini_agent_session.json")

    print("mini_agent 已启动（输入 quit 退出）\n")
    while True:
        try:
            user_input = input("\n你: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("quit", "exit"):
            break

        print("AI: ", end="", flush=True)
        result = harness.prompt(user_input)
        print()  # 流式输出后的换行


if __name__ == "__main__":
    main()
