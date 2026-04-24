#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""System Harness Plane for MCP Mirror."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from mcp_argument_compiler import compile_mcp_tool_arguments
from mcp_contracts import build_mcp_tool_contract
from mcp_verifier import postcheck_mcp_tool_result, precheck_mcp_tool_call
from tool_harness import infer_tool_harness_profile, summarize_tool_harness_capabilities


class MCPHarnessExecutionEngine:
    """Schema-aware harness wrapper around real MCP execution."""

    def __init__(
        self,
        *,
        infer_tool_arguments_from_context: Optional[Callable[..., tuple[Dict[str, Any], List[str]]]] = None,
        normalize_tool_arguments_runtime: Optional[Callable[..., Dict[str, Any]]] = None,
        path_allowed_fn: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self.infer_tool_arguments_from_context = infer_tool_arguments_from_context
        self.normalize_tool_arguments_runtime = normalize_tool_arguments_runtime
        self.path_allowed_fn = path_allowed_fn

    @staticmethod
    def _resolve_schema_type(manager: Optional[Any], schema: Dict[str, Any]) -> str:
        if manager and hasattr(manager, "_resolve_schema_type"):
            return str(manager._resolve_schema_type(schema) or "").strip().lower()
        raw_type = schema.get("type")
        if isinstance(raw_type, str):
            return raw_type.strip().lower()
        return ""

    @staticmethod
    def _tool_catalog(manager: Optional[Any]) -> List[Dict[str, Any]]:
        if manager and hasattr(manager, "get_all_tools"):
            try:
                return list(manager.get_all_tools() or [])
            except Exception:
                return []
        return []

    def find_tool(
        self,
        *,
        manager: Optional[Any],
        tool_name: str,
        server_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        for tool in self._tool_catalog(manager):
            if str(tool.get("name", "")).strip() != str(tool_name or "").strip():
                continue
            if server_name and str(tool.get("server", "")).strip() != str(server_name or "").strip():
                continue
            return tool
        return None

    def build_capability_snapshot(
        self,
        *,
        manager: Optional[Any],
        workspace_root: str = "",
    ) -> Dict[str, Any]:
        tools = self._tool_catalog(manager)
        profile_items = [
            infer_tool_harness_profile(
                tool,
                resolve_schema_type=(
                    (lambda schema, _manager=manager: self._resolve_schema_type(_manager, schema))
                    if manager else None
                ),
            )
            for tool in tools
        ]
        return {
            "workspace_root": str(workspace_root or ""),
            "timestamp": datetime.now().isoformat(),
            "server_count": len({
                str(tool.get("server", "")).strip()
                for tool in tools
                if str(tool.get("server", "")).strip()
            }),
            "tool_count": len(tools),
            "auto_candidate_tools": len([
                item for item in profile_items
                if str(item.get("automation_class", "")).startswith("auto_")
            ]),
            "tools": [
                {
                    "tool_key": item.get("tool_key", ""),
                    "risk_level": item.get("risk_level", "unknown"),
                    "automation_class": item.get("automation_class", "manual_only"),
                    "capabilities": summarize_tool_harness_capabilities(item),
                }
                for item in profile_items
            ],
        }

    def prepare_tool_call(
        self,
        *,
        manager: Optional[Any],
        tool_name: str,
        server_name: str,
        arguments: Optional[Dict[str, Any]],
        content: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
        workspace_root: str = "",
        request_id: Optional[str] = None,
        source: str = "chat",
    ) -> Dict[str, Any]:
        tool = self.find_tool(manager=manager, tool_name=tool_name, server_name=server_name)
        capability_snapshot = self.build_capability_snapshot(manager=manager, workspace_root=workspace_root)
        if not tool:
            return {
                "ok": False,
                "action": {
                    "action_id": f"mcp-action-{uuid.uuid4().hex[:12]}",
                    "request_id": str(request_id or ""),
                    "type": "mcp_tool",
                    "source": source,
                    "target": {"server": server_name, "tool": tool_name},
                    "workspace_root": str(workspace_root or ""),
                },
                "error": f"Tool '{tool_name}' is not present in the effective MCP runtime.",
                "capability_snapshot": capability_snapshot,
            }

        resolve_schema_type = (
            (lambda schema: self._resolve_schema_type(manager, schema))
            if manager else None
        )
        contract = build_mcp_tool_contract(tool, resolve_schema_type=resolve_schema_type)
        compiler = compile_mcp_tool_arguments(
            tool=tool,
            tool_name=tool_name,
            server_name=server_name,
            arguments=arguments,
            content=content,
            attachments=attachments,
            workspace_root=workspace_root,
            active_mcp_manager=manager,
            infer_tool_arguments_from_context=self.infer_tool_arguments_from_context,
            normalize_tool_arguments_runtime=self.normalize_tool_arguments_runtime,
            resolve_schema_type=resolve_schema_type,
        )
        precheck = precheck_mcp_tool_call(
            contract=contract,
            compiled_arguments=compiler.get("arguments", {}),
            missing_required=list(compiler.get("missing_required", [])),
            path_allowed_fn=self.path_allowed_fn,
            workspace_root=workspace_root,
        )
        action = {
            "action_id": f"mcp-action-{uuid.uuid4().hex[:12]}",
            "request_id": str(request_id or ""),
            "type": "mcp_tool",
            "plane": "mcp",
            "source": source,
            "target": {
                "server": str(server_name or tool.get("server", "")),
                "tool": str(tool_name or ""),
            },
            "workspace_root": str(workspace_root or ""),
            "attachment_count": len(attachments or []),
            "created_at": datetime.now().isoformat(),
        }
        return {
            "ok": True,
            "tool": tool,
            "contract": contract,
            "compiler": compiler,
            "precheck": precheck,
            "action": action,
            "capability_snapshot": capability_snapshot,
        }

    def finalize_tool_call(
        self,
        *,
        contract: Dict[str, Any],
        result: Any,
    ) -> Dict[str, Any]:
        return postcheck_mcp_tool_result(contract=contract, result=result)
