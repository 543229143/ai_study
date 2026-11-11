"""挂起队列：等人回答的高风险动作。

和"拒绝"的区别：
    拒绝  —— 当场结束，人回来之后只能自己动手；
    挂起  —— 记下动作 + 上下文 + 会话，人回来接着干，等待期间没有进程。

存盘格式是一行一条的 JSONL，和审计日志一样：只追加、可回放、出问题好排查。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

OPEN = "open"
APPROVED = "approved"
DENIED = "denied"


@dataclass
class Pending:
    action: str
    target: str = ""
    reason: str = ""
    run_id: str = ""
    incident_id: str = ""
    # 会话 = 这一轮调查的现场快照 id，回答后靠它续跑，而不是重跑整个调查
    session: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = OPEN
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    resolved_at: Optional[str] = None
    by: Optional[str] = None
    note: str = ""


class PendingStore:
    """挂起队列。一个进程一个实例，写盘加锁。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data",
            "pending",
            "pending.jsonl",
        )
        self._lock = threading.Lock()
        self._items: Dict[str, Pending] = {}
        self._load()

    # ---------- 读写 ----------

    def add(self, pending: Pending) -> Pending:
        with self._lock:
            self._items[pending.id] = pending
            self._append(pending)
        return pending

    def get(self, pending_id: str) -> Optional[Pending]:
        return self._items.get(pending_id)

    def list(self, run_id: Optional[str] = None, status: Optional[str] = OPEN) -> List[Pending]:
        items = list(self._items.values())
        if run_id:
            items = [p for p in items if p.run_id == run_id]
        if status:
            items = [p for p in items if p.status == status]
        return sorted(items, key=lambda p: p.created_at)

    def resolve(self, pending_id: str, approved: bool, by: str = "human", note: str = "") -> Pending:
        pending = self._items.get(pending_id)
        if pending is None:
            raise KeyError(f"没有这条挂起：{pending_id}")
        if pending.status != OPEN:
            return pending  # 幂等：重复回答不重复执行
        pending.status = APPROVED if approved else DENIED
        pending.resolved_at = datetime.now().isoformat(timespec="seconds")
        pending.by = by
        pending.note = note
        with self._lock:
            self._append(pending)
        return pending

    def summary(self, run_id: Optional[str] = None) -> Dict[str, int]:
        items = self.list(run_id=run_id, status=None)
        return {
            "total": len(items),
            "open": sum(1 for p in items if p.status == OPEN),
            "approved": sum(1 for p in items if p.status == APPROVED),
            "denied": sum(1 for p in items if p.status == DENIED),
        }

    # ---------- 内部 ----------

    def _append(self, pending: Pending) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(pending), ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"[pending] 写入失败: {exc}")

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    # 同一 id 后写的覆盖先写的（状态变更就是这么落盘的）
                    self._items[row["id"]] = Pending(**{k: v for k, v in row.items() if k in Pending.__annotations__})
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"[pending] 读取失败，按空队列继续: {exc}")
