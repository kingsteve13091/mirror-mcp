#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Schema-aware MCP tool contracts for the System Harness Plane."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from tool_harness import infer_tool_harness_profile, summarize_tool_harness_capabilities


def build_mcp_tool_contract(
    tool: Dict[str, Any],
    *,
    resolve_schema_type: Optional[Callable[[Dict[str, Any]], str]] = None,
) -> Dict[str, Any]:
    profile = infer_tool_harness_profile(tool, resolve_schema_type=resolve_schema_type)
    tool_name = str(tool.get("name", "")).strip()
    server_name = str(tool.get("server", "")).strip()
    tool_key = f"{server_name}.{tool_name}".strip(".")
    capabilities = summarize_tool_harness_capabilities(profile)

    preconditions = [
        "tool_visible_in_effective_runtime",
        "required_arguments_compiled",
    ]
    postconditions = [
        "real_mcp_runtime_result",
        "no_validation_error",
    ]
    recovery_hints = [
        "recompile_arguments_from_schema_and_context",
    ]

    if "path_input" in capabilities:
        preconditions.extend([
            "path_argument_grounded_when_required",
            "local_path_within_allowed_roots",
        ])
        recovery_hints.extend([
            "prefer_uploaded_attachment_or_workspace_relative_path",
            "suggest_allowed_root_or_workspace_copy_when_denied",
        ])

    if "url_input" in capabilities:
        preconditions.append("url_argument_grounded_when_required")
        recovery_hints.append("extract_url_from_query_or_attachment_metadata")

    if "text_input" in capabilities:
        preconditions.append("text_argument_grounded_when_required")

    if "image_input" in capabilities:
        preconditions.append("image_input_grounded_when_required")
        recovery_hints.append("prefer_uploaded_image_attachment")

    normalized_tool_name = tool_name.lower()
    if normalized_tool_name in {"read_file", "read_text_file"}:
        preconditions.extend([
            "target_path_exists_when_local",
            "target_path_is_file_when_local",
        ])
        postconditions.append("decoded_text_or_structured_error")
    elif normalized_tool_name == "sequentialthinking":
        preconditions.append("sequentialthinking_defaults_compilable")
        postconditions.append("thought_payload_accepted_by_runtime")
        recovery_hints.append("fill_missing_thought_defaults")

    return {
        "contract_version": "system-harness-v1",
        "source": "system_harness_plane",
        "tool_key": tool_key,
        "server_name": server_name,
        "tool_name": tool_name,
        "risk_level": profile.get("risk_level", "unknown"),
        "automation_class": profile.get("automation_class", "manual_only"),
        "default_visibility": profile.get("default_visibility", "manual_only"),
        "required_fields": profile.get("required_fields", []),
        "path_like_fields": profile.get("path_like_fields", []),
        "url_like_fields": profile.get("url_like_fields", []),
        "text_like_fields": profile.get("text_like_fields", []),
        "image_like_fields": profile.get("image_like_fields", []),
        "capabilities": capabilities,
        "preconditions": preconditions,
        "postconditions": postconditions,
        "recovery_hints": recovery_hints,
        "commit_rule": "verified_success_only",
    }
