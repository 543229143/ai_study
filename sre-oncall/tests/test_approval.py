import json
import os

import pytest

from core.safety.approval import ApprovalGate, Decision


def _gate(tmp_path, **kwargs):
    return ApprovalGate(audit_path=os.path.join(tmp_path, "audit.jsonl"), **kwargs)


def test_default_mode_denies_risky_action(tmp_path):
    gate = _gate(tmp_path)
    decision = gate.request("restart_service", "api-gateway", "连接池耗尽")
    assert decision.approved is False
    assert decision.decided_by == "auto_deny"


def test_non_risky_action_passes_by_policy(tmp_path):
    gate = _gate(tmp_path)
    decision = gate.request("query_metrics", "api-gateway")
    assert decision.approved is True
    assert decision.decided_by == "policy"


def test_auto_approve_mode(tmp_path):
    gate = _gate(tmp_path, mode="auto_approve")
    assert gate.request("rollback_deploy", "order-svc").approved is True


def test_prompt_mode_uses_injected_approver(tmp_path):
    seen = []

    def approver(decision: Decision) -> bool:
        seen.append(decision.action)
        return False

    gate = _gate(tmp_path, mode="prompt", approver=approver)
    decision = gate.request("scale_out", "pay-svc")
    assert seen == ["scale_out"]
    assert decision.approved is False
    assert decision.decided_by == "human"


def test_unknown_mode_rejected(tmp_path):
    with pytest.raises(ValueError):
        ApprovalGate(mode="whatever", audit_path=str(tmp_path / "a.jsonl"))


def test_audit_log_is_written(tmp_path):
    gate = _gate(tmp_path)
    gate.request("restart_service", "api-gateway", "连接池耗尽")
    gate.request("query_metrics", "api-gateway")

    lines = [json.loads(l) for l in open(gate.audit_path, encoding="utf-8") if l.strip()]
    assert len(lines) == 2
    assert lines[0]["action"] == "restart_service"
    assert lines[0]["approved"] is False
    assert lines[0]["reason"] == "连接池耗尽"
    assert "ts" in lines[0]


def test_summary_counts(tmp_path):
    gate = _gate(tmp_path, mode="auto_approve")
    gate.request("restart_service", "a")
    gate.request("query_metrics", "b")

    summary = gate.summary()
    assert summary == {"requests": 2, "approved": 2, "denied": 0}
