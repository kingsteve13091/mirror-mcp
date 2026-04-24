# -*- coding: utf-8 -*-

"""Append-only audit trail for agent system operations.

The audit layer is intentionally separate from MCP Tool Execution Memory.  A
record may later be referenced by Memory Plane governance, but system
operations remain tagged with ``source_plane=system_op`` so they are never
confused with MCP recipe / guard evidence.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationAuditLog:
    def __init__(self, path: Path, *, max_recent: int = 300) -> None:
        self.path = Path(path)
        self.max_recent = int(max_recent)
        self._lock = threading.RLock()

    def append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        item = deepcopy(event)
        item.setdefault("audit_id", f"op-audit-{uuid.uuid4().hex[:12]}")
        item.setdefault("timestamp", utc_now())
        item.setdefault("source_plane", "system_op")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return item

    def recent(self, *, limit: int = 50, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), self.max_recent))
        if not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        text = line.strip()
                        if not text:
                            continue
                        try:
                            parsed = json.loads(text)
                        except Exception:
                            continue
                        if task_id and str(parsed.get("task_id", "")) != str(task_id):
                            continue
                        rows.append(parsed)
            except FileNotFoundError:
                return []
        return rows[-safe_limit:]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "size_bytes": os.path.getsize(self.path) if self.path.exists() else 0,
        }
