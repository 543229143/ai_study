import os

import pytest

from core import runs
from core.resume import apply_answers, open_pendings, render
from core.safety.approval import ApprovalGate
from core.safety.pending import APPROVED, DENIED, PendingStore
from core.tools.remediation import RemediationTool

INCIDENT = {"incident_id": "db_pool_exhaustion", "service": "api-gateway"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "_dir", lambda: str(tmp_path / "runs"))
    store = PendingStore(path=str(tmp_path / "pending.jsonl"))
    gate = ApprovalGate(
        mode="suspend",
        audit_path=str(tmp_path / "audit.jsonl"),
        pending=store,
        run_id="r1",
        incident_id="db_pool_exhaustion",
        session="r1",
    )
    runs.save_run("r1", "db_pool_exhaustion", {"service": "api-gateway"})
    return store, gate, tmp_path


def test_suspend_records_pending_and_does_not_execute(env):
    store, gate, tmp_path = env
    calls = []
    tool = RemediationTool(INCIDENT, gate=gate, executor=lambda a, t: calls.append(a) or "done")

    result = tool.run("restart_service|api-gateway|连接池耗尽")

    assert "SUSPENDED" in result
    assert calls == []  # 挂起绝不能顺手执行
    item = store.list(run_id="r1")[0]
    assert item.action == "restart_service"
    assert item.session == "r1"  # 现场留下来了，回答后靠它续跑


def test_approve_after_suspend_executes(env):
    store, gate, tmp_path = env
    tool = RemediationTool(INCIDENT, gate=gate)
    tool.run("restart_service|api-gateway|连接池耗尽")
    pending_id = store.list(run_id="r1")[0].id

    calls = []
    report = apply_answers(
        "r1", {pending_id: True}, store=store, executor=lambda a, t: calls.append((a, t)) or "ok"
    )

    assert report["executed"][0]["action"] == "restart_service"
    assert calls == [("restart_service", "api-gateway")]
    assert store.get(pending_id).status == APPROVED


def test_deny_after_suspend_does_not_execute(env):
    store, gate, tmp_path = env
    RemediationTool(INCIDENT, gate=gate).run("scale_out|api-gateway|扩容")
    pending_id = store.list(run_id="r1")[0].id

    calls = []
    report = apply_answers(
        "r1", {pending_id: False}, store=store, executor=lambda a, t: calls.append(a) or "ok"
    )

    assert report["denied"][0]["action"] == "scale_out"
    assert calls == []
    assert store.get(pending_id).status == DENIED


def test_unanswered_items_are_skipped(env):
    store, gate, tmp_path = env
    tool = RemediationTool(INCIDENT, gate=gate)
    tool.run("restart_service|api-gateway|a")
    tool.run("scale_out|api-gateway|b")

    report = apply_answers("r1", {}, store=store, executor=lambda a, t: "ok")

    assert len(report["skipped"]) == 2
    assert report["summary"]["open"] == 2


def test_resume_writes_audit(env):
    store, gate, tmp_path = env
    RemediationTool(INCIDENT, gate=gate).run("restart_service|api-gateway|x")
    pending_id = store.list(run_id="r1")[0].id

    apply_answers(
        "r1", {pending_id: True}, store=store,
        executor=lambda a, t: "ok", audit_path=str(tmp_path / "audit.jsonl"),
    )

    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "restart_service" in audit
    assert '"approved": true' in audit


def test_unknown_run_is_empty_not_crash(env):
    store, gate, tmp_path = env
    report = apply_answers("no-such-run", {}, store=store)
    assert report["executed"] == []
    assert report["skipped"] == []


def test_render_mentions_outcome(env):
    store, gate, tmp_path = env
    RemediationTool(INCIDENT, gate=gate).run("restart_service|api-gateway|x")
    pending_id = store.list(run_id="r1")[0].id
    report = apply_answers("r1", {pending_id: False}, store=store)
    text = render(report)
    assert "已否决" in text
    assert "restart_service" in text


def test_open_pendings_only_returns_open(env):
    store, gate, tmp_path = env
    RemediationTool(INCIDENT, gate=gate).run("restart_service|api-gateway|x")
    pending_id = store.list(run_id="r1")[0].id
    store.resolve(pending_id, approved=True)

    assert open_pendings("r1", store=store) == []
