#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Pre/post verification for MCP tool execution in the System Harness Plane."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional


def _local_path_candidate(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return ""
    return text


def precheck_mcp_tool_call(
    *,
    contract: Dict[str, Any],
    compiled_arguments: Dict[str, Any],
    missing_required: list[str],
    path_allowed_fn: Optional[Callable[[str, str], bool]] = None,
    workspace_root: str = "",
) -> Dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[Dict[str, Any]] = []

    if missing_required:
        errors.append("missing_required_arguments")
        checks.append({
            "name": "required_arguments_compiled",
            "passed": False,
            "details": {"missing_required": list(missing_required)},
        })
    else:
        checks.append({
            "name": "required_arguments_compiled",
            "passed": True,
            "details": {},
        })

    path_like_fields = [
        str(name).strip()
        for name in contract.get("path_like_fields", [])
        if str(name).strip()
    ]
    for field_name in path_like_fields:
        local_path = _local_path_candidate(compiled_arguments.get(field_name))
        if not local_path:
            continue
        path_ok = True
        if callable(path_allowed_fn):
            try:
                path_ok = bool(path_allowed_fn(local_path, workspace_root))
            except Exception:
                path_ok = False
        checks.append({
            "name": f"path_allowed:{field_name}",
            "passed": path_ok,
            "details": {"path": local_path},
        })
        if not path_ok:
            errors.append("path_outside_allowed_roots")

        try:
            candidate = Path(local_path)
            if candidate.is_absolute():
                exists_ok = candidate.exists()
                checks.append({
                    "name": f"path_exists:{field_name}",
                    "passed": exists_ok,
                    "details": {"path": local_path},
                })
                if not exists_ok:
                    warnings.append("path_missing_on_local_filesystem")
                elif not candidate.is_file():
                    warnings.append("path_is_not_file")
        except Exception:
            warnings.append("path_stat_failed")

    blocking = bool(errors)
    reason = ""
    suggestion = ""
    if "missing_required_arguments" in errors:
        reason = "Harness precheck blocked the tool call because required arguments are still missing after compilation."
        suggestion = "Upload the file, include the URL, or phrase the request more explicitly so the compiler can ground the missing fields."
    elif "path_outside_allowed_roots" in errors:
        reason = "Harness precheck blocked the tool call because the local path is outside current filesystem allowed roots."
        suggestion = "Upload the file into the workspace copy or extend the filesystem server allowed directories."

    return {
        "phase": "precheck",
        "passed": not blocking,
        "blocking": blocking,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "reason": reason,
        "suggestion": suggestion,
    }


def postcheck_mcp_tool_result(
    *,
    contract: Dict[str, Any],
    result: Any,
) -> Dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[Dict[str, Any]] = []

    if not isinstance(result, dict):
        errors.append("result_not_structured")
        checks.append({
            "name": "structured_result",
            "passed": False,
            "details": {},
        })
        return {
            "phase": "postcheck",
            "passed": False,
            "commit_allowed": False,
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
            "recovery": {
                "strategy": "retry_with_structured_runtime",
                "reason": "Tool result is not a structured payload.",
            },
        }

    real_mcp = bool(result.get("_real_mcp_call"))
    success = bool(result.get("success"))
    error_text = str(result.get("error") or result.get("message") or "").strip()
    result_text = str(result.get("result") or "").strip()
    lowered_error = error_text.lower()

    checks.append({
        "name": "real_mcp_runtime_result",
        "passed": real_mcp,
        "details": {"real_mcp_call": real_mcp},
    })
    if not real_mcp:
        errors.append("not_real_mcp_result")

    checks.append({
        "name": "success_flag",
        "passed": success,
        "details": {"success": success},
    })
    if not success:
        errors.append("tool_execution_failed")

    validation_error = any(marker in lowered_error for marker in {
        "invalid input",
        "validation error",
        "missing required",
        "input validation error",
    })
    checks.append({
        "name": "no_validation_error",
        "passed": not validation_error,
        "details": {"error": error_text[:300]},
    })
    if validation_error:
        errors.append("runtime_validation_error")

    decoded_ok = bool(result_text or error_text or isinstance(result.get("raw_result"), str))
    checks.append({
        "name": "decoded_text_or_structured_error",
        "passed": decoded_ok,
        "details": {},
    })
    if not decoded_ok:
        warnings.append("empty_tool_payload")

    commit_allowed = not errors
    recovery_strategy = "none"
    recovery_reason = ""
    if "runtime_validation_error" in errors:
        recovery_strategy = "retry_after_argument_recompile"
        recovery_reason = "Runtime rejected the tool arguments."
    elif "tool_execution_failed" in errors and error_text:
        recovery_strategy = "surface_runtime_error_and_offer_retry"
        recovery_reason = error_text[:300]

    return {
        "phase": "postcheck",
        "passed": commit_allowed,
        "commit_allowed": commit_allowed,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "recovery": {
            "strategy": recovery_strategy,
            "reason": recovery_reason,
        },
        "contract_tool_key": contract.get("tool_key", ""),
    }
