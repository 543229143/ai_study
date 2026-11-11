import json
import os
import uuid
from pathlib import Path
from typing import Dict, Any

from ..llm_client import LLMClient
from .triage import TriageAgent
from .investigation import InvestigationAgent
from .postmortem import PostmortemAgent
from ..runs import save_run
from ..safety.approval import ApprovalGate
from ..safety.pending import PendingStore
from ..tools.log_search import LogSearchTool
from ..tools.metric_query import MetricQueryTool
from ..tools.remediation import RemediationTool
from ..tools.runbook import RunbookTool

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def load_incident(incident_id: str) -> Dict[str, Any]:
    incident_path = DATA_DIR / "incidents" / f"{incident_id}.json"
    with open(incident_path, "r") as f:
        return json.load(f)


def list_incidents() -> list:
    incidents_dir = DATA_DIR / "incidents"
    return [
        p.stem
        for p in incidents_dir.glob("*.json")
        if p.stem != "__init__"
    ]


def run_pipeline(incident_id: str, approval_mode: str = None, run_id: str = None) -> Dict[str, Any]:
    incident = load_incident(incident_id)
    llm = LLMClient()

    # 一轮调查 = 一个 run_id；它同时是"会话"，回答后靠它续跑
    run_id = run_id or uuid.uuid4().hex[:8]
    pending = PendingStore()

    # 高风险动作默认拒绝：Agent 只有"提议权"，没有"执行权"
    gate = ApprovalGate(
        mode=approval_mode or os.getenv("SRE_APPROVAL_MODE", "auto_deny"),
        pending=pending,
        run_id=run_id,
        incident_id=incident_id,
        session=run_id,
    )

    tools = {
        "log_search": LogSearchTool(incident),
        "metric_query": MetricQueryTool(incident),
        "runbook_lookup": RunbookTool(incident),
        "remediation": RemediationTool(incident, gate=gate),
    }

    print(f"🔍 STAGE 1: TRIAGE — Generating investigation plan")
    triage = TriageAgent(llm)
    plan = triage.run(incident)
    for i, step in enumerate(plan, 1):
        print(f"  {i}. [{step['tool']}] {step['query']} — {step['reason']}")

    print(f"\n🔎 STAGE 2: INVESTIGATION — Executing ReAct tool loop")
    investigation = InvestigationAgent(llm)
    findings = investigation.run(plan, incident, tools)
    print(f"  Root cause: {findings.get('root_cause', 'Not determined')}")
    print(f"  Evidence collected: {len(findings.get('evidence', []))} items")

    print(f"\n📝 STAGE 3: POST-MORTEM — Reflection (draft → critique → revise)")
    postmortem = PostmortemAgent(llm)
    report = postmortem.run(incident, findings)
    print(f"  Report generated ({len(report)} chars)")

    approval = gate.summary()
    print(f"\n🔐 APPROVAL — {approval['requests']} 次请求, "
          f"{approval['approved']} 批准, {approval['denied']} 拒绝 "
          f"(mode={gate.mode}, audit={gate.audit_path})")

    # 现场快照：挂起之后靠它续跑，不重跑调查
    snapshot_path = save_run(
        run_id, incident_id, findings,
        service=incident.get("service", ""),
        severity=incident.get("severity", ""),
    )

    waiting = pending.summary(run_id=run_id)
    if waiting["open"]:
        print(f"\n⏸  有 {waiting['open']} 个动作等你拍板（等待期间没有进程在跑）")
        print(f"   回答：python3 core/cli.py answer {run_id}")

    return {
        "run_id": run_id,
        "snapshot": snapshot_path,
        "pending": waiting,
        "incident_id": incident_id,
        "approval": approval,
        "service": incident.get("service", ""),
        "severity": incident.get("severity", ""),
        "plan": plan,
        "findings": findings,
        "report": report,
    }
