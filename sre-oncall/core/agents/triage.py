import ast
import json
from typing import Dict, Any, List
from ..llm_client import LLMClient

TRIAGE_PROMPT = """You are an SRE triage engineer. Analyze the following incident alert and create an ordered investigation plan.

Incident Alert:
{incident_json}

Available tools:
- log_search: Search log entries by keyword (e.g., "connection refused", "timeout")
- metric_query: Query time-series metrics (e.g., "cpu_usage", "db_pool_size", "latency")
- runbook_lookup: Look up runbook procedures (e.g., "DB pool exhausted", "OOM")

Output a Python list of {{"tool": "...", "query": "...", "reason": "..."}} objects, one per investigation step.
Order the steps to narrow down the root cause efficiently.

Example format:
```python
[
    {{"tool": "log_search", "query": "ERROR", "reason": "Identify the nature and frequency of errors"}},
    {{"tool": "metric_query", "query": "cpu", "reason": "Check if resource exhaustion correlates with the incident time"}},
    {{"tool": "runbook_lookup", "query": "high latency", "reason": "Find existing procedures for this error pattern"}}
]
```

Return ONLY the Python list, nothing else."""


class TriageAgent:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run(self, incident: Dict[str, Any]) -> List[Dict[str, str]]:
        incident_json = json.dumps(incident, ensure_ascii=False, indent=2)
        prompt = TRIAGE_PROMPT.format(incident_json=incident_json)
        messages = [{"role": "user", "content": prompt}]

        response = self.llm.think(messages=messages, temperature=0.0)
        if not response:
            return self._fallback_plan(incident)

        plan = self._parse_plan(response)
        return plan if plan else self._fallback_plan(incident)

    def _parse_plan(self, response: str) -> List[Dict]:
        import re
        match = re.search(r"```(?:python)?\s*(.*?)\s*```", response, re.DOTALL)
        code = match.group(1) if match else response
        try:
            return ast.literal_eval(code)
        except (ValueError, SyntaxError):
            return []

    def _fallback_plan(self, incident: Dict) -> List[Dict]:
        service = incident.get("service", "")
        return [
            {"tool": "log_search", "query": "ERROR|FATAL|CRITICAL", "reason": "Identify all severe error events"},
            {"tool": "metric_query", "query": "cpu", "reason": "Check resource utilization"},
            {"tool": "metric_query", "query": "memory", "reason": "Check for memory pressure"},
            {"tool": "metric_query", "query": "latency", "reason": "Verify response time degradation"},
            {"tool": "runbook_lookup", "query": service, "reason": f"Check {service} runbook for known issues"},
        ]
