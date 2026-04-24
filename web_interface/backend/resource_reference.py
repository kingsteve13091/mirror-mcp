#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Resource reference normalization for the System Harness Plane."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
AT_PATH_PATTERN = re.compile(
    r"@((?:\.{1,2}[\\/])?(?:[A-Za-z0-9_.\- ]+[\\/])*[A-Za-z0-9_.\- ]+\.[A-Za-z0-9]{1,16})"
)


def _resource_id(kind: str, value: str) -> str:
    digest = hashlib.sha1(f"{kind}:{value}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"res-{digest}"


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_workspace_path(raw_value: str, *, workspace_root: str = "", project_root: Optional[Path] = None) -> str:
    value = _safe_text(raw_value).strip("`'\"")
    if not value:
        return ""
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    root = Path(workspace_root).expanduser() if workspace_root else None
    if root is not None:
        try:
            return str((root / candidate).resolve())
        except Exception:
            pass
    if project_root is not None:
        try:
            return str((project_root / candidate).resolve())
        except Exception:
            pass
    return value


def _attachment_kind(attachment: Dict[str, Any]) -> str:
    mime_type = _safe_text(attachment.get("mime_type") or attachment.get("content_type")).lower()
    if bool(attachment.get("is_image")) or mime_type.startswith("image/"):
        return "uploaded_image"
    return "uploaded_file"


def build_resource_references(
    *,
    content: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    workspace_root: str = "",
    project_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add_ref(ref: Dict[str, Any]) -> None:
        value = _safe_text(ref.get("path") or ref.get("url") or ref.get("label"))
        kind = _safe_text(ref.get("kind"))
        if not kind or not value:
            return
        key = f"{kind}:{value}".lower()
        if key in seen:
            return
        seen.add(key)
        ref.setdefault("ref_id", _resource_id(kind, value))
        refs.append(ref)

    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        kind = _attachment_kind(attachment)
        path = _safe_text(attachment.get("file_path") or attachment.get("path"))
        url = _safe_text(attachment.get("url"))
        label = _safe_text(attachment.get("original_filename") or attachment.get("filename") or path or url)
        add_ref({
            "kind": kind,
            "label": label,
            "path": path,
            "url": url,
            "mime_type": _safe_text(attachment.get("mime_type")),
            "size": attachment.get("size"),
            "source": "upload",
            "model_visible": bool(attachment.get("model_visible_on_current_turn", False)) or kind == "uploaded_image",
            "tool_usable": bool(attachment.get("tool_usable_on_current_turn", False)) or bool(path),
            "parse_status": _safe_text(attachment.get("parse_status")),
            "transport_role": _safe_text(attachment.get("transport_role")),
        })

    for match in URL_PATTERN.findall(content or ""):
        url = match.rstrip(".,;:")
        add_ref({
            "kind": "url",
            "label": url,
            "url": url,
            "source": "message",
            "model_visible": True,
            "tool_usable": True,
        })

    for match in AT_PATH_PATTERN.findall(content or ""):
        resolved = _resolve_workspace_path(match, workspace_root=workspace_root, project_root=project_root)
        add_ref({
            "kind": "workspace_path",
            "label": match,
            "path": resolved,
            "source": "message_at_reference",
            "model_visible": False,
            "tool_usable": True,
        })

    return refs
