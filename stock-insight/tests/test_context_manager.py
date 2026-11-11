from core.context_manager import ContextManager


def test_compress_keeps_recent_turns_and_adds_summary():
    ctx = ContextManager(max_tokens=100)  # 阈值 = 400 字符
    for i in range(10):
        ctx.add_turn("user", f"第{i}个问题" + "补" * 60)
        ctx.add_turn("assistant", f"第{i}个回答" + "充" * 60)

    turns = ctx.get_context()
    assert turns[0]["role"] == "system"
    assert "上下文压缩摘要" in turns[0]["content"]
    # 压缩后只保留最近 4 轮 + 1 条摘要
    assert len(turns) == 5


def test_no_compress_below_threshold():
    ctx = ContextManager(max_tokens=10_000)
    ctx.add_turn("user", "短问题")
    ctx.add_turn("assistant", "短回答")
    assert len(ctx.get_context()) == 2
    assert "tokens" in ctx.stats()
