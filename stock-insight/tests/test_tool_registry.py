from core.tool_registry import ToolRegistry, object_schema, string_param


def _registry():
    reg = ToolRegistry()
    reg.register(
        "Echo",
        "回显参数",
        object_schema({"text": string_param("要回显的文本")}, ["text"]),
        lambda a: f"echo:{a['text']}",
    )
    reg.register("Boom", "总是抛异常", object_schema({}, []), lambda a: 1 / 0)
    return reg


def test_schema_is_openai_tools_format():
    schema = _registry().schema()
    assert schema[0]["type"] == "function"
    fn = schema[0]["function"]
    assert fn["name"] == "Echo"
    assert fn["parameters"]["type"] == "object"
    assert "text" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["text"]


def test_call_dispatches_and_stringifies():
    assert _registry().call("Echo", {"text": "hi"}) == "echo:hi"


def test_call_accepts_json_string_arguments():
    # 模型有时把 arguments 当字符串返回，注册表要能兜住
    assert _registry().call("Echo", '{"text": "hi"}') == "echo:hi"


def test_unknown_tool_returns_message_not_exception():
    result = _registry().call("Nope", {})
    assert "not found" in result
    assert "Echo" in result


def test_missing_required_argument():
    result = _registry().call("Echo", {})
    assert "missing required argument" in result


def test_tool_exception_becomes_observation():
    result = _registry().call("Boom", {})
    assert "failed" in result
    assert "division by zero" in result


def test_call_with_status_reports_failure():
    obs, ok = _registry().call_with_status("Boom", {})
    assert ok is False
    assert "failed" in obs

    obs, ok = _registry().call_with_status("Echo", {"text": "x"})
    assert ok is True
    assert obs == "echo:x"
