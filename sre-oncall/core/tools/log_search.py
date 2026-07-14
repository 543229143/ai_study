import re
from typing import Dict, Any, List


class LogSearchTool:
    name = "log_search"
    description = (
        "Search incident log entries by keyword or pattern. "
        "Returns matching log lines with timestamps. "
        "Use this to find error messages, stack traces, and warning signs in logs."
    )

    def __init__(self, incident: Dict[str, Any]):
        self._logs = incident.get("logs", [])

    def run(self, query: str) -> str:
        matches = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        for entry in self._logs:
            level = entry.get("level", "INFO")
            timestamp = entry.get("timestamp", "")
            message = entry.get("message", "")
            source = entry.get("source", "")

            if pattern.search(message) or pattern.search(level):
                matches.append(
                    f"[{timestamp}] [{level}] [{source}] {message}"
                )

        if not matches:
            return f'No log entries matching "{query}" found.'

        return (
            f"Found {len(matches)} matching log entries:\n"
            + "\n".join(matches)
        )
