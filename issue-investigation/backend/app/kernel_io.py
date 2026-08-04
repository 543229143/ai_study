"""JSON 读写工具（原子写），供平台与内核共用。"""
from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path


def _json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def read_json(path: Path, default=None):
    p = Path(path)
    if not p.is_file():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="." + p.name + ".", dir=str(p.parent))
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, p)


def read_text(path: Path, default: str = "") -> str:
    p = Path(path)
    if not p.is_file():
        return default
    return p.read_text(encoding="utf-8")
