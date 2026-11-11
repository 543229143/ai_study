from core.react_parser import extract_bracket, parse_thought_action, parse_tool_call


def test_parses_canonical_output():
    thought, action = parse_thought_action("Thought: 先看行情\nAction: GetRealtimeQuote[600519]")
    assert thought == "先看行情"
    assert action == "GetRealtimeQuote[600519]"
    assert parse_tool_call(action) == ("GetRealtimeQuote", "600519")


def test_full_width_colon_is_not_recognised():
    # 中文输入法下的全角冒号，正则匹配不到 —— 这是文本协议的固有缺口
    thought, action = parse_thought_action("Thought：先看行情\nAction：GetRealtimeQuote[600519]")
    assert thought == ""
    assert action == ""


def test_multiline_arguments_are_truncated():
    # Action 行只取到行尾，多行参数会被截断，导致工具收到残缺参数
    _thought, action = parse_thought_action("Thought: 保存\nAction: SaveAnalysis[600519|分析茅台\n第二段]")
    assert action == "SaveAnalysis[600519|分析茅台"
    assert parse_tool_call(action) == (None, None)  # 缺少结尾 ]，直接解析失败


def test_round_brackets_fail():
    assert parse_tool_call("GetNews(600519)") == (None, None)


def test_extract_bracket_handles_finish():
    assert extract_bracket("Finish[建议观望]") == "建议观望"
    assert extract_bracket("Finish 观望") == "观望"
