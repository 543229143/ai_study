import json
import os
import threading
from datetime import datetime
from typing import List, Dict, Optional


class StockMemory:
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "memory")
        os.makedirs(data_dir, exist_ok=True)
        self._data_dir = data_dir
        self._lock = threading.Lock()

    def _load(self, filename: str, default=None) -> any:
        path = os.path.join(self._data_dir, filename)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return default or []

    def _save(self, filename: str, data):
        with self._lock:
            path = os.path.join(self._data_dir, filename)
            with open(path, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def add_watchlist(self, entry: str) -> str:
        code, name = entry.strip().split("|", 1)
        items = self._load("watchlist.json", [])
        for item in items:
            if item["code"] == code:
                return f"{code} {name} 已在关注列表中"
        items.append({"code": code, "name": name, "added_at": datetime.now().isoformat()})
        self._save("watchlist.json", items)
        return f"已添加关注: {code} {name}"

    def remove_watchlist(self, code: str) -> str:
        items = self._load("watchlist.json", [])
        items = [i for i in items if i["code"] != code]
        self._save("watchlist.json", items)
        return f"已取消关注: {code}"

    def get_watchlist(self) -> str:
        items = self._load("watchlist.json", [])
        if not items:
            return "关注列表为空"
        return "\n".join(f"- {i['code']} {i['name']}" for i in items)

    def save_analysis(self, entry: str) -> str:
        parts = entry.strip().split("|", 2)
        code, question, summary = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
        history = self._load("history.json", {})
        if code not in history:
            history[code] = []
        history[code].append({
            "question": question,
            "summary": summary[:200],
            "timestamp": datetime.now().isoformat(),
        })
        self._save("history.json", history)
        return f"已保存 {code} 的分析记录"

    def get_history(self, code: str) -> str:
        history = self._load("history.json", {})
        entries = history.get(code, [])
        if not entries:
            return f"{code} 无历史分析记录"
        lines = []
        for e in entries[-5:]:
            lines.append(f"[{e['timestamp'][:10]}] {e['question']} — {e['summary']}")
        return "\n".join(lines)

    def get_last_analysis(self, code: str) -> str:
        history = self._load("history.json", {})
        entries = history.get(code, [])
        if not entries:
            return "无"
        last = entries[-1]
        return f"[{last['timestamp'][:10]}] {last['question']} — {last['summary']}"

    def set_preference(self, entry: str) -> str:
        key, value = entry.strip().split("=", 1)
        prefs = self._load("preferences.json", {})
        prefs[key.strip()] = value.strip()
        self._save("preferences.json", prefs)
        return f"偏好已设置: {key.strip()}={value.strip()}"

    def get_preferences(self) -> str:
        prefs = self._load("preferences.json", {})
        if not prefs:
            return "无偏好设置"
        return "\n".join(f"- {k}: {v}" for k, v in prefs.items())
