from core.tool_agent import ToolCallingAgent
from core.tool_registry import ToolRegistry, object_schema, string_param
from core.tracing import TraceRecorder
from tests.fakes import FakeLLM, FakeResponse, FakeToolCall


def _registry():
    reg = ToolRegistry()
    reg.register(
        "Echo",
        "回显",
        object_schema({"text": string_param("文本")}, ["text"]),
        lambda a: f"echo:{a['text']}",
    )
    return reg


def test_returns_content_when_model_calls_no_tool():
    llm = FakeLLM([FakeResponse(content="直接回答", usage={"prompt_tokens": 10, "completion_tokens": 5})])
    agent = ToolCallingAgent(llm=llm, registry=_registry())
    assert agent.run("你好") == "直接回答"
    assert llm.calls[0]["tools"] is not None  # schema 已传给模型


def test_executes_tool_then_answers():
    llm = FakeLLM(
        [
            FakeResponse(
                tool_calls=[FakeToolCall(id="call_1", name="Echo", arguments={"text": "hi"})],
                usage={"prompt_tokens": 20, "completion_tokens": 8},
            ),
            FakeResponse(content="最终结论", usage={"prompt_tokens": 30, "completion_tokens": 12}),
        ]
    )
    agent = ToolCallingAgent(llm=llm, registry=_registry())
    assert agent.run("测试") == "最终结论"

    tool_messages = [m for m in agent.messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert tool_messages[0]["content"] == "echo:hi"

    assistant = [m for m in agent.messages if m["role"] == "assistant"][0]
    assert assistant["tool_calls"][0]["function"]["name"] == "Echo"


def test_unknown_tool_does_not_crash_run():
    llm = FakeLLM(
        [
            FakeResponse(tool_calls=[FakeToolCall(id="c1", name="Ghost", arguments={})]),
            FakeResponse(content="降级回答"),
        ]
    )
    agent = ToolCallingAgent(llm=llm, registry=_registry())
    assert agent.run("测试") == "降级回答"
    tool_msg = [m for m in agent.messages if m["role"] == "tool"][0]
    assert "not found" in tool_msg["content"]


def test_stops_at_max_steps_and_forces_wrap_up():
    looping = FakeResponse(tool_calls=[FakeToolCall(id="c", name="Echo", arguments={"text": "x"})])
    llm = FakeLLM([looping, looping, FakeResponse(content="收尾结论")])
    agent = ToolCallingAgent(llm=llm, registry=_registry(), max_steps=2)
    result = agent.run("死循环测试")
    assert result == "收尾结论"
    # max_steps 次工具轮 + 1 次收尾调用
    assert len(llm.calls) == 3
    assert llm.calls[-1]["tools"] is None  # 收尾那轮不再给工具


def test_tracer_records_tokens_tools_and_success_rate():
    tracer = TraceRecorder(run_id="t1")
    llm = FakeLLM(
        [
            FakeResponse(
                tool_calls=[FakeToolCall(id="c1", name="Echo", arguments={"text": "a"})],
                usage={"prompt_tokens": 100, "completion_tokens": 20},
            ),
            FakeResponse(content="ok", usage={"prompt_tokens": 150, "completion_tokens": 30}),
        ]
    )
    agent = ToolCallingAgent(llm=llm, registry=_registry(), tracer=tracer)
    agent.run("测试")

    summary = tracer.summary()
    assert summary["llm_calls"] == 2
    assert summary["total_tokens"] == 300
    assert summary["tool_calls"] == 1
    assert summary["tool_success_rate"] == 1.0
    # fake-model 不在价格表里，成本必须显式未知，不能悄悄算成 0
    assert summary["cost_usd"] is None
    assert summary["cost_unknown_calls"] == 2
