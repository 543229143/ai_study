import json
import os
from datetime import datetime
from typing import List, Dict, Optional


class ContextManager:
    def __init__(self, max_tokens: int = 8000):
        self._turns: List[Dict] = []
        self._max_tokens = max_tokens

    def add_turn(self, role: str, content: str):
        self._turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        self._auto_compress()

    def get_context(self) -> List[Dict]:
        return [{"role": t["role"], "content": t["content"]} for t in self._turns]

    def _auto_compress(self):
        total = sum(len(t["content"]) for t in self._turns)
        if total > self._max_tokens * 4:
            self._compress()

    def _compress(self):
        if len(self._turns) < 6:
            return
        to_compress = self._turns[:-4]
        compressed_content = "\n".join(
            f"[{t['timestamp'][:10]}] {t['role']}: {t['content'][:100]}..."
            for t in to_compress
        )
        self._turns = [
            {"role": "system", "content": f"上下文压缩摘要:\n{compressed_content}", "timestamp": datetime.now().isoformat()}
        ] + self._turns[-4:]

    def clear(self):
        self._turns.clear()

    def summarize(self) -> str:
        if not self._turns:
            return "无上下文"
        return "\n".join(
            f"[{t['timestamp'][:10]}] {t['role']}: {t['content'][:100]}"
            for t in self._turns
        )

    def stats(self) -> str:
        total_chars = sum(len(t["content"]) for t in self._turns)
        return f"上下文: {len(self._turns)} 轮对话, 约 {total_chars // 4} tokens"
