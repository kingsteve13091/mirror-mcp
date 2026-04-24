#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Lightweight smoke checks for Agent Runtime endpoints.

This script verifies that the Agent Runtime layer is reachable without touching
the MCP configuration source of truth.  It is intentionally conservative:

- create a lightweight task
- list tasks
- cancel the created task
- probe a safe system operation policy path with `log_read`
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests


BASE_URL = "http://127.0.0.1:8000"


def pretty(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def require_ok(response: requests.Response, label: str) -> dict[str, Any]:
    if not response.ok:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")
    return response.json()


def main() -> int:
    print("[agent-runtime-smoke] checking capabilities...")
    capabilities = require_ok(requests.get(f"{BASE_URL}/api/agent/capabilities", timeout=20), "capabilities")
    print(pretty({
        "ok": capabilities.get("ok"),
        "system_operation_capabilities": len(capabilities.get("system_operation_capabilities") or []),
        "task_runtime": capabilities.get("task_runtime"),
    }))

    print("[agent-runtime-smoke] creating lightweight task...")
    create_payload = {
        "goal": "Smoke check agent runtime without changing MCP configuration",
        "client_id": "agent-runtime-smoke",
        "workspace_root": "",
        "attachments": [],
        "mode": "agent",
    }
    created = require_ok(
        requests.post(f"{BASE_URL}/api/agent/tasks", json=create_payload, timeout=20),
        "create task",
    )
    task_id = str((created.get("task") or {}).get("task_id") or "")
    if not task_id:
        raise RuntimeError("Task creation did not return task_id")
    print(pretty({"task_id": task_id, "status": created.get("task", {}).get("status")}))

    print("[agent-runtime-smoke] listing tasks...")
    task_list = require_ok(
        requests.get(f"{BASE_URL}/api/agent/tasks", params={"limit": 5, "client_id": "agent-runtime-smoke"}, timeout=20),
        "list tasks",
    )
    print(pretty({
        "count": task_list.get("count"),
        "status_counts": task_list.get("status_counts"),
    }))

    print("[agent-runtime-smoke] probing safe system operation...")
    op_payload = {
        "action_type": "log_read",
        "payload": {
            "path": "web_interface/backend/mcp_chat.log",
            "tail": 5,
        },
        "client_id": "agent-runtime-smoke",
        "task_id": task_id,
        "workspace_root": "",
        "policy_confirmed": False,
    }
    system_result = require_ok(
        requests.post(f"{BASE_URL}/api/system-ops/execute", json=op_payload, timeout=30),
        "system operation",
    )
    print(pretty({
        "ok": system_result.get("ok"),
        "action_type": system_result.get("action_type"),
        "decision": system_result.get("decision"),
    }))

    print("[agent-runtime-smoke] cancelling task...")
    cancelled = require_ok(
        requests.post(f"{BASE_URL}/api/agent/tasks/{task_id}/cancel", timeout=20),
        "cancel task",
    )
    print(pretty({"task_id": task_id, "status": cancelled.get("task", {}).get("status")}))

    print("[agent-runtime-smoke] done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[agent-runtime-smoke] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
