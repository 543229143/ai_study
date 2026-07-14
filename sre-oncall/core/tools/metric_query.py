from typing import Dict, Any


class MetricQueryTool:
    name = "metric_query"
    description = (
        "Query time-series metrics by name. "
        "Returns metric values over the incident window. "
        "Use this to check resource utilization, latency, error rates, etc."
    )

    def __init__(self, incident: Dict[str, Any]):
        self._metrics = incident.get("metrics", {})

    def run(self, metric_name: str) -> str:
        metric_name_lower = metric_name.strip().lower()

        for key, data in self._metrics.items():
            if metric_name_lower in key.lower():
                values = data.get("values", [])
                unit = data.get("unit", "")
                description = data.get("description", key)

                if len(values) > 20:
                    displayed = values[:20]
                    omitted = len(values) - 20
                    value_str = f"[{', '.join(map(str, displayed))}, ... (+{omitted} more points)]"
                else:
                    value_str = f"[{', '.join(map(str, values))}]"

                return (
                    f"Metric: {description}\n"
                    f"Unit: {unit}\n"
                    f"Values: {value_str}"
                )

        available = ", ".join(self._metrics.keys())
        return (
            f'No metric matching "{metric_name}" found.\n'
            f"Available metrics: {available}"
        )
