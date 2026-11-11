"""修复动作工具：模型可以提议，但破坏性动作必须过审批闸门。

设计要点：
- 模型只负责"提议"（action / target / reason），不持有执行权限；
- 是否执行由 ApprovalGate 决定，默认拒绝；
- 每次提议和结果都写审计日志，事后可追溯。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..safety.approval import ApprovalGate


class RemediationTool:
    name = "remediation"
    description = (
        "Propose a remediation action for the incident (e.g. restart_service, scale_out, "
        "rollback_deploy). Destructive actions require human approval and are denied by default. "
        "Format: action|target|reason"
    )

    def __init__(
        self,
        incident: Dict[str, Any],
        gate: Optional[ApprovalGate] = None,
        executor: Optional[Callable[[str, str], str]] = None,
    ):
        self._incident = incident
        self.gate = gate or ApprovalGate()
        self._executor = executor or self._simulate

    def run(self, query: str) -> str:
        parts = [p.strip() for p in str(query).split("|")]
        action = parts[0] if parts and parts[0] else ""
        target = parts[1] if len(parts) > 1 and parts[1] else self._incident.get("service", "")
        reason = parts[2] if len(parts) > 2 else ""

        if not action:
            return "remediation failed: 缺少 action，格式应为 action|target|reason"

        decision = self.gate.request(action, target, reason)
        if not decision.approved:
            return (
                f"remediation DENIED: {action} → {target} "
                f"(mode={decision.mode}, decided_by={decision.decided_by})。"
                f"请改为给出建议步骤，或升级给人工处理。"
            )

        try:
            effect = self._executor(action, target)
        except Exception as exc:  # noqa: BLE001
            return f"remediation FAILED: {action} → {target}: {exc}"
        return f"remediation EXECUTED: {action} → {target} | {effect}"

    @staticmethod
    def _simulate(action: str, target: str) -> str:
        # 演示环境没有真实执行器，明确标注"模拟"，避免被误读成真的动了生产
        return f"模拟执行（未接触真实环境）: {action} on {target}"
