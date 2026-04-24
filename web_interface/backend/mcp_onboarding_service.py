# -*- coding: utf-8 -*-

"""Services for MCP tool onboarding audit and minimal self-tests."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tool_harness import infer_tool_harness_profile, summarize_tool_harness_capabilities


logger = logging.getLogger(__name__)


class MCPToolOnboardingService:
    """Encapsulate MCP tool onboarding audit and safe self-test routines."""

    def __init__(
        self,
        *,
        project_root: Path,
        get_default_manager: Callable[[], Any],
        safe_workspace_root: Callable[[str], Optional[Path]],
        infer_tool_arguments_from_context: Callable[..., tuple[Dict[str, Any], List[str]]],
        normalize_tool_arguments_runtime: Callable[..., Dict[str, Any]],
        is_auto_tool_allowed: Callable[..., bool],
        arguments_ready_for_auto_execution: Callable[..., bool],
        tool_key: Callable[[str, str], str],
        is_fetch_like_tool: Callable[[Dict[str, Any]], bool],
        is_file_allowed_roots_tool: Callable[[Dict[str, Any]], bool],
        tool_has_path_like_argument: Callable[[Dict[str, Any]], bool],
        is_file_listing_tool: Callable[[Dict[str, Any]], bool],
        is_file_info_tool: Callable[[Dict[str, Any]], bool],
        is_file_read_tool: Callable[[Dict[str, Any]], bool],
        is_file_search_tool: Callable[[Dict[str, Any]], bool],
    ) -> None:
        self.project_root = project_root
        self.get_default_manager = get_default_manager
        self.safe_workspace_root = safe_workspace_root
        self.infer_tool_arguments_from_context = infer_tool_arguments_from_context
        self.normalize_tool_arguments_runtime = normalize_tool_arguments_runtime
        self.is_auto_tool_allowed = is_auto_tool_allowed
        self.arguments_ready_for_auto_execution = arguments_ready_for_auto_execution
        self.tool_key = tool_key
        self.is_fetch_like_tool = is_fetch_like_tool
        self.is_file_allowed_roots_tool = is_file_allowed_roots_tool
        self.tool_has_path_like_argument = tool_has_path_like_argument
        self.is_file_listing_tool = is_file_listing_tool
        self.is_file_info_tool = is_file_info_tool
        self.is_file_read_tool = is_file_read_tool
        self.is_file_search_tool = is_file_search_tool

    def build_audit_for_manager(
        self,
        active_manager: Optional[Any] = None,
        workspace_root: str = "",
    ) -> dict[str, Any]:
        manager_ref = active_manager or self.get_default_manager()
        tools = manager_ref.get_all_tools() if manager_ref else []
        if not tools:
            return {
                "ok": False,
                "summary": {
                    "total_tools": 0,
                    "auto_routable_tools": 0,
                    "auto_executable_tools": 0,
                    "manual_only_tools": 0,
                    "schema_risk_tools": 0,
                },
                "issues": ["No MCP tools are currently loaded."],
                "tools": [],
            }

        resolve_schema_type = (
            manager_ref._resolve_schema_type
            if manager_ref and hasattr(manager_ref, "_resolve_schema_type")
            else None
        )

        report_items: list[dict[str, Any]] = []
        issue_messages: list[str] = []
        auto_routable_count = 0
        auto_executable_count = 0
        manual_only_count = 0
        schema_risk_count = 0
        workspace_candidate_root = self.safe_workspace_root(workspace_root)
        sample_root_path = workspace_candidate_root or self.project_root.resolve()
        project_root_str = str(sample_root_path)
        self_test_root = str(sample_root_path / "artifacts" / "manual_test")
        readme_path = str(sample_root_path / "README.md")
        pixel_path = str(sample_root_path / "artifacts" / "manual_test" / "pixel.png")

        if workspace_candidate_root is not None:
            workspace_manual_root = sample_root_path / ".mcp-mirror" / "self_test"
            workspace_manual_root.mkdir(parents=True, exist_ok=True)
            self_test_root = str(workspace_manual_root)

            workspace_readme = sample_root_path / "README.md"
            if workspace_readme.exists():
                readme_path = str(workspace_readme)
            else:
                workspace_readme = workspace_manual_root / "workspace_readme.txt"
                if not workspace_readme.exists():
                    workspace_readme.write_text(
                        "Workspace onboarding self-test file for MCP Mirror.\n",
                        encoding="utf-8",
                    )
                readme_path = str(workspace_readme)

            workspace_pixel = workspace_manual_root / "pixel.png"
            source_pixel = self.project_root / "artifacts" / "manual_test" / "pixel.png"
            try:
                if source_pixel.exists() and not workspace_pixel.exists():
                    workspace_pixel.write_bytes(source_pixel.read_bytes())
            except Exception:
                pass
            if workspace_pixel.exists():
                pixel_path = str(workspace_pixel)

        for tool in tools:
            server_name = str(tool.get("server", "")).strip()
            tool_name = str(tool.get("name", "")).strip()
            tool_label = f"{server_name}.{tool_name}".strip(".")
            schema = tool.get("input_schema") or {}
            properties = schema.get("properties") if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else {}
            required_fields = schema.get("required") if isinstance(schema, dict) and isinstance(schema.get("required"), list) else []
            missing_property_names = [
                str(field_name)
                for field_name in required_fields
                if str(field_name).strip() and str(field_name) not in properties
            ]

            auto_allowed = self.is_auto_tool_allowed(
                tool,
                resolve_schema_type=resolve_schema_type,
            )
            harness_profile = infer_tool_harness_profile(
                tool,
                resolve_schema_type=resolve_schema_type,
            )
            harness_capabilities = summarize_tool_harness_capabilities(harness_profile)
            inferred_arguments, inferred_fields = self.infer_tool_arguments_from_context(
                tool_name=tool_name,
                server_name=server_name,
                arguments={},
                content=f"Please inspect http://127.0.0.1:8000/health and {readme_path}",
                attachments=[
                    {
                        "original_filename": Path(readme_path).name,
                        "filename": Path(readme_path).name,
                        "file_path": readme_path,
                        "path": readme_path,
                        "url": "http://127.0.0.1:8000/health",
                    }
                ],
                active_mcp_manager=manager_ref,
                workspace_root=str(sample_root_path),
            )
            auto_executable = bool(
                auto_allowed
                and self.arguments_ready_for_auto_execution(
                    tool,
                    inferred_arguments,
                    content=f"Please inspect http://127.0.0.1:8000/health and {readme_path}",
                    resolve_schema_type=resolve_schema_type,
                )
            )

            schema_warnings: list[str] = []
            if not isinstance(schema, dict) or not schema:
                schema_warnings.append("missing_input_schema")
            if required_fields and not properties:
                schema_warnings.append("required_without_properties")
            if missing_property_names:
                schema_warnings.append("required_field_missing_property_schema")

            for property_name, property_schema in properties.items():
                if not isinstance(property_schema, dict):
                    schema_warnings.append(f"property_schema_not_object:{property_name}")
                    continue
                resolved_type = (
                    str(resolve_schema_type(property_schema)).strip().lower()
                    if callable(resolve_schema_type)
                    else str(property_schema.get("type", "")).strip().lower()
                )
                if not resolved_type:
                    schema_warnings.append(f"property_type_unresolved:{property_name}")
                if property_schema.get("enum") is not None and not isinstance(property_schema.get("enum"), list):
                    schema_warnings.append(f"enum_not_list:{property_name}")

            automation_class = "manual_only"
            if auto_executable:
                automation_class = "auto_executable"
            elif auto_allowed:
                automation_class = "auto_routable_manual_confirm"
            elif harness_profile.get("automation_class") in {"auto_executable", "auto_routable_manual_confirm"}:
                automation_class = str(harness_profile.get("automation_class"))

            if auto_allowed:
                auto_routable_count += 1
            else:
                manual_only_count += 1
            if auto_executable:
                auto_executable_count += 1
            if schema_warnings:
                schema_risk_count += 1
                issue_messages.append(f"{tool_label}: " + ", ".join(schema_warnings[:3]))

            self_test = self._build_tool_minimal_self_test_plan(
                tool=tool,
                automation_class=automation_class,
                required_fields=[str(field_name) for field_name in required_fields if str(field_name).strip()],
                inferred_fields=inferred_fields,
                schema_warnings=schema_warnings,
                project_root_str=project_root_str,
                self_test_root=self_test_root,
                readme_path=readme_path,
                pixel_path=pixel_path,
            )

            report_items.append({
                "tool_key": self.tool_key(server_name, tool_name),
                "server": server_name,
                "name": tool_name,
                "description": str(tool.get("description", "") or ""),
                "automation_class": automation_class,
                "auto_routable": auto_allowed,
                "auto_executable": auto_executable,
                "inferred_fields_sample": inferred_fields,
                "required_fields": [str(field_name) for field_name in required_fields if str(field_name).strip()],
                "schema_property_count": len(properties),
                "schema_warnings": schema_warnings,
                "harness": {
                    "capabilities": harness_capabilities,
                    "risk_level": harness_profile.get("risk_level", "unknown"),
                    "path_like_fields": harness_profile.get("path_like_fields", []),
                    "url_like_fields": harness_profile.get("url_like_fields", []),
                    "text_like_fields": harness_profile.get("text_like_fields", []),
                    "image_like_fields": harness_profile.get("image_like_fields", []),
                    "default_visibility": harness_profile.get("default_visibility", "manual_only"),
                    "server_visibility_model": "server_level_allowMCPs",
                },
                "self_test": self_test,
            })

        report_items.sort(key=lambda item: (item["automation_class"], item["tool_key"]))
        issue_messages = issue_messages[:20]

        return {
            "ok": schema_risk_count == 0,
            "summary": {
                "total_tools": len(report_items),
                "auto_routable_tools": auto_routable_count,
                "auto_executable_tools": auto_executable_count,
                "manual_only_tools": manual_only_count,
                "schema_risk_tools": schema_risk_count,
            },
            "issues": issue_messages,
            "tools": report_items,
        }

    def build_default_audit(self) -> dict[str, Any]:
        return self.build_audit_for_manager(self.get_default_manager())

    def _build_tool_minimal_self_test_plan(
        self,
        *,
        tool: Dict[str, Any],
        automation_class: str,
        required_fields: List[str],
        inferred_fields: List[str],
        schema_warnings: List[str],
        project_root_str: str,
        self_test_root: str,
        readme_path: str,
        pixel_path: str,
    ) -> dict[str, Any]:
        server_name = str(tool.get("server", "")).strip()
        tool_name = str(tool.get("name", "")).strip()
        normalized_tool_name = tool_name.strip().lower()
        normalized_server_name = server_name.strip().lower()
        schema = tool.get("input_schema") or {}
        properties = schema.get("properties") if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else {}
        harness_profile = infer_tool_harness_profile(tool)
        harness_capabilities = harness_profile.get("capabilities", {}) if isinstance(harness_profile, dict) else {}

        sample_arguments: Dict[str, Any] = {}
        status = "planned"
        reason = "Minimal self-test is not yet classified."
        safe_to_run = False
        expected_outcome = ""
        gate_required = False

        if schema_warnings:
            status = "schema_risk"
            reason = "Input schema has unresolved warnings. Fix schema shape before running self-test."
            expected_outcome = "Schema warnings should be cleared before onboarding gate passes."
        elif self.is_fetch_like_tool(tool):
            sample_arguments = {
                "url": "http://127.0.0.1:8000/health",
                "max_length": 1200,
            }
            status = "ready"
            safe_to_run = True
            gate_required = True
            reason = "Read-only local health fetch."
            expected_outcome = "Returns backend /health payload."
        elif self.is_file_allowed_roots_tool(tool):
            sample_arguments = {}
            status = "ready"
            safe_to_run = True
            gate_required = True
            reason = "Safe capability discovery call with no arguments."
            expected_outcome = "Returns allowed root directories."
        elif normalized_server_name == "cdar_mcp" and normalized_tool_name == "cdar_compositional_decomposed_adaptive_reasoning":
            sample_arguments = {
                "image_path": pixel_path,
                "question": "Please briefly describe the visible content.",
            }
            if "enable_decomposition" in properties:
                sample_arguments["enable_decomposition"] = True
            status = "ready"
            safe_to_run = True
            gate_required = False
            reason = "Read-only vision reasoning against bundled pixel sample."
            expected_outcome = "Returns a valid CDAR response or an explicit upstream availability error."
        elif self.tool_has_path_like_argument(tool):
            if normalized_tool_name == "read_multiple_files":
                sample_arguments = {"paths": [readme_path]}
                status = "ready"
                safe_to_run = True
                gate_required = True
                reason = "Read-only multi-file sample with a single readable file path."
                expected_outcome = "Returns one file content block."
            elif normalized_tool_name == "read_media_file":
                sample_arguments = {"path": pixel_path}
                status = "ready"
                safe_to_run = True
                gate_required = True
                reason = "Read-only media probe against bundled 1x1 PNG sample."
                expected_outcome = "Returns image MIME type and encoded content."
            elif self.is_file_listing_tool(tool):
                sample_arguments = {"path": self_test_root}
                if "sortBy" in properties:
                    sample_arguments["sortBy"] = "name"
                status = "ready"
                safe_to_run = True
                gate_required = True
                reason = "Read-only directory inspection inside a small dedicated self-test folder."
                expected_outcome = "Returns the dedicated self-test folder structure."
            elif self.is_file_info_tool(tool):
                sample_arguments = {"path": readme_path}
                status = "ready"
                safe_to_run = True
                gate_required = True
                reason = "Read-only file metadata check on README."
                expected_outcome = "Returns README metadata."
            elif self.is_file_read_tool(tool):
                sample_arguments = {"path": readme_path}
                if "head" in properties:
                    sample_arguments["head"] = 12
                status = "ready"
                safe_to_run = True
                gate_required = True
                reason = "Read-only text file sample inside allowed workspace."
                expected_outcome = "Returns README text preview."
            elif self.is_file_search_tool(tool):
                sample_arguments = {"path": self_test_root, "pattern": "*.png"}
                if "excludePatterns" in properties:
                    sample_arguments["excludePatterns"] = ["node_modules/**", ".venv/**"]
                status = "ready"
                safe_to_run = True
                gate_required = True
                reason = "Read-only file search inside the dedicated self-test folder."
                expected_outcome = "Returns small fixture files from the self-test folder."
            else:
                status = "manual_only"
                reason = "Filesystem mutation tool requires explicit operator confirmation."
                expected_outcome = "Manual validation only."
        elif normalized_server_name == "memory":
            if normalized_tool_name in {"read_graph"}:
                sample_arguments = {}
                status = "manual_only"
                safe_to_run = False
                reason = "Memory graph access is intentionally excluded from automatic onboarding gate to avoid mixing product diagnostics with research memory state."
                expected_outcome = "Manual verification only."
            elif normalized_tool_name == "search_nodes":
                sample_arguments = {"query": "MCP Mirror"}
                status = "manual_only"
                safe_to_run = False
                reason = "Memory search is readable but intentionally left out of automatic gate to protect runtime memory isolation."
                expected_outcome = "Manual verification only."
            else:
                status = "manual_only"
                safe_to_run = False
                reason = "Memory mutation tools must stay operator-confirmed."
                expected_outcome = "Manual validation only."
        elif normalized_server_name == "sequential_thinking" and normalized_tool_name == "sequentialthinking":
            sample_arguments = {
                "thought": "Validate that the onboarding self-test can reach the server.",
                "nextThoughtNeeded": False,
                "thoughtNumber": 1,
                "totalThoughts": 1,
            }
            status = "manual_only"
            safe_to_run = False
            reason = "Sequential thinking is intentionally excluded from automatic onboarding gate because it is a stateful reasoning surface, even though it is non-destructive."
            expected_outcome = "Manual validation only."
        elif harness_capabilities.get("url_input") and harness_capabilities.get("read_only"):
            url_field = next(iter(harness_profile.get("url_like_fields", []) or []), "url")
            sample_arguments = {str(url_field): "http://127.0.0.1:8000/health"}
            for property_name, property_schema in properties.items():
                normalized_property_name = str(property_name).strip()
                if normalized_property_name in sample_arguments:
                    continue
                property_type = ""
                if isinstance(property_schema, dict):
                    property_type = str(property_schema.get("type", "") or "").strip().lower()
                if property_type in {"integer", "number"} and normalized_property_name.lower() in {"max_length", "limit", "timeout"}:
                    sample_arguments[normalized_property_name] = 1200
            status = "ready"
            safe_to_run = True
            gate_required = False
            reason = "Generic schema-driven read-only URL self-test."
            expected_outcome = "Returns a response for the local backend health URL."
        elif harness_capabilities.get("text_input") and harness_capabilities.get("read_only"):
            text_field = next(iter(harness_profile.get("text_like_fields", []) or []), "query")
            sample_arguments = {str(text_field): "MCP Mirror onboarding self-test"}
            status = "ready"
            safe_to_run = True
            gate_required = False
            reason = "Generic schema-driven read-only text/query self-test."
            expected_outcome = "Returns a valid response for a small synthetic text input."
        elif harness_capabilities.get("path_input") and harness_capabilities.get("read_only"):
            path_field = next(iter(harness_profile.get("path_like_fields", []) or []), "path")
            sample_arguments = {str(path_field): readme_path}
            status = "ready"
            safe_to_run = True
            gate_required = False
            reason = "Generic schema-driven read-only path self-test against README."
            expected_outcome = "Returns a valid read-only response for the sample workspace file."
        else:
            status = "missing_arguments" if required_fields else "manual_only"
            reason = (
                "No generic safe self-test template could be derived from the current schema."
                if required_fields
                else "Tool is not marked for automatic onboarding self-test."
            )
            expected_outcome = "Manual validation only."

        return {
            "status": status,
            "safe_to_run": safe_to_run,
            "reason": reason,
            "expected_outcome": expected_outcome,
            "gate_required": gate_required,
            "sample_arguments": sample_arguments,
            "required_fields": required_fields,
            "inferred_fields": inferred_fields,
            "command_hint": "POST /api/mcp/tool-onboarding-audit/run",
        }

    async def execute_tool_onboarding_self_test(
        self,
        *,
        tool: Dict[str, Any],
        plan: Dict[str, Any],
        active_manager: Optional[Any] = None,
    ) -> dict[str, Any]:
        server_name = str(tool.get("server", "")).strip()
        tool_name = str(tool.get("name", "")).strip()
        normalized_plan = dict(plan or {})
        started_at = datetime.now().isoformat()
        sample_arguments = self.normalize_tool_arguments_runtime(
            tool_name=tool_name,
            server_name=server_name,
            arguments=dict(normalized_plan.get("sample_arguments") or {}),
            active_mcp_manager=active_manager or self.get_default_manager(),
        )
        safe_to_run = bool(normalized_plan.get("safe_to_run", False))
        status = str(normalized_plan.get("status", "planned"))

        if not safe_to_run or status not in {"ready", "planned"}:
            return {
                "tool_key": self.tool_key(server_name, tool_name),
                "server": server_name,
                "name": tool_name,
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "ok": False,
                "status": status,
                "skipped": True,
                "reason": str(normalized_plan.get("reason", "Self-test is not safe to run automatically.")),
                "arguments": sample_arguments,
            }

        manager_ref = active_manager or self.get_default_manager()
        if not manager_ref or not hasattr(manager_ref, "call_tool"):
            return {
                "tool_key": self.tool_key(server_name, tool_name),
                "server": server_name,
                "name": tool_name,
                "started_at": started_at,
                "completed_at": datetime.now().isoformat(),
                "ok": False,
                "status": "unavailable",
                "skipped": True,
                "reason": "MCP manager is unavailable.",
                "arguments": sample_arguments,
            }

        t0 = time.time()
        result = await manager_ref.call_tool(tool_name, sample_arguments, server_name)
        latency_ms = round((time.time() - t0) * 1000, 1)
        success = bool(isinstance(result, dict) and result.get("success"))
        result_preview = ""
        error_preview = ""
        if isinstance(result, dict):
            if result.get("result") is not None:
                result_preview = str(result.get("result"))[:600]
            error_preview = str(result.get("error", result.get("message", "")) or "")[:600]
        else:
            result_preview = str(result)[:600]

        completed_status = "passed" if success else "failed"
        return {
            "tool_key": self.tool_key(server_name, tool_name),
            "server": server_name,
            "name": tool_name,
            "started_at": started_at,
            "completed_at": datetime.now().isoformat(),
            "ok": success,
            "status": completed_status,
            "skipped": False,
            "reason": "" if success else (error_preview or "Tool self-test failed."),
            "arguments": sample_arguments,
            "latency_ms": latency_ms,
            "result_preview": result_preview,
            "error_preview": error_preview,
        }
