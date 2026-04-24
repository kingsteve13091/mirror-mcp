# -*- coding: utf-8 -*-

"""Background multi-step executor for AgentTask.

This module keeps the System Operation Plane separate from MCP Tool Plane while
allowing AgentTask to advance through an explicit step lifecycle:

- pending -> running -> waiting_approval -> completed / failed / cancelled

It is intentionally lightweight and deterministic so it can coexist with the
existing Memory Plane and TEM research mainline without re-labeling system
operations as recipe / guard evidence.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any, Awaitable, Callable, Dict, Optional

from agent_planner import SYSTEM_OPERATION_HINTS
from system_operation_policy import evaluate_system_operation_policy

logger = logging.getLogger(__name__)


ToolRunner = Callable[[str, Dict[str, Any], str, str, str], Awaitable[Dict[str, Any]]]
SystemOpRunner = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]
SystemOpAuditIngestor = Callable[..., Dict[str, Any]]


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _attachment_paths(attachments: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        for key in ("path", "file_path"):
            value = str(attachment.get(key, "") or "").strip()
            if value and value not in paths:
                paths.append(value)
    return paths


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class AgentTaskExecutor:
    def __init__(
        self,
        *,
        runtime: Any,
        operation_audit_log: Any,
        system_operation_harness: Any,
        runtime_config_service: Any,
        memory_control_plane: Any,
        tool_runner: ToolRunner,
        system_op_audit_ingestor: Optional[SystemOpAuditIngestor] = None,
    ) -> None:
        self.runtime = runtime
        self.operation_audit_log = operation_audit_log
        self.system_operation_harness = system_operation_harness
        self.runtime_config_service = runtime_config_service
        self.memory_control_plane = memory_control_plane
        self.tool_runner = tool_runner
        self.system_op_audit_ingestor = system_op_audit_ingestor
        self._running_jobs: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    def _emit_event(
        self,
        task_id: str,
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        source_plane: str = "agent",
        step_id: str = "",
        event_kind: str = "lifecycle",
    ) -> None:
        try:
            self.runtime.append_replay_event(
                task_id,
                event,
                payload or {},
                source_plane=source_plane,
                step_id=step_id,
                event_kind=event_kind,
            )
        except Exception:
            logger.exception("failed to append runtime event %s for task %s", event, task_id)

    async def start_task(
        self,
        task_id: str,
        *,
        workspace_root: str = "",
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        async with self._lock:
            existing = self._running_jobs.get(task_id)
            if existing and not existing.done():
                return
            job = asyncio.create_task(
                self._run_task(
                    task_id,
                    workspace_root=workspace_root,
                    attachments=deepcopy(attachments or []),
                )
            )
            self._running_jobs[task_id] = job

    async def resume_after_approval(
        self,
        task_id: str,
        *,
        workspace_root: str = "",
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        await self.start_task(task_id, workspace_root=workspace_root, attachments=attachments)

    async def cancel_task(self, task_id: str) -> None:
        async with self._lock:
            job = self._running_jobs.get(task_id)
            if job and not job.done():
                job.cancel()

    async def _run_task(
        self,
        task_id: str,
        *,
        workspace_root: str,
        attachments: list[dict[str, Any]],
    ) -> None:
        try:
            task = self.runtime.get_task(task_id)
            if not task:
                return
            if str(task.get("status", "")) in {"completed", "failed", "cancelled"}:
                return
            self.runtime.update_status(task_id, "running")
            self._emit_event(
                task_id,
                "run_started",
                {
                    "goal": str(task.get("goal", "")),
                    "mode": str(task.get("mode", "")),
                    "run_id": str(task.get("run_id", "")),
                    "workspace_root": workspace_root or str(task.get("workspace_root", "")),
                },
                source_plane="agent",
                event_kind="lifecycle",
            )
            steps = list(task.get("steps", []))
            start_index = int(task.get("current_step_index", 0) or 0)
            index = start_index
            while index < len(steps):
                current = self.runtime.get_task(task_id)
                if not current:
                    return
                if self.runtime.is_cancel_requested(task_id) or str(current.get("status", "")) in {"cancelled", "completed", "failed"}:
                    self._emit_event(
                        task_id,
                        "run_stopped",
                        {"reason": "cancel_requested_or_terminal_status", "status": str(current.get("status", ""))},
                        source_plane="agent",
                        event_kind="lifecycle",
                    )
                    return
                step = steps[index]
                parallel_group = str(step.get("parallel_group", "") or "").strip()
                if parallel_group:
                    group_steps: list[dict[str, Any]] = []
                    cursor = index
                    while cursor < len(steps):
                        candidate = steps[cursor]
                        if str(candidate.get("parallel_group", "") or "").strip() != parallel_group:
                            break
                        if str(candidate.get("status", "pending") or "pending") in {"pending", "running"}:
                            group_steps.append(candidate)
                        cursor += 1
                    if len(group_steps) > 1:
                        self._emit_event(
                            task_id,
                            "parallel_group_started",
                            {
                                "parallel_group": parallel_group,
                                "step_ids": [str(item.get("step_id", "")) for item in group_steps],
                            },
                            source_plane="agent",
                            event_kind="parallel",
                        )
                        await asyncio.gather(
                            *[
                                self._execute_step(
                                    current,
                                    step=group_step,
                                    workspace_root=workspace_root,
                                    attachments=attachments,
                                )
                                for group_step in group_steps
                            ],
                        )
                        refreshed = self.runtime.get_task(task_id)
                        if not refreshed:
                            return
                        refreshed_status = str(refreshed.get("status", ""))
                        self._emit_event(
                            task_id,
                            "parallel_group_finished",
                            {
                                "parallel_group": parallel_group,
                                "status": refreshed_status,
                                "step_ids": [str(item.get("step_id", "")) for item in group_steps],
                            },
                            source_plane="agent",
                            event_kind="parallel",
                        )
                        if refreshed_status in {"waiting_approval", "cancelled", "failed"}:
                            self.runtime.advance_current_step_index(task_id, index, reason=f"parallel_yield:{parallel_group}")
                            return
                        self.runtime.advance_current_step_index(task_id, cursor, reason=f"parallel_completed:{parallel_group}")
                        index = cursor
                        continue
                self.runtime.heartbeat(task_id, note=f"before:{step.get('step_id', '')}")
                await self._execute_step(
                    current,
                    step=step,
                    workspace_root=workspace_root,
                    attachments=attachments,
                )
                refreshed = self.runtime.get_task(task_id)
                if not refreshed:
                    return
                refreshed_status = str(refreshed.get("status", ""))
                if refreshed_status in {"waiting_approval", "cancelled", "failed"}:
                    self._emit_event(
                        task_id,
                        "run_yielded",
                        {"status": refreshed_status, "step_id": str(step.get("step_id", ""))},
                        source_plane="agent",
                        step_id=str(step.get("step_id", "")),
                        event_kind="lifecycle",
                    )
                    return
                index = int(refreshed.get("current_step_index", index + 1) or index + 1)
            final_task = self.runtime.get_task(task_id)
            if final_task and str(final_task.get("status", "")) not in {"completed", "cancelled", "failed"}:
                self.runtime.finish_task(
                    task_id,
                    status="completed",
                    result_summary={
                        "message": "Agent task completed all planned steps.",
                        "completed_steps": len(final_task.get("steps", [])),
                        "system_op_events": int(final_task.get("source_plane_counts", {}).get("system_op", 0) or 0),
                        "mcp_events": int(final_task.get("source_plane_counts", {}).get("mcp", 0) or 0),
                    },
                    verification={"verified": True, "reason": "all_steps_completed"},
                )
        except asyncio.CancelledError:
            logger.info("agent task executor cancelled: %s", task_id)
            self._emit_event(
                task_id,
                "run_cancelled",
                {"reason": "executor_cancelled"},
                source_plane="agent",
                event_kind="lifecycle",
            )
            raise
        except Exception as exc:
            logger.exception("agent task executor failed for %s", task_id)
            try:
                self.runtime.finish_task(
                    task_id,
                    status="failed",
                    result_summary={"error": str(exc)},
                    verification={"verified": False, "reason": "executor_exception"},
                )
            except Exception:
                logger.exception("failed to mark agent task as failed: %s", task_id)
        finally:
            async with self._lock:
                existing = self._running_jobs.get(task_id)
                if existing and existing.done():
                    self._running_jobs.pop(task_id, None)
                elif task_id in self._running_jobs:
                    self._running_jobs.pop(task_id, None)

    async def _execute_step(
        self,
        task: Dict[str, Any],
        *,
        step: Dict[str, Any],
        workspace_root: str,
        attachments: list[dict[str, Any]],
    ) -> None:
        task_id = str(task.get("task_id", ""))
        client_id = str(task.get("client_id", ""))
        goal = str(task.get("goal", ""))
        step_id = str(step.get("step_id", ""))
        kind = _safe_text(step.get("kind"), "analysis")
        action = _safe_text(step.get("action"))
        self.runtime.update_step(task_id, step_id, status="running")
        self._emit_event(
            task_id,
            "step_started",
            {
                "step_id": step_id,
                "step_kind": kind,
                "step_action": action,
                "step_title": str(step.get("title", "")),
            },
            source_plane=kind if kind in {"mcp", "mcp_tool", "system_op"} else "agent",
            step_id=step_id,
            event_kind="step",
        )

        if kind == "analysis":
            summary = self._analysis_summary(goal, attachments)
            self.runtime.add_observation(
                task_id,
                source_plane="agent",
                action=action or "summarize_goal",
                observation=summary,
                status="running",
                step_id=step_id,
            )
            self.runtime.update_step(task_id, step_id, status="completed", result_summary=summary)
            self._emit_event(
                task_id,
                "step_completed",
                {"step_id": step_id, "result_summary": summary},
                source_plane="agent",
                step_id=step_id,
                event_kind="step",
            )
            return

        if kind == "attachment_grounding":
            summary = self._attachment_grounding_summary(attachments)
            self.runtime.add_observation(
                task_id,
                source_plane="agent",
                action=action or "attachment_grounding",
                observation=summary,
                status="running",
                step_id=step_id,
            )
            self.runtime.update_step(task_id, step_id, status="completed", result_summary=summary)
            self._emit_event(
                task_id,
                "step_completed",
                {"step_id": step_id, "result_summary": summary},
                source_plane="agent",
                step_id=step_id,
                event_kind="step",
            )
            return

        if kind == "verification":
            verification = self._build_verification(task_id)
            self.runtime.add_observation(
                task_id,
                source_plane="agent",
                action=action or "verify_and_answer",
                observation=verification,
                status="running",
                step_id=step_id,
            )
            self.runtime.update_step(task_id, step_id, status="completed", result_summary=verification)
            self._emit_event(
                task_id,
                "verification_finished",
                {"step_id": step_id, "verification": verification},
                source_plane="agent",
                step_id=step_id,
                event_kind="verification",
            )
            return

        if kind == "skill_template":
            summary = self._execute_skill_template_summary(task_id=task_id, step=step, workspace_root=workspace_root, attachments=attachments)
            self.runtime.add_observation(
                task_id,
                source_plane="agent",
                action=action or "skill_template",
                observation=summary,
                status="running",
                step_id=step_id,
            )
            self.runtime.update_step(task_id, step_id, status="completed", result_summary=summary)
            self._emit_event(
                task_id,
                "skill_template_completed",
                {"step_id": step_id, "result_summary": summary},
                source_plane="agent",
                step_id=step_id,
                event_kind="step",
            )
            return

        if kind == "system_op":
            await self._execute_system_op_step(
                task_id=task_id,
                client_id=client_id,
                goal=goal,
                step=step,
                workspace_root=workspace_root,
                attachments=attachments,
            )
            return

        if kind == "mcp_tool":
            await self._execute_mcp_step(
                task_id=task_id,
                goal=goal,
                step=step,
                workspace_root=workspace_root,
                attachments=attachments,
            )
            return

        summary = {
            "message": f"Unknown step kind treated as note: {kind}",
            "kind": kind,
            "action": action,
        }
        self.runtime.add_observation(
            task_id,
            source_plane="agent",
            action=action or "unknown_step",
            observation=summary,
            status="running",
            step_id=step_id,
        )
        self.runtime.update_step(task_id, step_id, status="completed", result_summary=summary)
        self._emit_event(
            task_id,
            "step_completed",
            {"step_id": step_id, "result_summary": summary},
            source_plane="agent",
            step_id=step_id,
            event_kind="step",
        )

    def _analysis_summary(self, goal: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "message": "Agent interpreted the request and prepared a bounded execution plan.",
            "goal": goal[:500],
            "attachment_count": len(attachments),
            "attachment_paths": _attachment_paths(attachments)[:8],
        }

    def _attachment_grounding_summary(self, attachments: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "message": "Attachment grounding finished.",
            "attachment_count": len(attachments),
            "visible_inputs": [
                {
                    "filename": str(item.get("filename") or item.get("original_filename") or ""),
                    "path": str(item.get("path") or item.get("file_path") or ""),
                    "mime_type": str(item.get("mime_type") or item.get("content_type") or ""),
                    "parse_status": str(item.get("parse_status") or ""),
                    "parse_mode": str(item.get("parse_mode") or ""),
                }
                for item in attachments[:10]
                if isinstance(item, dict)
            ],
        }

    def _build_verification(self, task_id: str) -> dict[str, Any]:
        task = self.runtime.get_task(task_id) or {}
        observations = list(task.get("observations", []))
        return {
            "verified": True,
            "observation_count": len(observations),
            "system_op_events": int(task.get("source_plane_counts", {}).get("system_op", 0) or 0),
            "mcp_events": int(task.get("source_plane_counts", {}).get("mcp", 0) or 0),
            "latest_observations": observations[-3:],
        }

    def _execute_skill_template_summary(
        self,
        *,
        task_id: str,
        step: Dict[str, Any],
        workspace_root: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        template = step.get("skill_template") if isinstance(step.get("skill_template"), dict) else {}
        template_kind = _safe_text(template.get("kind") or step.get("action"), "skill_template")
        template_title = _safe_text(template.get("title") or step.get("title"), template_kind)
        template_steps = [
            str(item).strip()
            for item in _safe_list(template.get("steps"))
            if str(item).strip()
        ]
        task = self.runtime.get_task(task_id) or {}
        return {
            "message": "Skill action template scaffold completed.",
            "template_kind": template_kind,
            "template_title": template_title,
            "template_steps": template_steps,
            "workspace_root": workspace_root,
            "attachment_paths": _attachment_paths(attachments)[:8],
            "goal": str(task.get("goal", ""))[:500],
        }

    def _system_op_payload_for_step(
        self,
        *,
        action: str,
        goal: str,
        workspace_root: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        lowered = goal.lower()
        if action == "log_read":
            return {"path": "artifacts/logs/backend_restart_check.out.log", "tail": 120}
        if action == "browser_smoke":
            return {"stage": "tool_chain", "timeout_ms": 180000}
        if action == "test_runner":
            profile = "smoke"
            if "frontend" in lowered:
                profile = "frontend_ci"
            elif "backend" in lowered or "compile" in lowered:
                profile = "backend_compile"
            elif "onboarding" in lowered:
                profile = "mcp_onboarding_gate"
            return {"profile": profile, "timeout_ms": 90000}
        if action == "process_control":
            operation = "status"
            if "restart backend" in lowered:
                operation = "restart_backend"
            elif "restart frontend" in lowered:
                operation = "restart_frontend"
            return {"operation": operation}
        if action == "workspace_file_op":
            attachment_paths = _attachment_paths(attachments)
            chosen_path = attachment_paths[0] if attachment_paths else "README.md"
            return {"operation": "read", "path": chosen_path}
        if action == "terminal_command":
            return {
                "command": "powershell -NoProfile -Command \"Get-ChildItem -Force | Select-Object -First 20 Name,Mode | ConvertTo-Json\"",
                "working_directory": workspace_root or ".",
                "timeout_ms": 20000,
            }
        return {}

    async def _execute_system_op_step(
        self,
        *,
        task_id: str,
        client_id: str,
        goal: str,
        step: Dict[str, Any],
        workspace_root: str,
        attachments: list[dict[str, Any]],
    ) -> None:
        step_id = str(step.get("step_id", ""))
        action = _safe_text(step.get("action"))
        payload = self._system_op_payload_for_step(
            action=action,
            goal=goal,
            workspace_root=workspace_root,
            attachments=attachments,
        )
        policy_state = self.runtime_config_service.get_tool_policy_state()
        decision = evaluate_system_operation_policy(
            action_type=action,
            payload=payload,
            policy_state=policy_state,
            workspace_root=workspace_root,
            policy_confirmed=False,
        )
        if not decision.allowed and decision.requires_confirmation:
            self._emit_event(
                task_id,
                "system_op_waiting_approval",
                {
                    "step_id": step_id,
                    "action_type": action,
                    "payload": payload,
                    "decision": decision.to_payload(),
                },
                source_plane="system_op",
                step_id=step_id,
                event_kind="approval",
            )
            approval = self.runtime.create_approval(
                task_id,
                step_id=step_id,
                action_type=action,
                payload=payload,
                decision=decision.to_payload(),
                client_id=client_id,
                workspace_root=workspace_root,
            )
            self.operation_audit_log.append(
                {
                    "task_id": task_id,
                    "client_id": client_id,
                    "event": "system_op_approval_requested",
                    "step_id": step_id,
                    "action_type": action,
                    "payload": payload,
                    "decision": decision.to_payload(),
                    "approval_id": approval.get("approval_id", ""),
                }
            )
            self.runtime.update_step(task_id, step_id, status="waiting_approval", result_summary={"approval_id": approval.get("approval_id", "")})
            return
        if not decision.allowed:
            self._emit_event(
                task_id,
                "system_op_denied",
                {
                    "step_id": step_id,
                    "action_type": action,
                    "decision": decision.to_payload(),
                },
                source_plane="system_op",
                step_id=step_id,
                event_kind="policy",
            )
            self.runtime.update_step(task_id, step_id, status="failed", result_summary=decision.to_payload(), error=decision.reason)
            self.runtime.finish_task(
                task_id,
                status="failed",
                result_summary={"error": decision.reason, "action_type": action},
                verification={"verified": False, "reason": "system_op_denied"},
            )
            self.operation_audit_log.append(
                {
                    "task_id": task_id,
                    "client_id": client_id,
                    "event": "system_op_denied",
                    "step_id": step_id,
                    "action_type": action,
                    "payload": payload,
                    "decision": decision.to_payload(),
                }
            )
            return

        self._emit_event(
            task_id,
            "system_op_started",
            {
                "step_id": step_id,
                "action_type": action,
                "payload": payload,
            },
            source_plane="system_op",
            step_id=step_id,
            event_kind="system_op",
        )
        result = await self.system_operation_harness.execute(
            action_type=action,
            payload=payload,
            workspace_root=workspace_root,
        )
        self.runtime.add_observation(
            task_id,
            source_plane="system_op",
            action=action,
            observation=result,
            status="running",
            step_id=step_id,
        )
        audit_event = self.operation_audit_log.append(
            {
                "task_id": task_id,
                "client_id": client_id,
                "event": "system_op_executed",
                "step_id": step_id,
                "action_type": action,
                "payload": payload,
                "result": {
                    "success": bool(result.get("success", False)),
                    "action_type": result.get("action_type"),
                    "timestamp": result.get("timestamp"),
                },
                "decision": decision.to_payload(),
            }
        )
        if self.system_op_audit_ingestor is not None:
            try:
                if bool(self.runtime_config_service.get_memory_plane_runtime_state().get("absorb_system_op_audit", True)):
                    self.system_op_audit_ingestor(
                        task_id=task_id,
                        client_id=client_id,
                        step_id=step_id,
                        action_type=action,
                        payload=payload,
                        result=result,
                        decision=decision.to_payload(),
                        audit=audit_event,
                    )
            except Exception:
                logger.exception("failed to ingest system_op audit into memory plane")
        if bool(result.get("success", False)):
            self.runtime.update_step(task_id, step_id, status="completed", result_summary=result)
            self._emit_event(
                task_id,
                "system_op_finished",
                {"step_id": step_id, "action_type": action, "success": True, "result": result},
                source_plane="system_op",
                step_id=step_id,
                event_kind="system_op",
            )
        else:
            error = str(result.get("stderr") or result.get("error") or "System operation failed.")
            self.runtime.update_step(task_id, step_id, status="failed", result_summary=result, error=error)
            self._emit_event(
                task_id,
                "system_op_finished",
                {"step_id": step_id, "action_type": action, "success": False, "error": error, "result": result},
                source_plane="system_op",
                step_id=step_id,
                event_kind="system_op",
            )
            self.runtime.finish_task(
                task_id,
                status="failed",
                result_summary={"error": error, "action_type": action, "result": result},
                verification={"verified": False, "reason": "system_op_failed"},
            )

    async def _execute_mcp_step(
        self,
        *,
        task_id: str,
        goal: str,
        step: Dict[str, Any],
        workspace_root: str,
        attachments: list[dict[str, Any]],
    ) -> None:
        step_id = str(step.get("step_id", ""))
        action = _safe_text(step.get("action"))
        tool_name = "fetch" if action == "fetch" else action
        arguments: dict[str, Any] = {}
        lowered = goal.lower()
        if tool_name == "fetch":
            url = ""
            for token in goal.split():
                if token.startswith("http://") or token.startswith("https://"):
                    url = token.strip()
                    break
            arguments = {"url": url} if url else {}
        elif attachments:
            arguments = {"path": _attachment_paths(attachments)[0]} if _attachment_paths(attachments) else {}
        self._emit_event(
            task_id,
            "tool_call_started",
            {
                "step_id": step_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "workspace_root": workspace_root,
            },
            source_plane="mcp",
            step_id=step_id,
            event_kind="tool_call",
        )
        try:
            result = await self.tool_runner(task_id, arguments, tool_name, "", workspace_root)
        except Exception as exc:
            failure = {"success": False, "error": str(exc), "tool_name": tool_name}
            self.runtime.add_observation(
                task_id,
                source_plane="mcp",
                action=tool_name,
                observation=failure,
                status="running",
                step_id=step_id,
            )
            self._emit_event(
                task_id,
                "tool_call_finished",
                {"step_id": step_id, "tool_name": tool_name, "success": False, "error": str(exc)},
                source_plane="mcp",
                step_id=step_id,
                event_kind="tool_call",
            )
            self.runtime.update_step(task_id, step_id, status="failed", result_summary=failure, error=str(exc))
            self.runtime.finish_task(
                task_id,
                status="failed",
                result_summary=failure,
                verification={"verified": False, "reason": "mcp_step_failed"},
            )
            return

        self.runtime.add_observation(
            task_id,
            source_plane="mcp",
            action=tool_name,
            observation=result,
            status="running",
            step_id=step_id,
        )
        self._emit_event(
            task_id,
            "tool_call_finished",
            {
                "step_id": step_id,
                "tool_name": tool_name,
                "success": bool(result.get("success", True)) if isinstance(result, dict) else True,
                "result": result,
            },
            source_plane="mcp",
            step_id=step_id,
            event_kind="tool_call",
        )
        ok = bool(result.get("success", True)) if isinstance(result, dict) else True
        if ok:
            self.runtime.update_step(task_id, step_id, status="completed", result_summary=result if isinstance(result, dict) else {"result": result})
        else:
            error = str(result.get("error", "MCP step failed")) if isinstance(result, dict) else "MCP step failed"
            self.runtime.update_step(task_id, step_id, status="failed", result_summary=result if isinstance(result, dict) else {"result": result}, error=error)
            self.runtime.finish_task(
                task_id,
                status="failed",
                result_summary=result if isinstance(result, dict) else {"result": result},
                verification={"verified": False, "reason": "mcp_step_failed"},
            )
