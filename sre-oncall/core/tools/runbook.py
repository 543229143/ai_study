import os
import glob
import yaml
from typing import List, Dict, Any


class RunbookTool:
    name = "runbook_lookup"
    description = (
        "Look up incident response runbooks for known error patterns. "
        "Returns step-by-step remediation procedures. "
        "Use this when you need to know how to resolve a known issue."
    )

    def __init__(self, incident: Dict[str, Any], runbook_dir: str = None):
        self._service = incident.get("service", "")
        self._runbooks: Dict[str, Any] = {}

        if runbook_dir is None:
            runbook_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "runbooks"
            )

        for yaml_file in glob.glob(os.path.join(runbook_dir, "*.yaml")):
            with open(yaml_file, "r") as f:
                data = yaml.safe_load(f)
                if data and "service" in data:
                    self._runbooks[data["service"]] = data

    def run(self, error_pattern: str) -> str:
        pattern_lower = error_pattern.strip().lower()

        for service, book in self._runbooks.items():
            procedures = book.get("procedures", [])
            for proc in procedures:
                triggers = proc.get("triggers", [])
                for trigger in triggers:
                    if pattern_lower in trigger.lower():
                        return self._format_runbook(book, proc)

        for service, book in self._runbooks.items():
            if pattern_lower in service.lower() or pattern_lower in self._service.lower():
                procedures = book.get("procedures", [])
                if procedures:
                    return self._format_runbook(book, procedures[0])

        available = ", ".join(self._runbooks.keys()) if self._runbooks else "none"
        return (
            f'No runbook matching "{error_pattern}" found.\n'
            f"Available runbook services: {available}"
        )

    def _format_runbook(self, book: Dict, proc: Dict) -> str:
        steps = proc.get("steps", [])
        step_lines = "\n".join(
            f"  {s.get('seq', i+1)}. {s.get('action', '')}"
            for i, s in enumerate(steps)
        )
        return (
            f"Runbook: {book.get('service', '')} — {proc.get('name', '')}\n"
            f"Severity: {proc.get('severity', 'N/A')}\n"
            f"Steps:\n{step_lines}"
        )
