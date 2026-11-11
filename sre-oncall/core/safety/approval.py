"""安全闸门：高风险动作必须有人批准。

默认是 auto_deny —— 也就是说，**Agent 默认没有破坏性权限**。
要放开必须显式指定 mode，并且每一次请求都会落到审计日志。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

# 会改变生产状态的动作。新增动作时只改这里。
RISKY_ACTIONS = frozenset(
    {
        "restart_service",
        "scale_out",
        "rollback_deploy",
        "drain_node",
        "kill_process",
        "flush_cache",
        "disable_circuit_breaker",
    }
)

MODES = ("auto_deny", "auto_approve", "prompt")


@dataclass
class Decision:
    action: str
    target: str = ""
    reason: str = ""
    approved: bool = False
    mode: str = "auto_deny"
    decided_by: str = "system"
    ts: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def render(self) -> str:
        verdict = "APPROVED" if self.approved else "DENIED"
        return (
            f"[{verdict}] {self.action} target={self.target or '-'} "
            f"by={self.decided_by} mode={self.mode} reason={self.reason or '-'}"
        )


class ApprovalGate:
    def __init__(
        self,
        mode: str = "auto_deny",
        approver: Optional[Callable[[Decision], bool]] = None,
        audit_path: Optional[str] = None,
    ):
        if mode not in MODES:
            raise ValueError(f"unknown approval mode: {mode}（可选 {MODES}）")
        self.mode = mode
        self.approver = approver
        self.audit_path = audit_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
            "audit",
            "approvals.jsonl",
        )
        self._lock = threading.Lock()
        self.decisions: list = []

    def requires_approval(self, action: str) -> bool:
        return action in RISKY_ACTIONS

    def request(self, action: str, target: str = "", reason: str = "") -> Decision:
        if not self.requires_approval(action):
            decision = Decision(action, target, reason, approved=True, mode=self.mode, decided_by="policy")
            self._record(decision)
            return decision

        if self.mode == "auto_approve":
            approved, by = True, "auto_approve"
        elif self.mode == "prompt":
            approved, by = self._ask(Decision(action, target, reason, mode=self.mode)), "human"
        else:
            approved, by = False, "auto_deny"

        decision = Decision(action, target, reason, approved=approved, mode=self.mode, decided_by=by)
        self._record(decision)
        return decision

    # ---------- 内部 ----------

    def _ask(self, decision: Decision) -> bool:
        if self.approver is not None:
            return bool(self.approver(decision))
        print(f"\n⚠️  高风险操作待确认: {decision.action} → {decision.target}")
        if decision.reason:
            print(f"   理由: {decision.reason}")
        answer = input("   批准执行？[y/N] ").strip().lower()
        return answer in ("y", "yes")

    def _record(self, decision: Decision) -> None:
        self.decisions.append(decision)
        try:
            os.makedirs(os.path.dirname(self.audit_path), exist_ok=True)
            with self._lock, open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(decision), ensure_ascii=False) + "\n")
        except OSError as exc:  # 审计写失败不能拖垮主流程，但必须留痕
            print(f"[audit] 写入失败: {exc}")

    def summary(self) -> Dict[str, int]:
        return {
            "requests": len(self.decisions),
            "approved": sum(1 for d in self.decisions if d.approved),
            "denied": sum(1 for d in self.decisions if not d.approved),
        }
