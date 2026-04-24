# -*- coding: utf-8 -*-

"""Idempotent request runtime journal and replay cache service."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional


logger = logging.getLogger(__name__)


class RequestRuntimeService:
    """Track request lifecycle, dedupe repeated requests, and recover interrupted runs."""

    def __init__(
        self,
        *,
        journal_path: Path,
        max_size: int = 500,
        journal_version: int = 1,
        default_model_id: str = "",
        summarize_request_result_payload: Optional[Callable[[Optional[dict[str, Any]]], dict[str, Any]]] = None,
    ) -> None:
        self.journal_path = Path(journal_path)
        self.max_size = int(max_size)
        self.journal_version = int(journal_version)
        self.default_model_id = default_model_id
        self.summarize_request_result_payload = summarize_request_result_payload or (lambda _payload: {})

        self.result_cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.inflight_requests: Dict[str, set[str]] = {}
        self.inflight_request_owners: Dict[str, str] = {}
        self.runtime_journal: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.lock = threading.RLock()

    def now(self) -> str:
        return datetime.now().isoformat()

    def summarize_request_message(self, message: dict[str, Any]) -> dict[str, Any]:
        request_type = str(message.get("type", "unknown"))
        summary: dict[str, Any] = {"request_type": request_type}

        if request_type == "chat":
            content = str(message.get("content", "") or "")
            attachments = message.get("attachments") or []
            summary.update(
                {
                    "model_id": message.get("model_id") or self.default_model_id,
                    "content_preview": content[:160],
                    "has_image": bool(message.get("image_data")),
                    "attachment_count": len(attachments) if isinstance(attachments, list) else 0,
                }
            )
        elif request_type == "tool_call":
            summary.update(
                {
                    "tool_name": message.get("tool_name", ""),
                    "server_name": message.get("server_name", ""),
                    "argument_keys": sorted((message.get("arguments") or {}).keys()),
                }
            )
        elif request_type == "resource_read":
            summary.update(
                {
                    "uri": message.get("uri", ""),
                    "server_name": message.get("server_name", ""),
                }
            )
        elif request_type == "prompt_get":
            summary.update(
                {
                    "prompt_name": message.get("prompt_name", ""),
                    "server_name": message.get("server_name", ""),
                    "argument_keys": sorted((message.get("arguments") or {}).keys()),
                }
            )

        return summary

    def runtime_status_from_payload(self, payload: dict[str, Any]) -> str:
        explicit_status = str(payload.get("request_runtime_status", "") or "").strip().lower()
        if explicit_status in {"completed", "failed", "blocked", "interrupted"}:
            return explicit_status

        payload_type = str(payload.get("type", "") or "").strip().lower()
        if payload_type == "tool_blocked":
            return "blocked"
        if payload_type == "error":
            return "failed"
        if payload_type in {"tool_result", "resource_result", "prompt_result"}:
            result = payload.get("result")
            if isinstance(result, dict) and result.get("success") is False:
                return "failed"
        return "completed"

    def delivery_status_from_runtime_status(self, runtime_status: str) -> str:
        if runtime_status in {"completed", "failed", "blocked"}:
            return runtime_status
        if runtime_status == "interrupted":
            return "failed"
        return "completed"

    def delivery_message_for_replay(self, runtime_status: str) -> str:
        if runtime_status == "interrupted":
            return "Previous request was interrupted by backend restart and was not re-executed automatically"
        return f"Replayed cached {runtime_status} request result"

    def build_interrupted_request_payload(self, entry: dict[str, Any]) -> dict[str, Any]:
        request_id = str(entry.get("request_id", "") or "")
        request_type = str(entry.get("request_type", "unknown") or "unknown")
        summary = entry.get("request_summary") or {}
        return {
            "type": "error",
            "message": "Request was interrupted by backend restart before completion. It was not re-executed automatically.",
            "error_type": "BackendRestartInterrupted",
            "request_runtime_status": "interrupted",
            "request_id": request_id,
            "interrupted_request_type": request_type,
            "request_summary": summary,
            "recovery_action": "manual_retry_required",
            "timestamp": self.now(),
        }

    def build_request_replay_payload(self, payload: dict[str, Any], *, source: str) -> dict[str, Any]:
        replay_payload = copy.deepcopy(payload)
        runtime_status = self.runtime_status_from_payload(replay_payload)
        replay_payload["request_runtime_status"] = runtime_status
        replay_payload["replayed_from_request_cache"] = True
        replay_payload["replay_source"] = source
        replay_payload["replay_timestamp"] = self.now()
        return replay_payload

    def trim_state(self) -> bool:
        trimmed = False
        while len(self.result_cache) > self.max_size:
            self.result_cache.popitem(last=False)
            trimmed = True

        while len(self.runtime_journal) > self.max_size:
            dropped_request_id, _ = self.runtime_journal.popitem(last=False)
            self.result_cache.pop(dropped_request_id, None)
            self.inflight_requests.pop(dropped_request_id, None)
            self.inflight_request_owners.pop(dropped_request_id, None)
            trimmed = True

        return trimmed

    def persist_journal(self) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            payload = {
                "version": self.journal_version,
                "updated_at": self.now(),
                "entries": [copy.deepcopy(entry) for entry in self.runtime_journal.values()],
            }
            tmp_path = self.journal_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, self.journal_path)

    def remember_inflight(self, request_id: Optional[str], message: dict[str, Any], client_id: str) -> None:
        if not request_id:
            return

        request_type = str(message.get("type", "unknown") or "unknown")
        now = self.now()

        with self.lock:
            existing = self.runtime_journal.get(request_id, {})
            client_ids = {
                str(existing_client_id)
                for existing_client_id in existing.get("client_ids", [])
                if str(existing_client_id).strip()
            }
            client_ids.add(client_id)
            self.runtime_journal[request_id] = {
                "request_id": request_id,
                "request_type": request_type,
                "status": "inflight",
                "started_at": existing.get("started_at", now),
                "updated_at": now,
                "client_ids": sorted(client_ids),
                "request_summary": self.summarize_request_message(message),
                "result_payload": None,
            }
            self.runtime_journal.move_to_end(request_id)
            self.trim_state()
            self.persist_journal()

    def load_journal(self) -> None:
        with self.lock:
            self.result_cache.clear()
            self.inflight_requests.clear()
            self.inflight_request_owners.clear()
            self.runtime_journal.clear()

            if not self.journal_path.exists():
                return

            try:
                with open(self.journal_path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except Exception as exc:
                logger.warning("failed to load request dedupe journal; ignoring old entries: %s", exc)
                return

            raw_entries = raw.get("entries", []) if isinstance(raw, dict) else []
            needs_persist = False

            for entry in raw_entries:
                if not isinstance(entry, dict):
                    continue
                request_id = str(entry.get("request_id", "") or "").strip()
                if not request_id:
                    continue
                self.runtime_journal[request_id] = copy.deepcopy(entry)

            for request_id, entry in list(self.runtime_journal.items()):
                status = str(entry.get("status", "") or "").strip().lower()
                if status == "inflight":
                    interrupted_payload = self.build_interrupted_request_payload(entry)
                    entry["status"] = "interrupted"
                    entry["updated_at"] = self.now()
                    entry["result_payload"] = copy.deepcopy(interrupted_payload)
                    self.result_cache[request_id] = copy.deepcopy(interrupted_payload)
                    self.result_cache.move_to_end(request_id)
                    needs_persist = True
                    continue

                result_payload = entry.get("result_payload")
                if status in {"completed", "failed", "blocked", "interrupted"} and isinstance(result_payload, dict):
                    self.result_cache[request_id] = copy.deepcopy(result_payload)
                    self.result_cache.move_to_end(request_id)

            if self.trim_state():
                needs_persist = True

            if needs_persist:
                self.persist_journal()

    def remember_result(self, request_id: Optional[str], payload: dict[str, Any]) -> None:
        if not request_id:
            return
        payload_copy = copy.deepcopy(payload)
        runtime_status = self.runtime_status_from_payload(payload_copy)
        payload_copy["request_runtime_status"] = runtime_status
        self.result_cache[request_id] = payload_copy
        self.result_cache.move_to_end(request_id)
        with self.lock:
            existing = self.runtime_journal.get(request_id, {})
            self.runtime_journal[request_id] = {
                "request_id": request_id,
                "request_type": existing.get("request_type") or str(payload_copy.get("type", "unknown") or "unknown"),
                "status": runtime_status,
                "started_at": existing.get("started_at", payload_copy.get("timestamp") or self.now()),
                "updated_at": self.now(),
                "client_ids": existing.get("client_ids", []),
                "request_summary": existing.get("request_summary", {}),
                "result_payload": copy.deepcopy(payload_copy),
            }
            self.runtime_journal.move_to_end(request_id)
            self.trim_state()
            self.persist_journal()

    def ordered_deepcopy(self, data: OrderedDict | dict[str, Any]) -> OrderedDict:
        return OrderedDict((key, copy.deepcopy(value)) for key, value in data.items())

    def snapshot_state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "request_result_cache": self.ordered_deepcopy(self.result_cache),
                "request_runtime_journal": self.ordered_deepcopy(self.runtime_journal),
                "inflight_requests": {
                    str(key): set(value)
                    for key, value in self.inflight_requests.items()
                },
                "inflight_request_owners": dict(self.inflight_request_owners),
            }

    def restore_state(self, snapshot: dict[str, Any]) -> None:
        with self.lock:
            self.result_cache.clear()
            self.result_cache.update(copy.deepcopy(snapshot.get("request_result_cache", OrderedDict())))
            self.runtime_journal.clear()
            self.runtime_journal.update(copy.deepcopy(snapshot.get("request_runtime_journal", OrderedDict())))
            self.inflight_requests.clear()
            self.inflight_requests.update(
                {
                    str(key): set(value)
                    for key, value in copy.deepcopy(snapshot.get("inflight_requests", {})).items()
                }
            )
            self.inflight_request_owners.clear()
            self.inflight_request_owners.update(copy.deepcopy(snapshot.get("inflight_request_owners", {})))

    def get_cached_result(self, request_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not request_id:
            return None
        cached = self.result_cache.get(request_id)
        if cached is None:
            return None
        self.result_cache.move_to_end(request_id)
        return dict(cached)

    def register_inflight_request(self, request_id: Optional[str], client_id: str) -> bool:
        if not request_id:
            return False
        owner = self.inflight_request_owners.get(request_id)
        if owner is None:
            self.inflight_request_owners[request_id] = client_id
            self.inflight_requests[request_id] = set()
            return False
        if owner != client_id:
            watchers = self.inflight_requests.setdefault(request_id, set())
            watchers.add(client_id)
        return True

    def release_inflight_request(self, request_id: Optional[str]) -> list[str]:
        if not request_id:
            return []
        self.inflight_request_owners.pop(request_id, None)
        watchers = list(self.inflight_requests.pop(request_id, set()))
        return watchers

    def estimate_duration_ms(self, started_at: Any, updated_at: Any) -> Optional[int]:
        if not started_at or not updated_at:
            return None
        try:
            started = datetime.fromisoformat(str(started_at))
            updated = datetime.fromisoformat(str(updated_at))
            duration = int((updated - started).total_seconds() * 1000)
            return max(duration, 0)
        except Exception:
            return None

    def build_entry_view(self, request_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        status = str(entry.get("status", "unknown") or "unknown")
        started_at = entry.get("started_at")
        updated_at = entry.get("updated_at")
        request_summary = entry.get("request_summary") if isinstance(entry.get("request_summary"), dict) else {}
        result_payload = entry.get("result_payload") if isinstance(entry.get("result_payload"), dict) else None
        client_ids = [
            str(client_id)
            for client_id in entry.get("client_ids", [])
            if str(client_id).strip()
        ]

        return {
            "request_id": request_id,
            "request_type": str(entry.get("request_type", "unknown") or "unknown"),
            "status": status,
            "started_at": started_at,
            "updated_at": updated_at,
            "client_ids": client_ids,
            "watcher_count": max(len(client_ids) - 1, 0),
            "request_summary": request_summary,
            "result_summary": self.summarize_request_result_payload(result_payload),
            "is_inflight": status == "inflight",
            "is_recoverable": status in {"failed", "blocked", "interrupted"},
            "duration_ms": self.estimate_duration_ms(started_at, updated_at),
        }

    def recent_entries(self) -> list[tuple[str, dict[str, Any]]]:
        with self.lock:
            return list(self.runtime_journal.items())
