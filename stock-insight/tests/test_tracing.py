import json
import os

from core.tracing import TraceRecorder


def test_cost_computed_from_pricing_table():
    tracer = TraceRecorder(run_id="cost")
    tracer.record_llm("gpt-4o-mini", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert tracer.summary()["cost_usd"] == 0.15

    tracer = TraceRecorder(run_id="cost2")
    tracer.record_llm("gpt-4o-mini", {"prompt_tokens": 0, "completion_tokens": 1_000_000})
    assert tracer.summary()["cost_usd"] == 0.6


def test_unknown_model_cost_is_none_not_zero():
    tracer = TraceRecorder(run_id="unknown")
    tracer.record_llm("some-local-model", {"prompt_tokens": 500, "completion_tokens": 500})
    summary = tracer.summary()
    assert summary["cost_usd"] is None
    assert summary["cost_unknown_calls"] == 1


def test_env_override_beats_table(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_M", "1")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_M", "2")
    tracer = TraceRecorder(run_id="env")
    tracer.record_llm("some-local-model", {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})
    assert tracer.summary()["cost_usd"] == 3.0


def test_tool_success_rate_and_failures():
    tracer = TraceRecorder(run_id="tools")
    tracer.record_tool("A", {}, ok=True, latency_ms=10)
    tracer.record_tool("B", {}, ok=False, latency_ms=20, error="boom")
    summary = tracer.summary()
    assert summary["tool_calls"] == 2
    assert summary["tool_failures"] == 1
    assert summary["tool_success_rate"] == 0.5


def test_save_writes_jsonl_and_summary(tmp_path):
    tracer = TraceRecorder(run_id="save")
    tracer.record_llm("gpt-4o-mini", {"prompt_tokens": 10, "completion_tokens": 5})
    tracer.record_tool("Echo", {"text": "x"}, ok=True)

    path = os.path.join(tmp_path, "trace.jsonl")
    summary_path = tracer.save(path)

    lines = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    assert len(lines) == 2
    assert lines[0]["kind"] == "llm"
    assert lines[1]["kind"] == "tool"

    saved = json.load(open(summary_path, encoding="utf-8"))
    assert saved["llm_calls"] == 1
    assert saved["total_tokens"] == 15


def test_render_row_is_markdown_table_row():
    tracer = TraceRecorder(run_id="row")
    tracer.record_llm("gpt-4o-mini", {"prompt_tokens": 100, "completion_tokens": 50})
    row = tracer.render_row()
    assert row.startswith("| row |")
    assert row.count("|") == 7
