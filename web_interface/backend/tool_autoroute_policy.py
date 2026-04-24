#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Dynamic auto-routing policy for MCP tools.

This module keeps automatic tool eligibility out of app.py so new MCP servers
can be added without editing the main chat entrypoint.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Optional

from tool_harness import infer_tool_harness_profile

READ_ONLY_VERBS = {
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
}

STATEFUL_VERBS = {
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
}

STATEFUL_ARGUMENT_HINTS = {
    "content",
    "text",
    "entity",
    "entities",
    "observation",
    "observations",
    "payload",
    "body",
    "patch",
    "diff",
}

MANUAL_ONLY_SERVER_HINTS = {
    "memory",
    "terminal",
}
MANUAL_ONLY_TOOL_NAMES = {
    "list_allowed_directories",
    "read_graph",
    "sequentialthinking",
    "execute_command",
}

URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
AUTO_TOOL_MIN_SCORE = 0.55


def tool_key(server_name: str, tool_name: str) -> str:
    return f"{str(server_name or '').strip()}.{str(tool_name or '').strip()}".strip(".")


def _tokenize_text(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if token
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
    return [str(field) for field in required if str(field).strip()]


def _resolve_type(
    schema: Dict[str, Any],
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]],
) -> str:
    if callable(resolve_schema_type):
        return str(resolve_schema_type(schema) or "").strip().lower()
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type.strip().lower()
    return ""


def is_auto_tool_allowed(
    tool: Dict[str, Any],
    *,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> bool:
    profile = infer_tool_harness_profile(tool, resolve_schema_type=resolve_schema_type)
    capabilities = profile.get("capabilities", {})
    if capabilities.get("manual_only") or capabilities.get("mutation"):
        return False
    if capabilities.get("read_only") and (
        capabilities.get("path_input")
        or capabilities.get("url_input")
        or capabilities.get("text_input")
        or not profile.get("required_fields")
    ):
        return True

    tool_name = str(tool.get("name", "")).strip()
    server_name = str(tool.get("server", "")).strip().lower()
    if not tool_name:
        return False
    if tool_name in MANUAL_ONLY_TOOL_NAMES:
        return False

    name_tokens = _tokenize_text(tool_name.replace(".", "_"))
    description_tokens = _tokenize_text(str(tool.get("description", "") or ""))
    combined_tokens = name_tokens | description_tokens

    if any(hint == server_name or hint in combined_tokens for hint in MANUAL_ONLY_SERVER_HINTS):
        return False
    if combined_tokens & STATEFUL_VERBS:
        return False
    if not (combined_tokens & READ_ONLY_VERBS):
        return False

    schema = tool.get("input_schema") or {}
    properties = _schema_properties(schema)
    property_names = {str(key).strip().lower() for key in properties.keys()}
    if property_names & STATEFUL_ARGUMENT_HINTS:
        return False

    for property_name, property_schema in properties.items():
        normalized_name = str(property_name).strip().lower()
        normalized_type = _resolve_type(property_schema if isinstance(property_schema, dict) else {}, resolve_schema_type)
        if normalized_name in {"content", "text", "body"} and normalized_type in {"string", "object", "array"}:
            return False

    return True


def arguments_ready_for_auto_execution(
    tool: Dict[str, Any],
    arguments: Dict[str, Any],
    *,
    content: str,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> bool:
    schema = tool.get("input_schema") or {}
    required_fields = _schema_required_fields(schema)
    if not required_fields:
        return True

    profile = infer_tool_harness_profile(tool, resolve_schema_type=resolve_schema_type)
    capabilities = profile.get("capabilities", {})
    if capabilities.get("manual_only") or capabilities.get("mutation"):
        return False

    properties = _schema_properties(schema)
    normalized_content = str(content or "").strip()

    for field_name in required_fields:
        value = arguments.get(field_name)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        property_schema = properties.get(field_name) if isinstance(properties, dict) else {}
        if isinstance(value, str):
            resolved_type = _resolve_type(property_schema if isinstance(property_schema, dict) else {}, resolve_schema_type)
            if resolved_type in {"integer", "number", "boolean"}:
                return False

    if str(tool.get("name", "")).strip().lower() == "fetch":
        # Keep legacy safety: explicit URL in user text is always acceptable.
        if URL_PATTERN.search(normalized_content):
            return True
        # Also allow runtime-generated web-search URL fallback when arguments are ready.
        url_value = arguments.get("url")
        if not isinstance(url_value, str) or not URL_PATTERN.search(url_value.strip()):
            return False

    return True


def filter_auto_tool_candidates(
    tools: Iterable[Dict[str, Any]],
    *,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> list[Dict[str, Any]]:
    return [
        tool
        for tool in tools
        if is_auto_tool_allowed(tool, resolve_schema_type=resolve_schema_type)
    ]
