#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Schema-driven tool harness helpers.

This module keeps MCP tool understanding independent from concrete tool names as
much as possible so newly added MCP servers/tools can be discovered and adapted
without manual registration changes.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional


READ_ONLY_NAME_HINTS = {
    "read",
    "get",
    "list",
    "search",
    "find",
    "fetch",
    "query",
    "inspect",
    "browse",
    "lookup",
    "describe",
    "analyze",
    "parse",
    "extract",
    "summarize",
    "open",
}

WRITE_NAME_HINTS = {
    "write",
    "edit",
    "update",
    "delete",
    "remove",
    "create",
    "move",
    "rename",
    "append",
    "store",
    "save",
    "insert",
    "set",
    "add",
    "push",
    "send",
    "post",
    "commit",
    "publish",
    "revoke",
    "run",
    "execute",
}

PATH_FIELD_HINTS = {
    "path",
    "file",
    "filepath",
    "filename",
    "directory",
    "folder",
    "target_path",
    "source_path",
    "destination",
    "destination_path",
    "uri",
    "url",
    "paths",
    "files",
}

TEXT_FIELD_HINTS = {
    "query",
    "question",
    "prompt",
    "instruction",
    "text",
    "input",
    "content",
    "message",
    "body",
}

IMAGE_FIELD_HINTS = {
    "image",
    "image_path",
    "image_url",
    "photo",
    "screenshot",
    "vision_input",
}

MANUAL_SERVER_HINTS = {
    "memory",
    "terminal",
}

MANUAL_TOOL_NAMES = {
    "list_allowed_directories",
    "read_graph",
    "sequentialthinking",
    "execute_command",
}


def _schema_properties(schema: Any) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _schema_required_fields(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [str(field).strip() for field in required if str(field).strip()]


def _resolve_type(
    schema: Dict[str, Any],
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> str:
    if callable(resolve_schema_type):
        return str(resolve_schema_type(schema) or "").strip().lower()
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type.strip().lower()
    if isinstance(raw_type, list):
        lowered = [str(item).strip().lower() for item in raw_type if str(item).strip()]
        return lowered[0] if lowered else ""
    return ""


def _normalize_text_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = str(value or "").strip().lower().replace(".", "_").replace("-", "_")
        for token in normalized.replace("/", "_").split("_"):
            token = token.strip()
            if token:
                tokens.add(token)
    return tokens


def infer_tool_harness_profile(
    tool: Dict[str, Any],
    *,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> Dict[str, Any]:
    tool_name = str(tool.get("name", "")).strip()
    server_name = str(tool.get("server", "")).strip()
    description = str(tool.get("description", "") or "").strip()
    schema = tool.get("input_schema") or {}
    properties = _schema_properties(schema)
    required_fields = _schema_required_fields(schema)

    name_tokens = _normalize_text_tokens(tool_name, description)
    server_tokens = _normalize_text_tokens(server_name)

    property_profiles: list[dict[str, Any]] = []
    path_like_fields: list[str] = []
    url_like_fields: list[str] = []
    text_like_fields: list[str] = []
    image_like_fields: list[str] = []
    array_like_fields: list[str] = []

    for property_name, property_schema in properties.items():
        normalized_name = str(property_name or "").strip()
        schema_dict = property_schema if isinstance(property_schema, dict) else {}
        normalized_type = _resolve_type(schema_dict, resolve_schema_type)
        normalized_name_lower = normalized_name.lower()
        field_tokens = _normalize_text_tokens(
            normalized_name_lower,
            str(schema_dict.get("description") or ""),
            str(schema_dict.get("title") or ""),
        )

        is_path_like = any(hint in normalized_name_lower for hint in PATH_FIELD_HINTS) or any(
            hint in field_tokens for hint in PATH_FIELD_HINTS
        )
        is_url_like = normalized_name_lower in {"url", "uri"} or "url" in field_tokens or "uri" in field_tokens
        is_text_like = any(hint in normalized_name_lower for hint in TEXT_FIELD_HINTS) or any(
            hint in field_tokens for hint in TEXT_FIELD_HINTS
        )
        is_image_like = any(hint in normalized_name_lower for hint in IMAGE_FIELD_HINTS) or any(
            hint in field_tokens for hint in IMAGE_FIELD_HINTS
        )

        if normalized_type == "array":
            array_like_fields.append(normalized_name)
        if is_path_like:
            path_like_fields.append(normalized_name)
        if is_url_like:
            url_like_fields.append(normalized_name)
        if is_text_like:
            text_like_fields.append(normalized_name)
        if is_image_like:
            image_like_fields.append(normalized_name)

        property_profiles.append(
            {
                "name": normalized_name,
                "type": normalized_type,
                "required": normalized_name in required_fields,
                "path_like": is_path_like,
                "url_like": is_url_like,
                "text_like": is_text_like,
                "image_like": is_image_like,
            }
        )

    is_manual_server = any(token in MANUAL_SERVER_HINTS for token in server_tokens)
    has_read_only_hint = any(token in READ_ONLY_NAME_HINTS for token in name_tokens)
    has_write_hint = any(token in WRITE_NAME_HINTS for token in name_tokens)
    has_text_inputs = bool(text_like_fields)
    has_path_inputs = bool(path_like_fields)
    has_url_inputs = bool(url_like_fields)
    has_image_inputs = bool(image_like_fields)
    has_array_inputs = bool(array_like_fields)
    is_manual_only = tool_name.lower() in MANUAL_TOOL_NAMES or is_manual_server

    if has_write_hint:
        default_visibility = "manual_only"
    elif has_read_only_hint:
        default_visibility = "auto_candidate"
    else:
        default_visibility = "manual_only"

    if is_manual_only:
        default_visibility = "manual_only"

    automation_class = "manual_only"
    if default_visibility == "auto_candidate" and required_fields:
        automation_class = "auto_routable_manual_confirm"
    elif default_visibility == "auto_candidate":
        automation_class = "auto_executable"

    if is_manual_only:
        automation_class = "manual_only"

    if has_write_hint:
        risk_level = "high"
    elif has_path_inputs or has_url_inputs:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "tool_key": f"{server_name}.{tool_name}".strip("."),
        "server": server_name,
        "name": tool_name,
        "description": description,
        "required_fields": required_fields,
        "property_count": len(properties),
        "properties": property_profiles,
        "capabilities": {
            "read_only": has_read_only_hint and not has_write_hint,
            "mutation": has_write_hint,
            "path_input": has_path_inputs,
            "url_input": has_url_inputs,
            "text_input": has_text_inputs,
            "image_input": has_image_inputs,
            "array_input": has_array_inputs,
            "manual_server": is_manual_server,
            "manual_only": is_manual_only,
        },
        "path_like_fields": path_like_fields,
        "url_like_fields": url_like_fields,
        "text_like_fields": text_like_fields,
        "image_like_fields": image_like_fields,
        "automation_class": automation_class,
        "default_visibility": default_visibility,
        "risk_level": risk_level,
    }


def summarize_tool_harness_capabilities(profile: Dict[str, Any]) -> list[str]:
    capabilities = profile.get("capabilities", {}) if isinstance(profile, dict) else {}
    labels: list[str] = []
    if capabilities.get("read_only"):
        labels.append("read_only")
    if capabilities.get("mutation"):
        labels.append("mutation")
    if capabilities.get("path_input"):
        labels.append("path_input")
    if capabilities.get("url_input"):
        labels.append("url_input")
    if capabilities.get("text_input"):
        labels.append("text_input")
    if capabilities.get("image_input"):
        labels.append("image_input")
    if capabilities.get("array_input"):
        labels.append("array_input")
    if capabilities.get("manual_server"):
        labels.append("manual_server")
    if capabilities.get("manual_only"):
        labels.append("manual_only")
    return labels


def build_harness_summary_for_tools(
    tools: Iterable[Dict[str, Any]],
    *,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> list[Dict[str, Any]]:
    return [
        infer_tool_harness_profile(tool, resolve_schema_type=resolve_schema_type)
        for tool in tools
    ]
