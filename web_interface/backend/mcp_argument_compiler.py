#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Argument compiler for schema-aware MCP execution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _schema_properties(tool: Dict[str, Any]) -> Dict[str, Any]:
    schema = tool.get("input_schema") if isinstance(tool, dict) else {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    return properties if isinstance(properties, dict) else {}


def _schema_required(tool: Dict[str, Any]) -> List[str]:
    schema = tool.get("input_schema") if isinstance(tool, dict) else {}
    required = schema.get("required") if isinstance(schema, dict) else []
    if not isinstance(required, list):
        return []
    return [str(item).strip() for item in required if str(item).strip()]


def _resolve_schema_type(
    schema: Dict[str, Any],
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> str:
    if callable(resolve_schema_type):
        return str(resolve_schema_type(schema) or "").strip().lower()
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type.strip().lower()
    if isinstance(raw_type, list):
        lowered = [str(item).strip().lower() for item in raw_type if str(item).strip() and str(item).strip().lower() != "null"]
        return lowered[0] if lowered else ""
    return ""


def _field_is_path_like(field_name: str, field_schema: Dict[str, Any]) -> bool:
    normalized = str(field_name or "").strip().lower()
    description = str(field_schema.get("description") or field_schema.get("title") or "").lower()
    return (
        normalized in {"path", "file", "filepath", "filename", "directory", "folder", "target_path", "source_path"}
        or normalized.endswith("_path")
        or normalized.endswith("path")
        or "path" in description
        or "file" in description
    )


def _field_is_url_like(field_name: str, field_schema: Dict[str, Any]) -> bool:
    normalized = str(field_name or "").strip().lower()
    description = str(field_schema.get("description") or field_schema.get("title") or "").lower()
    return normalized in {"url", "uri"} or "url" in normalized or "uri" in normalized or "url" in description or "uri" in description


def _field_is_text_like(field_name: str, field_schema: Dict[str, Any]) -> bool:
    normalized = str(field_name or "").strip().lower()
    description = str(field_schema.get("description") or field_schema.get("title") or "").lower()
    return (
        normalized in {"text", "query", "prompt", "instruction", "message", "body", "content", "input", "thought"}
        or normalized.endswith("_query")
        or normalized.endswith("_prompt")
        or "prompt" in description
        or "question" in description
        or "instruction" in description
        or "thought" in description
    )


def _field_is_image_like(field_name: str, field_schema: Dict[str, Any]) -> bool:
    normalized = str(field_name or "").strip().lower()
    description = str(field_schema.get("description") or field_schema.get("title") or "").lower()
    return (
        normalized in {"image", "image_path", "image_url", "photo", "screenshot"}
        or "image" in normalized
        or "photo" in normalized
        or "screenshot" in normalized
        or "image" in description
        or "photo" in description
    )


def _first_attachment(attachments: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not isinstance(attachments, list):
        return {}
    for attachment in attachments:
        if isinstance(attachment, dict):
            return attachment
    return {}


def _first_image_attachment(attachments: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not isinstance(attachments, list):
        return {}
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        mime_type = str(attachment.get("mime_type") or attachment.get("content_type") or "").strip().lower()
        if bool(attachment.get("is_image")) or mime_type.startswith("image/"):
            return attachment
    return {}


def _attachment_local_path(attachment: Dict[str, Any]) -> str:
    for key in ("file_path", "path"):
        value = str(attachment.get(key) or "").strip()
        if value:
            return value
    return ""


def _attachment_url(attachment: Dict[str, Any]) -> str:
    return str(attachment.get("url") or "").strip()


def _extract_url(text: str) -> str:
    match = URL_PATTERN.search(str(text or ""))
    return match.group(0) if match else ""


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except Exception:
            return None
    return None


def compile_mcp_tool_arguments(
    *,
    tool: Dict[str, Any],
    tool_name: str,
    server_name: str,
    arguments: Optional[Dict[str, Any]],
    content: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    workspace_root: str = "",
    active_mcp_manager: Optional[Any] = None,
    infer_tool_arguments_from_context: Optional[Callable[..., tuple[Dict[str, Any], List[str]]]] = None,
    normalize_tool_arguments_runtime: Optional[Callable[..., Dict[str, Any]]] = None,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> Dict[str, Any]:
    next_args = dict(arguments or {})
    inferred_fields: List[str] = []
    compile_actions: List[str] = []
    warnings: List[str] = []

    if callable(infer_tool_arguments_from_context):
        try:
            next_args, inferred_fields = infer_tool_arguments_from_context(
                tool_name=tool_name,
                server_name=server_name,
                arguments=next_args,
                content=content,
                attachments=attachments if isinstance(attachments, list) else [],
                active_mcp_manager=active_mcp_manager,
                workspace_root=workspace_root,
            )
            if inferred_fields:
                compile_actions.extend([f"context_inferred:{name}" for name in inferred_fields])
        except TypeError:
            next_args, inferred_fields = infer_tool_arguments_from_context(  # type: ignore[misc]
                tool_name=tool_name,
                server_name=server_name,
                arguments=next_args,
                content=content,
                attachments=attachments if isinstance(attachments, list) else [],
            )
            if inferred_fields:
                compile_actions.extend([f"context_inferred:{name}" for name in inferred_fields])

    if callable(normalize_tool_arguments_runtime):
        try:
            next_args = normalize_tool_arguments_runtime(
                tool_name,
                server_name,
                next_args,
                active_mcp_manager=active_mcp_manager,
            )
        except TypeError:
            next_args = normalize_tool_arguments_runtime(tool_name, server_name, next_args)
        compile_actions.append("runtime_normalized")

    properties = _schema_properties(tool)
    required_fields = _schema_required(tool)
    first_attachment = _first_attachment(attachments)
    first_image_attachment = _first_image_attachment(attachments)

    normalized_tool_name = str(tool_name or "").strip().lower()
    if normalized_tool_name == "sequentialthinking":
        thought = str(next_args.get("thought") or content or "").strip()
        if not thought:
            thought = "Analyze the current request step by step."
            compile_actions.append("defaulted:thought")
        next_args["thought"] = thought
        if "thought" not in inferred_fields:
            inferred_fields.append("thought")

        thought_number = _coerce_int(next_args.get("thoughtNumber"))
        if thought_number is None or thought_number <= 0:
            thought_number = 1
            compile_actions.append("defaulted:thoughtNumber")
        next_args["thoughtNumber"] = thought_number

        total_thoughts = _coerce_int(next_args.get("totalThoughts"))
        if total_thoughts is None or total_thoughts < thought_number:
            total_thoughts = max(1, thought_number)
            compile_actions.append("defaulted:totalThoughts")
        next_args["totalThoughts"] = total_thoughts

        next_needed = _coerce_bool(next_args.get("nextThoughtNeeded"))
        if next_needed is None:
            next_needed = False
            compile_actions.append("defaulted:nextThoughtNeeded")
        next_args["nextThoughtNeeded"] = next_needed

    for field_name, field_schema in properties.items():
        schema_dict = field_schema if isinstance(field_schema, dict) else {}
        resolved_type = _resolve_schema_type(schema_dict, resolve_schema_type)
        if resolved_type and resolved_type not in {"string", "integer", "number", "boolean"}:
            continue

        existing = next_args.get(field_name)
        if existing is not None and not (isinstance(existing, str) and not existing.strip()):
            continue

        if _field_is_path_like(field_name, schema_dict):
            attachment_path = _attachment_local_path(first_attachment)
            if attachment_path:
                next_args[field_name] = attachment_path
                inferred_fields.append(field_name)
                compile_actions.append(f"attachment_path:{field_name}")
                continue

        if _field_is_url_like(field_name, schema_dict):
            attachment_url = _attachment_url(first_attachment)
            query_url = _extract_url(content)
            inferred_value = attachment_url or query_url
            if inferred_value:
                next_args[field_name] = inferred_value
                inferred_fields.append(field_name)
                compile_actions.append(f"url_grounded:{field_name}")
                continue

        if _field_is_image_like(field_name, schema_dict):
            image_path = _attachment_local_path(first_image_attachment)
            image_url = _attachment_url(first_image_attachment)
            inferred_value = image_path or image_url
            if inferred_value:
                next_args[field_name] = inferred_value
                inferred_fields.append(field_name)
                compile_actions.append(f"image_grounded:{field_name}")
                continue

        if _field_is_text_like(field_name, schema_dict):
            normalized_content = str(content or "").strip()
            if normalized_content:
                next_args[field_name] = normalized_content
                inferred_fields.append(field_name)
                compile_actions.append(f"text_grounded:{field_name}")
                continue

    if callable(normalize_tool_arguments_runtime):
        try:
            next_args = normalize_tool_arguments_runtime(
                tool_name,
                server_name,
                next_args,
                active_mcp_manager=active_mcp_manager,
            )
        except TypeError:
            next_args = normalize_tool_arguments_runtime(tool_name, server_name, next_args)
        compile_actions.append("runtime_normalized_final")

    missing_required: List[str] = []
    for field_name in required_fields:
        value = next_args.get(field_name)
        if value is None:
            missing_required.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing_required.append(field_name)

    for field_name in missing_required:
        schema = properties.get(field_name, {})
        if _field_is_path_like(field_name, schema):
            warnings.append(f"missing_path:{field_name}")
        elif _field_is_url_like(field_name, schema):
            warnings.append(f"missing_url:{field_name}")
        elif _field_is_image_like(field_name, schema):
            warnings.append(f"missing_image:{field_name}")
        elif _field_is_text_like(field_name, schema):
            warnings.append(f"missing_text:{field_name}")
        else:
            warnings.append(f"missing_required:{field_name}")

    return {
        "arguments": next_args,
        "inferred_fields": inferred_fields,
        "missing_required": missing_required,
        "compile_actions": compile_actions,
        "warnings": warnings,
        "workspace_root": str(workspace_root or ""),
        "attachment_paths": [
            _attachment_local_path(item)
            for item in (attachments or [])
            if isinstance(item, dict) and _attachment_local_path(item)
        ],
        "attachment_urls": [
            _attachment_url(item)
            for item in (attachments or [])
            if isinstance(item, dict) and _attachment_url(item)
        ],
    }
