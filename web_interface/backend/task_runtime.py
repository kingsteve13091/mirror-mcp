# -*- coding: utf-8 -*-

"""Agent run runtime for long-running and multi-step tasks.

This runtime remains backward-compatible with the existing AgentTask API while
upgrading the stored object into a richer run-oriented structure.  Existing
frontend/API callers can continue using task_id / steps / replay_events, while
new agent runtime features can build on:

- run_id / run_kind / lifecycle
- execution_events as the canonical event stream
- scheduler metadata placeholders
- parent/child run relationships
- richer status transitions without collapsing System Operation Plane into
  MCP Tool Plane or Memory Plane
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


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class AgentTaskRuntime:
    def __init__(self, *, path: Path, max_size: int = 300) -> None:
        self.path = Path(path)
        self.max_size = int(max_size)
        self._lock = threading.RLock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self.load()

    def create_task(
        self,
        *,
        client_id: str,
        goal: str,
        plan: Dict[str, Any],
        mode: str = "agent",
        workspace_root: str = "",
        parent_run_id: str = "",
        run_kind: str = "interactive_chat",
        scheduler_id: str = "",
        trigger: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        task_id = _new_id("agent-task")
        run_id = _new_id("agent-run")
        now = utc_now()
        normalized_steps = self._normalize_steps(deepcopy(plan.get("steps", [])) if isinstance(plan, dict) else [])
        task = {
            "task_id": task_id,
            "run_id": run_id,
            "client_id": str(client_id or ""),
            "goal": str(goal or ""),
            "mode": str(mode or "agent"),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "started_at": "",
            "completed_at": "",
            "workspace_root": str(workspace_root or ""),
            "plan": deepcopy(plan),
            "plan_version": str(plan.get("plan_version", "")) if isinstance(plan, dict) else "",
            "steps": normalized_steps,
            "current_step_index": 0,
            "observations": [],
            "verification": {},
            "result_summary": {},
            "source_plane_counts": {"mcp": 0, "system_op": 0, "agent": 0},
            "pending_approvals": [],
            "replay_events": [],
            "execution_events": [],
            "lifecycle": {
                "phase": "created",
                "phase_history": [
                    {
                        "phase": "created",
                        "timestamp": now,
                        "reason": "task_created",
                    }
                ],
                "last_error": "",
                "retry_count": 0,
                "cancel_requested": False,
                "paused": False,
            },
            "run_kind": str(run_kind or "interactive_chat"),
            "scheduler": {
                "scheduler_id": str(scheduler_id or ""),
                "trigger": deepcopy(trigger or {}),
                "scheduled_for": "",
                "last_heartbeat_at": "",
            },
            "relationships": {
                "parent_run_id": str(parent_run_id or ""),
                "child_run_ids": [],
            },
        }
        with self._lock:
            self._tasks[task_id] = task
            self._append_event_locked(
                task,
                "run_created",
                {
                    "goal": goal,
                    "mode": mode,
                    "workspace_root": workspace_root,
                    "run_kind": run_kind,
                },
                source_plane="agent",
            )
            self._trim()
            self.persist()
        return deepcopy(task)

    def _normalize_steps(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, raw_step in enumerate(steps or []):
            if not isinstance(raw_step, dict):
                continue
            step = deepcopy(raw_step)
            step_id = str(step.get("step_id") or f"step-{index + 1}")
            step["step_id"] = step_id
            step.setdefault("title", step.get("action") or step.get("kind") or f"Step {index + 1}")
            step.setdefault("kind", "analysis")
            step.setdefault("action", "")
            step.setdefault("status", "pending")
            step.setdefault("started_at", "")
            step.setdefault("completed_at", "")
            step.setdefault("result_summary", {})
            step.setdefault("error", "")
            step.setdefault("attempt_count", 0)
            step.setdefault("requires_confirmation", False)
            normalized.append(step)
        return normalized

    def _find_step_locked(self, task: Dict[str, Any], step_id: str) -> tuple[int, Optional[Dict[str, Any]]]:
        for index, step in enumerate(task.get("steps", [])):
            if str(step.get("step_id", "")) == str(step_id):
                return index, step
        return -1, None

    def _append_event_locked(
        self,
        task: Dict[str, Any],
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        source_plane: str = "agent",
        step_id: str = "",
        event_kind: str = "lifecycle",
    ) -> Dict[str, Any]:
        item = {
            "event_id": _new_id("run-event"),
            "timestamp": utc_now(),
            "event": event,
            "event_kind": event_kind,
            "source_plane": source_plane,
            "step_id": step_id,
            "task_id": task.get("task_id", ""),
            "run_id": task.get("run_id", ""),
            "payload": deepcopy(payload or {}),
        }
        task.setdefault("execution_events", []).append(item)
        task["execution_events"] = task.get("execution_events", [])[-1000:]

        replay_item = {
            "event_id": item["event_id"],
            "timestamp": item["timestamp"],
            "event": event,
            "source_plane": source_plane,
            "step_id": step_id,
            "payload": deepcopy(payload or {}),
        }
        task.setdefault("replay_events", []).append(replay_item)
        task["replay_events"] = task.get("replay_events", [])[-500:]
        task["updated_at"] = utc_now()
        return deepcopy(item)

    def append_replay_event(
        self,
        task_id: str,
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        source_plane: str = "agent",
        step_id: str = "",
        event_kind: str = "lifecycle",
    ) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            item = self._append_event_locked(
                task,
                event,
                payload,
                source_plane=source_plane,
                step_id=step_id,
                event_kind=event_kind,
            )
            self.persist()
            return item

    def _transition_phase_locked(self, task: Dict[str, Any], phase: str, *, reason: str = "", error: str = "") -> None:
        lifecycle = task.setdefault("lifecycle", {})
        current_phase = str(lifecycle.get("phase", "") or "")
        if current_phase != phase:
            lifecycle["phase"] = phase
            lifecycle.setdefault("phase_history", []).append(
                {
                    "phase": phase,
                    "timestamp": utc_now(),
                    "reason": reason or "",
                }
            )
        if error:
            lifecycle["last_error"] = error
        if phase in {"completed", "failed", "cancelled"} and not task.get("completed_at"):
            task["completed_at"] = utc_now()

    def update_status(self, task_id: str, status: str, *, result_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        normalized_status = str(status or "running")
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            previous = str(task.get("status", "") or "")
            task["status"] = normalized_status
            if normalized_status == "running" and not task.get("started_at"):
                task["started_at"] = utc_now()
            if result_summary is not None:
                task["result_summary"] = deepcopy(result_summary)
            phase = normalized_status
            if normalized_status == "waiting_approval":
                phase = "waiting_approval"
            elif normalized_status == "pending":
                phase = "planned"
            self._transition_phase_locked(task, phase, reason=f"status:{normalized_status}")
            self._append_event_locked(
                task,
                "run_status_changed",
                {"status": normalized_status, "previous_status": previous},
                source_plane="agent",
                event_kind="status",
            )
            self.persist()
            return deepcopy(task)

    def update_step(
        self,
        task_id: str,
        step_id: str,
        *,
        status: str,
        result_summary: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> Dict[str, Any]:
        normalized_status = str(status or "pending")
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            target_index, step = self._find_step_locked(task, step_id)
            if step is None:
                raise KeyError(f"Agent task step not found: {step_id}")

            previous_status = str(step.get("status", "") or "")
            step["status"] = normalized_status
            if normalized_status == "running":
                if not step.get("started_at"):
                    step["started_at"] = utc_now()
                step["attempt_count"] = int(step.get("attempt_count", 0) or 0) + 1
                task["status"] = "running"
                if not task.get("started_at"):
                    task["started_at"] = utc_now()
                self._transition_phase_locked(task, "running", reason=f"step_started:{step_id}")
            if normalized_status in {"completed", "failed", "skipped"}:
                step["completed_at"] = utc_now()
            if normalized_status == "waiting_approval":
                step["completed_at"] = ""
                task["status"] = "waiting_approval"
                self._transition_phase_locked(task, "waiting_approval", reason=f"step_waiting_approval:{step_id}")
            if result_summary is not None:
                step["result_summary"] = deepcopy(result_summary)
            if error:
                step["error"] = error
                self._transition_phase_locked(task, "running", reason=f"step_error:{step_id}", error=error)

            if target_index >= 0:
                task["current_step_index"] = target_index
                if normalized_status in {"completed", "skipped"}:
                    task["current_step_index"] = min(target_index + 1, len(task.get("steps", [])))

            self._append_event_locked(
                task,
                "step_status_changed",
                {
                    "status": normalized_status,
                    "previous_status": previous_status,
                    "result_summary": result_summary or {},
                    "error": error,
                    "step_title": step.get("title", ""),
                    "step_kind": step.get("kind", ""),
                    "step_action": step.get("action", ""),
                },
                source_plane=str(step.get("kind", "agent") or "agent"),
                step_id=step_id,
                event_kind="step",
            )
            self.persist()
            return deepcopy(task)

    def add_observation(
        self,
        task_id: str,
        *,
        source_plane: str,
        action: str,
        observation: Dict[str, Any],
        status: str = "running",
        step_id: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            item = {
                "timestamp": utc_now(),
                "source_plane": source_plane,
                "action": action,
                "step_id": step_id,
                "observation": deepcopy(observation),
            }
            task.setdefault("observations", []).append(item)
            task["observations"] = task.get("observations", [])[-500:]
            counts = task.setdefault("source_plane_counts", {})
            counts[source_plane] = int(counts.get(source_plane, 0) or 0) + 1
            task["status"] = status
            if status == "running" and not task.get("started_at"):
                task["started_at"] = utc_now()
            self._append_event_locked(
                task,
                "observation_added",
                {"action": action, "observation": item},
                source_plane=source_plane,
                step_id=step_id,
                event_kind="observation",
            )
            self.persist()
            return deepcopy(task)

    def advance_current_step_index(self, task_id: str, index: int, *, reason: str = "") -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            max_index = len(task.get("steps", []))
            safe_index = max(0, min(int(index), max_index))
            previous_index = int(task.get("current_step_index", 0) or 0)
            task["current_step_index"] = safe_index
            self._append_event_locked(
                task,
                "current_step_advanced",
                {
                    "previous_index": previous_index,
                    "current_step_index": safe_index,
                    "reason": reason,
                },
                source_plane="agent",
                event_kind="step",
            )
            self.persist()
            return deepcopy(task)

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return True
            if str(task.get("status", "")) == "cancelled":
                return True
            lifecycle = task.get("lifecycle", {}) if isinstance(task.get("lifecycle"), dict) else {}
            return bool(lifecycle.get("cancel_requested", False))

    def create_approval(
        self,
        task_id: str,
        *,
        step_id: str,
        action_type: str,
        payload: Dict[str, Any],
        decision: Dict[str, Any],
        client_id: str = "",
        workspace_root: str = "",
    ) -> Dict[str, Any]:
        approval = {
            "approval_id": _new_id("approval"),
            "task_id": task_id,
            "step_id": step_id,
            "client_id": client_id,
            "action_type": action_type,
            "payload": deepcopy(payload),
            "payload_preview": self._preview_payload(payload),
            "decision": deepcopy(decision),
            "risk_level": str(decision.get("risk_level", "medium")) if isinstance(decision, dict) else "medium",
            "reason": str(decision.get("reason", "")) if isinstance(decision, dict) else "",
            "suggestion": str(decision.get("suggestion", "")) if isinstance(decision, dict) else "",
            "workspace_root": workspace_root,
            "status": "pending",
            "created_at": utc_now(),
            "resolved_at": "",
        }
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            task.setdefault("pending_approvals", []).append(approval)
            task["status"] = "waiting_approval"
            self._transition_phase_locked(task, "waiting_approval", reason=f"approval_requested:{step_id}")
            self._append_event_locked(
                task,
                "approval_requested",
                approval,
                source_plane="system_op",
                step_id=step_id,
                event_kind="approval",
            )
            self.persist()
            return deepcopy(approval)

    def resolve_approval(self, task_id: str, approval_id: str, *, approved: bool, note: str = "") -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            for approval in task.get("pending_approvals", []):
                if str(approval.get("approval_id", "")) != str(approval_id):
                    continue
                if str(approval.get("status", "")) != "pending":
                    return deepcopy(approval)
                approval["status"] = "approved" if approved else "rejected"
                approval["resolved_at"] = utc_now()
                approval["note"] = note
                task["status"] = "running" if approved else "cancelled"
                if approved:
                    self._transition_phase_locked(task, "running", reason=f"approval_approved:{approval_id}")
                else:
                    self._transition_phase_locked(task, "cancelled", reason=f"approval_rejected:{approval_id}")
                self._append_event_locked(
                    task,
                    "approval_resolved",
                    {
                        "approval_id": approval_id,
                        "approved": approved,
                        "note": note,
                        "action_type": approval.get("action_type", ""),
                    },
                    source_plane="system_op",
                    step_id=str(approval.get("step_id", "")),
                    event_kind="approval",
                )
                self.persist()
                return deepcopy(approval)
            raise KeyError(f"Approval not found: {approval_id}")

    def list_pending_approvals(
        self,
        *,
        client_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
        approvals: List[Dict[str, Any]] = []
        for task in tasks:
            if task_id and str(task.get("task_id", "")) != str(task_id):
                continue
            if client_id and str(task.get("client_id", "")) != str(client_id):
                continue
            for approval in task.get("pending_approvals", []) or []:
                if str(approval.get("status", "")) == "pending":
                    approvals.append(deepcopy(approval))
        approvals.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return approvals

    def get_replay(self, task_id: str, *, limit: int = 200) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            safe_limit = max(1, min(int(limit), 500))
            events = list(task.get("replay_events", []))[-safe_limit:]
            execution_events = list(task.get("execution_events", []))[-safe_limit:]
            return {
                "task_id": task_id,
                "run_id": task.get("run_id", ""),
                "status": task.get("status", ""),
                "current_step_index": task.get("current_step_index", 0),
                "events": deepcopy(events),
                "execution_events": deepcopy(execution_events),
                "observations": deepcopy(task.get("observations", [])),
                "pending_approvals": deepcopy(task.get("pending_approvals", [])),
            }

    @staticmethod
    def _preview_payload(payload: Dict[str, Any], *, max_chars: int = 1200) -> str:
        try:
            text = json.dumps(payload or {}, ensure_ascii=False, indent=2, default=str)
        except Exception:
            text = str(payload)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[truncated]..."

    def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        result_summary: Dict[str, Any],
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_status = str(status or "completed")
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            task["status"] = normalized_status
            task["result_summary"] = deepcopy(result_summary)
            task["verification"] = deepcopy(verification or {})
            self._transition_phase_locked(
                task,
                normalized_status,
                reason=f"finish:{normalized_status}",
                error=str(result_summary.get("error", "")) if isinstance(result_summary, dict) else "",
            )
            self._append_event_locked(
                task,
                "run_finished",
                {
                    "status": normalized_status,
                    "result_summary": result_summary,
                    "verification": verification or {},
                },
                source_plane="agent",
                event_kind="lifecycle",
            )
            self.persist()
            return deepcopy(task)

    def cancel_task(self, task_id: str, *, reason: str = "") -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            task.setdefault("lifecycle", {})["cancel_requested"] = True
        return self.finish_task(
            task_id,
            status="cancelled",
            result_summary={"reason": reason or "Cancelled by user."},
            verification={"verified": False, "reason": "cancelled"},
        )

    def list_tasks(self, *, limit: int = 50, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), self.max_size))
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        if client_id:
            tasks = [task for task in tasks if str(task.get("client_id", "")) == str(client_id)]
        return deepcopy(tasks[:safe_limit])

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    def attach_child_run(self, task_id: str, child_run_id: str) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            children = task.setdefault("relationships", {}).setdefault("child_run_ids", [])
            if child_run_id and child_run_id not in children:
                children.append(child_run_id)
                self._append_event_locked(
                    task,
                    "child_run_attached",
                    {"child_run_id": child_run_id},
                    source_plane="agent",
                    event_kind="relationship",
                )
                self.persist()
            return deepcopy(task)

    def heartbeat(self, task_id: str, *, note: str = "") -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            heartbeat_at = utc_now()
            task.setdefault("scheduler", {})["last_heartbeat_at"] = heartbeat_at
            self._append_event_locked(
                task,
                "run_heartbeat",
                {"note": note, "heartbeat_at": heartbeat_at},
                source_plane="agent",
                event_kind="heartbeat",
            )
            self.persist()
            return deepcopy(task)

    def schedule_task(self, task_id: str, *, scheduled_for: str, scheduler_id: str = "") -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Agent task not found: {task_id}")
            scheduler = task.setdefault("scheduler", {})
            scheduler["scheduled_for"] = str(scheduled_for or "")
            if scheduler_id:
                scheduler["scheduler_id"] = str(scheduler_id)
            task["status"] = "scheduled"
            self._transition_phase_locked(task, "scheduled", reason="run_scheduled")
            self._append_event_locked(
                task,
                "run_scheduled",
                {
                    "scheduled_for": str(scheduled_for or ""),
                    "scheduler_id": str(scheduler.get("scheduler_id", "") or ""),
                },
                source_plane="agent",
                event_kind="scheduler",
            )
            self.persist()
            return deepcopy(task)

    def _trim(self) -> None:
        if len(self._tasks) <= self.max_size:
            return
        ordered = sorted(self._tasks.items(), key=lambda item: str(item[1].get("updated_at", "")))
        for task_id, _ in ordered[: max(0, len(self._tasks) - self.max_size)]:
            self._tasks.pop(task_id, None)

    def persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "updated_at": utc_now(),
            "tasks": list(self._tasks.values()),
        }
        tmp_path = self.path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, self.path)

    def _migrate_legacy_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        migrated = deepcopy(task)
        now = utc_now()
        migrated.setdefault("run_id", _new_id("agent-run"))
        migrated.setdefault("workspace_root", "")
        migrated.setdefault("started_at", "")
        migrated.setdefault("completed_at", "")
        migrated.setdefault("plan_version", str(migrated.get("plan", {}).get("plan_version", "")) if isinstance(migrated.get("plan"), dict) else "")
        migrated.setdefault("execution_events", [])
        migrated.setdefault(
            "lifecycle",
            {
                "phase": str(migrated.get("status", "created") or "created"),
                "phase_history": [
                    {
                        "phase": str(migrated.get("status", "created") or "created"),
                        "timestamp": str(migrated.get("created_at", now) or now),
                        "reason": "legacy_import",
                    }
                ],
                "last_error": "",
                "retry_count": 0,
                "cancel_requested": False,
                "paused": False,
            },
        )
        migrated.setdefault(
            "scheduler",
            {
                "scheduler_id": "",
                "trigger": {},
                "scheduled_for": "",
                "last_heartbeat_at": "",
            },
        )
        migrated.setdefault(
            "relationships",
            {
                "parent_run_id": "",
                "child_run_ids": [],
            },
        )
        counts = migrated.setdefault("source_plane_counts", {})
        counts.setdefault("mcp", 0)
        counts.setdefault("system_op", 0)
        counts.setdefault("agent", 0)
        migrated["steps"] = self._normalize_steps(migrated.get("steps", []))

        if not migrated.get("execution_events"):
            for replay_event in migrated.get("replay_events", []) or []:
                if not isinstance(replay_event, dict):
                    continue
                migrated["execution_events"].append(
                    {
                        "event_id": str(replay_event.get("event_id", _new_id("run-event"))),
                        "timestamp": str(replay_event.get("timestamp", now)),
                        "event": str(replay_event.get("event", "")),
                        "event_kind": "legacy_replay",
                        "source_plane": str(replay_event.get("source_plane", "agent")),
                        "step_id": str(replay_event.get("step_id", "")),
                        "task_id": str(migrated.get("task_id", "")),
                        "run_id": str(migrated.get("run_id", "")),
                        "payload": deepcopy(replay_event.get("payload", {})),
                    }
                )
        migrated["execution_events"] = migrated.get("execution_events", [])[-1000:]
        migrated["replay_events"] = migrated.get("replay_events", [])[-500:]
        return migrated

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return
        raw_tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
        with self._lock:
            self._tasks.clear()
            for task in raw_tasks:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("task_id", "") or "").strip()
                if not task_id:
                    continue
                migrated = self._migrate_legacy_task(task)
                self._tasks[task_id] = migrated
            self._trim()

    def snapshot(self) -> Dict[str, Any]:
        statuses: Dict[str, int] = {}
        phases: Dict[str, int] = {}
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            status_key = str(task.get("status", "unknown") or "unknown")
            statuses[status_key] = statuses.get(status_key, 0) + 1
            phase_key = str(task.get("lifecycle", {}).get("phase", "unknown") or "unknown")
            phases[phase_key] = phases.get(phase_key, 0) + 1
        return {
            "path": str(self.path),
            "count": len(tasks),
            "status_counts": statuses,
            "phase_counts": phases,
            "version": 2,
        }
