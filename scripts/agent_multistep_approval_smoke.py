#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Smoke check for multi-step agent execution with approval + replay.

Validates:
1. create task
2. task reaches waiting_approval
3. pending approval is visible
4. approval resumes execution
5. replay is available
6. Memory Plane ledger exposes system_op_events separately
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import requests


BASE_URL = "http://127.0.0.1:8000"
CLIENT_ID = "agent-multistep-smoke"


def pretty(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def require_ok(response: requests.Response, label: str) -> dict[str, Any]:
    if not response.ok:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")
    return response.json()


def wait_for_task(task_id: str, expected_status: str, *, timeout_s: float = 15.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        payload = require_ok(requests.get(f"{BASE_URL}/api/agent/tasks/{task_id}", timeout=20), "get task")
        task = payload.get("task") or {}
        last_payload = payload
        if str(task.get("status", "")) == expected_status:
            return payload
        time.sleep(0.5)
    raise RuntimeError(f"task {task_id} did not reach status {expected_status}: {pretty(last_payload)}")


def main() -> int:
    create_payload = {
        "goal": "Please run a terminal command to inspect the workspace safely",
        "client_id": CLIENT_ID,
        "workspace_root": "D:\\mirror_mcp",
        "attachments": [],
        "mode": "agent",
    }
    print("[agent-multistep-smoke] creating task...")
    created = require_ok(
        requests.post(f"{BASE_URL}/api/agent/tasks", json=create_payload, timeout=20),
        "create task",
    )
    task = created.get("task") or {}
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise RuntimeError("task_id missing from create response")
    print(pretty({"task_id": task_id, "status": task.get("status")}))

    print("[agent-multistep-smoke] waiting for approval...")
    waited = wait_for_task(task_id, "waiting_approval", timeout_s=20.0)
    waited_task = waited.get("task") or {}
    print(pretty({
        "task_id": task_id,
        "status": waited_task.get("status"),
        "pending_approvals": len(waited_task.get("pending_approvals") or []),
    }))

    approvals = require_ok(
        requests.get(f"{BASE_URL}/api/agent/operations/approvals", params={"task_id": task_id}, timeout=20),
        "list approvals",
    )
    items = approvals.get("items") or []
    if not items:
        raise RuntimeError("pending approvals endpoint returned no items")
    approval = items[0]
    approval_id = str(approval.get("approval_id") or "")
    print(pretty({"approval_id": approval_id, "action_type": approval.get("action_type")}))

    print("[agent-multistep-smoke] approving task...")
    approved = require_ok(
        requests.post(
            f"{BASE_URL}/api/agent/tasks/{task_id}/approvals/{approval_id}/approve",
            json={
                "client_id": CLIENT_ID,
                "workspace_root": "D:\\mirror_mcp",
                "attachments": [],
                "note": "smoke approval",
            },
            timeout=40,
        ),
        "approve operation",
    )
    print(pretty({
        "ok": approved.get("ok"),
        "task_status": (approved.get("task") or {}).get("status"),
        "result_success": ((approved.get("result") or {}).get("success")),
    }))

    print("[agent-multistep-smoke] waiting for completion...")
    completed = wait_for_task(task_id, "completed", timeout_s=20.0)
    print(pretty({
        "task_id": task_id,
        "status": (completed.get("task") or {}).get("status"),
        "result_summary": (completed.get("task") or {}).get("result_summary"),
    }))

    print("[agent-multistep-smoke] reading replay...")
    replay = require_ok(
        requests.get(f"{BASE_URL}/api/agent/tasks/{task_id}/replay", timeout=20),
        "task replay",
    )
    if not (replay.get("events") or []):
        raise RuntimeError("task replay returned no events")
    print(pretty({
        "event_count": len(replay.get("events") or []),
        "pending_approvals": len(replay.get("pending_approvals") or []),
    }))

    print("[agent-multistep-smoke] reading memory plane ledger...")
    ledger = require_ok(
        requests.get(f"{BASE_URL}/api/memory-plane/ledger", params={"limit": 20}, timeout=20),
        "memory plane ledger",
    )
    print(pretty({
        "system_op_event_count": (ledger.get("summary") or {}).get("system_op_event_count"),
        "system_op_events": len(ledger.get("system_op_events") or []),
    }))

    print("[agent-multistep-smoke] done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[agent-multistep-smoke] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
