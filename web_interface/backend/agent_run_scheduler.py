# -*- coding: utf-8 -*-

"""Lightweight scheduler for delayed agent task execution.

This scheduler intentionally stays small and auditable:

- it does not replace the main chat runtime
- it only releases already-created agent tasks when they become due
- it keeps system operation governance inside the existing policy / approval flow
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc_timestamp(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class AgentRunScheduler:
    def __init__(
        self,
        *,
        runtime: Any,
        executor: Any,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.runtime = runtime
        self.executor = executor
        self.poll_interval_seconds = max(0.5, float(poll_interval_seconds))
        self._loop_task: Optional[asyncio.Task[Any]] = None
        self._stop_event = asyncio.Event()
        self._scheduled_task_ids: set[str] = set()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run_loop(), name="agent-run-scheduler")

    async def shutdown(self) -> None:
        self._stop_event.set()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None

    async def register(self, task_id: str) -> None:
        if not str(task_id or "").strip():
            return
        async with self._lock:
            self._scheduled_task_ids.add(str(task_id))

    async def unregister(self, task_id: str) -> None:
        async with self._lock:
            self._scheduled_task_ids.discard(str(task_id or ""))

    async def _drain_due_tasks(self) -> None:
        async with self._lock:
            candidate_ids = list(self._scheduled_task_ids)
        if not candidate_ids:
            return

        now = utc_now()
        due_ids: list[str] = []
        stale_ids: list[str] = []

        for task_id in candidate_ids:
            task = self.runtime.get_task(task_id)
            if not task:
                stale_ids.append(task_id)
                continue
            status = str(task.get("status", "") or "")
            if status in {"completed", "cancelled", "failed"}:
                stale_ids.append(task_id)
                continue
            scheduled_for = parse_utc_timestamp(str(task.get("scheduler", {}).get("scheduled_for", "") or ""))
            if scheduled_for is None:
                due_ids.append(task_id)
                continue
            if scheduled_for <= now:
                due_ids.append(task_id)

        for task_id in stale_ids:
            await self.unregister(task_id)

        for task_id in due_ids:
            task = self.runtime.get_task(task_id)
            if not task:
                await self.unregister(task_id)
                continue
            self.runtime.append_replay_event(
                task_id,
                "scheduler_released",
                {
                    "scheduled_for": str(task.get("scheduler", {}).get("scheduled_for", "") or ""),
                    "released_at": utc_now().isoformat(),
                },
                source_plane="agent",
                event_kind="scheduler",
            )
            self.runtime.update_status(task_id, "pending")
            await self.executor.start_task(
                task_id,
                workspace_root=str(task.get("workspace_root", "") or ""),
                attachments=[],
            )
            await self.unregister(task_id)

    async def _run_loop(self) -> None:
        logger.info("agent run scheduler started")
        try:
            while not self._stop_event.is_set():
                try:
                    await self._drain_due_tasks()
                except Exception:
                    logger.exception("agent run scheduler tick failed")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.info("agent run scheduler cancelled")
            raise
        finally:
            logger.info("agent run scheduler stopped")

    def snapshot(self) -> Dict[str, Any]:
        loop_running = self._loop_task is not None and not self._loop_task.done()
        return {
            "running": loop_running,
            "poll_interval_seconds": self.poll_interval_seconds,
            "scheduled_count": len(self._scheduled_task_ids),
        }
