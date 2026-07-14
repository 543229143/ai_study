import json
import os
from pathlib import Path
from typing import Dict, Any

from ..llm_client import LLMClient
from .triage import TriageAgent
from .investigation import InvestigationAgent
from .postmortem import PostmortemAgent
from ..tools.log_search import LogSearchTool
from ..tools.metric_query import MetricQueryTool
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


def run_pipeline(incident_id: str) -> Dict[str, Any]:
    incident = load_incident(incident_id)
    llm = LLMClient()

    tools = {
        "log_search": LogSearchTool(incident),
        "metric_query": MetricQueryTool(incident),
        "runbook_lookup": RunbookTool(incident),
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

    return {
        "incident_id": incident_id,
        "service": incident.get("service", ""),
        "severity": incident.get("severity", ""),
        "plan": plan,
        "findings": findings,
        "report": report,
    }
