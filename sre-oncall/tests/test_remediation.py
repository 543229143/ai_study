import os

from core.safety.approval import ApprovalGate
from core.tools.remediation import RemediationTool

INCIDENT = {"incident_id": "db_pool_exhaustion", "service": "api-gateway"}


def _gate(tmp_path, mode="auto_deny"):
    return ApprovalGate(mode=mode, audit_path=os.path.join(tmp_path, "audit.jsonl"))


def test_denied_action_never_reaches_executor(tmp_path):
    calls = []
    tool = RemediationTool(
        INCIDENT,
        gate=_gate(tmp_path),
        executor=lambda action, target: calls.append(action) or "done",
    )
    result = tool.run("restart_service|api-gateway|连接池耗尽")

    assert "DENIED" in result
    assert calls == []  # 关键：拒绝之后执行器一次都不能被调用


def test_approved_action_executes(tmp_path):
    calls = []
    tool = RemediationTool(
        INCIDENT,
        gate=_gate(tmp_path, mode="auto_approve"),
        executor=lambda action, target: calls.append((action, target)) or "done",
    )
    result = tool.run("restart_service|api-gateway|连接池耗尽")

    assert "EXECUTED" in result
    assert calls == [("restart_service", "api-gateway")]


def test_default_target_is_incident_service(tmp_path):
    calls = []
    tool = RemediationTool(
        INCIDENT,
        gate=_gate(tmp_path, mode="auto_approve"),
        executor=lambda action, target: calls.append(target) or "done",
    )
    tool.run("scale_out||扩容")
    assert calls == ["api-gateway"]


def test_simulated_executor_is_labelled(tmp_path):
    tool = RemediationTool(INCIDENT, gate=_gate(tmp_path, mode="auto_approve"))
    result = tool.run("scale_out|api-gateway|扩容")
    assert "模拟执行" in result


def test_missing_action_reports_error(tmp_path):
    tool = RemediationTool(INCIDENT, gate=_gate(tmp_path))
    assert "缺少 action" in tool.run("|api-gateway|reason")


def test_executor_failure_is_reported(tmp_path):
    def boom(action, target):
        raise RuntimeError("no permission")

    tool = RemediationTool(INCIDENT, gate=_gate(tmp_path, mode="auto_approve"), executor=boom)
    result = tool.run("restart_service|api-gateway|x")
    assert "FAILED" in result
    assert "no permission" in result
