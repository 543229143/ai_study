"""一轮调查的现场快照。

挂起之后要能"接着干"，靠的就是这份快照：不重跑调查，只把现场取回来继续。
存成一份 JSON，人看得懂、坏了能手工改。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


def _dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "runs"
    )


def save_run(run_id: str, incident_id: str, findings: Dict[str, Any], **extra: Any) -> str:
    os.makedirs(_dir(), exist_ok=True)
    path = os.path.join(_dir(), f"{run_id}.json")
    snapshot = {
        "run_id": run_id,
        "incident_id": incident_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "findings": findings,
        **extra,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return path


def load_run(run_id: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(_dir(), f"{run_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_runs() -> list:
    if not os.path.isdir(_dir()):
        return []
    return sorted(name[:-5] for name in os.listdir(_dir()) if name.endswith(".json"))
