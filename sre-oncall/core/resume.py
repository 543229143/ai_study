"""续跑：把挂起的动作接回原现场。

流程和"阻塞等人"完全不同：

    挂起时：  记 pending(含 run_id / session) → 进程退出，零 Token
    人回来：  answer → 取出 pending → 按答案执行或否决 → 落审计 → 结束

不重跑调查，因为调查结果已经在现场快照里。
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

from .runs import load_run
from .safety.approval import ApprovalGate
from .safety.pending import PendingStore
from .tools.remediation import RemediationTool


def open_pendings(run_id: str, store: Optional[PendingStore] = None) -> List:
    store = store or PendingStore()
    return store.list(run_id=run_id, status="open")


def apply_answers(
    run_id: str,
    answers: Dict[str, bool],
    store: Optional[PendingStore] = None,
    executor: Optional[Callable[[str, str], str]] = None,
    by: str = "human",
    audit_path: Optional[str] = None,
) -> Dict[str, object]:
    """按 {pending_id: 是否批准} 处理挂起项。

    批准 → 过闸门执行（闸门用 auto_approve，因为人已经批过了，审计照样留痕）
    否决 → 只记结论，不执行
    """
    store = store or PendingStore()
    snapshot = load_run(run_id) or {}
    incident = {"incident_id": snapshot.get("incident_id", ""), "service": _service_of(snapshot)}

    # 人已经批过了，这里只是执行；审计要记成"人"，不能记成"自动批准"
    gate = ApprovalGate(
        mode="auto_approve",
        audit_path=audit_path or _audit_path(),
        run_id=run_id,
        decided_by=by,
    )
    tool = RemediationTool(incident, gate=gate, executor=executor)

    executed, denied, skipped = [], [], []
    for pending in store.list(run_id=run_id, status="open"):
        if pending.id not in answers:
            skipped.append(pending.id)
            continue
        approved = answers[pending.id]
        store.resolve(pending.id, approved=approved, by=by)
        if not approved:
            denied.append({"id": pending.id, "action": pending.action, "target": pending.target})
            continue
        result = tool.run(f"{pending.action}|{pending.target}|{pending.reason}")
        executed.append({"id": pending.id, "action": pending.action, "target": pending.target, "result": result})

    return {
        "run_id": run_id,
        "incident_id": snapshot.get("incident_id", ""),
        "executed": executed,
        "denied": denied,
        "skipped": skipped,
        "summary": store.summary(run_id=run_id),
    }


def render(report: Dict[str, object]) -> str:
    lines = [f"续跑 {report['run_id']}（{report['incident_id'] or '未知事件'}）"]
    for item in report["executed"]:
        lines.append(f"  ✅ 已执行 {item['action']} → {item['target']}：{item['result']}")
    for item in report["denied"]:
        lines.append(f"  ⛔ 已否决 {item['action']} → {item['target']}，请人工处理或给出建议步骤")
    for pending_id in report["skipped"]:
        lines.append(f"  ⏸  仍未回答 {pending_id}")
    s = report["summary"]
    lines.append(f"  合计 {s['total']} 条：批准 {s['approved']}，否决 {s['denied']}，未答 {s['open']}")
    return "\n".join(lines)


def _service_of(snapshot: Dict) -> str:
    findings = snapshot.get("findings") or {}
    return findings.get("service", "") or snapshot.get("service", "")


def _audit_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "audit", "approvals.jsonl"
    )
