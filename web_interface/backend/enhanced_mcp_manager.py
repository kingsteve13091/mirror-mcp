#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced MCP manager for MCP Mirror.

Design goals:
- Treat configured MCP servers (including cdar_mcp) as external MCP services.
- Never import/exec server scripts in-process.
- A single MCP server failure must not block backend startup.
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tool_execution_memory import FailureCause, classify_failure_cause
from path_portability import decode_portable_paths

try:
    from fastmcp import Client
    FASTMCP_AVAILABLE = True
except ImportError as exc:
    Client = None  # type: ignore[assignment]
    FASTMCP_AVAILABLE = False
    _import_error = exc

logger = logging.getLogger(__name__)
INVISIBLE_TEXT_CHARS = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)
if FASTMCP_AVAILABLE:
    logger.info("FastMCP available")
else:
    logger.error("FastMCP unavailable: %s", _import_error)


class EnhancedMCPManager:
    """MCP manager backed by FastMCP client(s)."""

    _OMIT_ARGUMENT = object()

    @staticmethod
    def _sanitize_text_payload(value: Any) -> str:
        return str(value).translate(INVISIBLE_TEXT_CHARS)

    def __init__(self) -> None:
        self.clients: Dict[str, Any] = {}
        self.tools: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []
        self.prompts: List[Dict[str, Any]] = []
        self.servers: List[Dict[str, Any]] = []
        self.initialized = False
        self.config: Dict[str, Any] = {}

    def _build_wrapped_single_server_config(self, server_name: str) -> Dict[str, Any]:
        raw_cfg = self.config.get(server_name)
        if not isinstance(raw_cfg, dict):
            server_info = next((server for server in self.servers if server.get("name") == server_name), None)
            raw_cfg = server_info.get("config", {}) if isinstance(server_info, dict) else {}
        if not isinstance(raw_cfg, dict):
            raise ValueError(f"server config is not available for {server_name}")
        return {"mcpServers": {server_name: raw_cfg}}

    def _create_ephemeral_client(self, server_name: str) -> Any:
        if not FASTMCP_AVAILABLE:
            raise RuntimeError("FastMCP is not installed")
        wrapped_config = self._build_wrapped_single_server_config(server_name)
        return Client(wrapped_config)

    async def initialize(self) -> bool:
        """Initialize manager. Returns True even if some servers fail."""
        if not FASTMCP_AVAILABLE:
            logger.error("Cannot initialize MCP manager: FastMCP is not installed")
            return False

        try:
            await self._load_mcp_config()
            await self._connect_mcp_servers()
            await self._refresh_mcp_capabilities()
            self.initialized = True
            logger.info(
                "MCP manager initialized: servers=%d, connected=%d, tools=%d",
                len(self.servers),
                len([s for s in self.servers if s.get("status") == "connected"]),
                len(self.tools),
            )
            return True
        except Exception as exc:
            logger.error("MCP manager initialization failed: %s", exc)
            logger.error(traceback.format_exc())
            return False

    async def _load_mcp_config(self) -> None:
        """Load MCP config from known locations."""
        config_paths = [
            Path(__file__).parent.parent.parent / "mcp_config.json",
            Path(__file__).parent.parent.parent / "claude_desktop_config.json",
            Path.home() / ".config" / "claude" / "claude_desktop_config.json",
        ]

        for config_path in config_paths:
            if not config_path.exists():
                continue

            try:
                logger.info("Found MCP config: %s", config_path)
                with open(config_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict) and "mcpServers" in loaded:
                    mcp_servers = loaded.get("mcpServers", {})
                    if isinstance(mcp_servers, dict):
                        self.config = mcp_servers
                        await self._process_mcp_config(self.config)
                        return
            except Exception as exc:
                logger.error("Failed reading MCP config %s: %s", config_path, exc)

        logger.warning("No valid MCP config found. Continuing without MCP servers.")
        self.config = {}
        self.servers = []

    async def _process_mcp_config(self, mcp_servers: Dict[str, Any]) -> None:
        """Transform config into runtime server metadata."""
        self.servers = []
        for server_name, config in mcp_servers.items():
            if not isinstance(config, dict):
                logger.warning("Invalid server config for %s: expected dict", server_name)
                continue

            if config.get("url"):
                connection_type = "external_transport"
            elif config.get("command"):
                connection_type = "local_stdio"
            else:
                connection_type = "unknown"

            self.servers.append(
                {
                    "name": server_name,
                    "status": "disconnected",
                    "enabled": not bool(config.get("disabled", False)),
                    "description": config.get("description", f"MCP server {server_name}"),
                    "tools": [],
                    "tools_count": 0,
                    "resources_count": 0,
                    "prompts_count": 0,
                    "client_connected": False,
                    "connection_type": connection_type,
                    "last_ping": datetime.now().isoformat(),
                    "config": config,
                }
            )

    async def _connect_mcp_servers(self) -> None:
        """Create client objects from config; do not execute server code in-process."""
        self.clients = {}

        for server_info in self.servers:
            if not server_info.get("enabled", True):
                server_info["status"] = "disabled"
                continue

            try:
                await self._connect_single_server(server_info)
            except Exception as exc:
                server_info["status"] = "error"
                server_info["client_connected"] = False
                server_info["error_message"] = str(exc)
                logger.error("Server setup failed %s: %s", server_info.get("name"), exc)

    async def _connect_single_server(self, server_info: Dict[str, Any]) -> None:
        """Build a FastMCP client from a single-server MCPConfig wrapper."""
        server_name = server_info["name"]
        raw_cfg = server_info.get("config", {})
        if not isinstance(raw_cfg, dict):
            raise ValueError("server config is not a dict")

        # FastMCP expects MCPConfig-style shape: {"mcpServers": {...}}
        wrapped_config = {"mcpServers": {server_name: raw_cfg}}
        client = Client(wrapped_config)

        self.clients[server_name] = client
        server_info["status"] = "configured"
        server_info["client_connected"] = False
        server_info["last_ping"] = datetime.now().isoformat()

    async def _refresh_mcp_capabilities(self) -> None:
        """Query tools/resources/prompts from each configured server."""
        self.tools = []
        self.resources = []
        self.prompts = []

        for server_name, client in self.clients.items():
            server_info = next((s for s in self.servers if s.get("name") == server_name), None)
            if not server_info:
                continue

            try:
                async with client:
                    tools_result = await client.list_tools()

                    try:
                        resources_result = await client.list_resources()
                    except Exception as exc:
                        resources_result = []
                        logger.info(
                            "Server %s does not provide resources or refused list_resources(): %r",
                            server_name,
                            exc,
                        )

                    try:
                        prompts_result = await client.list_prompts()
                    except Exception as exc:
                        prompts_result = []
                        logger.info(
                            "Server %s does not provide prompts or refused list_prompts(): %r",
                            server_name,
                            exc,
                        )

                self._merge_tools(server_name, tools_result)
                self._merge_resources(server_name, resources_result)
                self._merge_prompts(server_name, prompts_result)

                server_info["status"] = "connected"
                server_info["client_connected"] = True
                server_info["tools_count"] = len([t for t in self.tools if t.get("server") == server_name])
                server_info["resources_count"] = len([r for r in self.resources if r.get("server") == server_name])
                server_info["prompts_count"] = len([p for p in self.prompts if p.get("server") == server_name])
                server_info["tools"] = [t.get("name") for t in self.tools if t.get("server") == server_name]
                server_info["last_ping"] = datetime.now().isoformat()
            except Exception as exc:
                server_info["status"] = "error"
                server_info["client_connected"] = False
                server_info["error_message"] = repr(exc)
                logger.error("Capability refresh failed for %s: %r", server_name, exc)

        logger.info(
            "Capability refresh done: tools=%d resources=%d prompts=%d",
            len(self.tools),
            len(self.resources),
            len(self.prompts),
        )

    def _merge_tools(self, server_name: str, tools_result: Any) -> None:
        if not isinstance(tools_result, list):
            return

        for tool in tools_result:
            schema = {}
            input_schema = getattr(tool, "inputSchema", None)
            if input_schema is not None:
                if hasattr(input_schema, "model_dump"):
                    schema = input_schema.model_dump()
                elif isinstance(input_schema, dict):
                    schema = input_schema
                else:
                    try:
                        schema = dict(input_schema)
                    except Exception:
                        schema = {}

            self.tools.append(
                {
                    "server": server_name,
                    "name": getattr(tool, "name", ""),
                    "display_name": getattr(tool, "display_name", getattr(tool, "name", "")),
                    "description": getattr(tool, "description", ""),
                    "enabled": True,
                    "server_status": "connected",
                    "client_connected": True,
                    "input_schema": schema,
                }
            )

    def _merge_resources(self, server_name: str, resources_result: Any) -> None:
        if not isinstance(resources_result, list):
            return

        for resource in resources_result:
            self.resources.append(
                {
                    "server": server_name,
                    "uri": getattr(resource, "uri", ""),
                    "name": getattr(resource, "name", ""),
                    "description": getattr(resource, "description", ""),
                    "mime_type": getattr(resource, "mimeType", ""),
                    "enabled": True,
                }
            )

    def _merge_prompts(self, server_name: str, prompts_result: Any) -> None:
        if not isinstance(prompts_result, list):
            return

        for prompt in prompts_result:
            self.prompts.append(
                {
                    "server": server_name,
                    "name": getattr(prompt, "name", ""),
                    "description": getattr(prompt, "description", ""),
                    "arguments": getattr(prompt, "arguments", []),
                    "enabled": True,
                }
            )

    def get_all_tools(self) -> List[Dict[str, Any]]:
        return self.tools

    def get_all_resources(self) -> List[Dict[str, Any]]:
        return self.resources

    def get_all_prompts(self) -> List[Dict[str, Any]]:
        return self.prompts

    def get_server_status(self) -> Dict[str, Any]:
        return {
            "servers": self.servers,
            "total_servers": len(self.servers),
            "connected_servers": len([s for s in self.servers if s.get("status") == "connected"]),
            "total_tools": len(self.tools),
            "total_resources": len(self.resources),
            "total_prompts": len(self.prompts),
            "last_update": datetime.now().isoformat(),
            "fastmcp_available": FASTMCP_AVAILABLE,
        }

    @classmethod
    def _resolve_schema_type(cls, schema: Dict[str, Any]) -> str:
        if not isinstance(schema, dict):
            return "string"

        raw_type = schema.get("type")
        if isinstance(raw_type, list):
            for item in raw_type:
                if item != "null":
                    return str(item)
            return "string"
        if isinstance(raw_type, str) and raw_type.strip():
            return raw_type.strip()

        for union_key in ("anyOf", "oneOf", "allOf"):
            union_options = schema.get(union_key)
            if not isinstance(union_options, list):
                continue
            for option in union_options:
                if not isinstance(option, dict):
                    continue
                resolved = cls._resolve_schema_type(option)
                if resolved and resolved != "null":
                    return resolved

        return "string"

    @classmethod
    def _coerce_argument_value(cls, schema: Dict[str, Any], value: Any, required: bool) -> Any:
        schema_type = cls._resolve_schema_type(schema)

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return value if required else cls._OMIT_ARGUMENT

            if schema_type == "boolean":
                lowered = stripped.lower()
                if lowered in {"true", "1", "yes", "on"}:
                    return True
                if lowered in {"false", "0", "no", "off"}:
                    return False
                return value if required else cls._OMIT_ARGUMENT

            if schema_type == "integer":
                try:
                    return int(stripped)
                except ValueError:
                    return value if required else cls._OMIT_ARGUMENT

            if schema_type == "number":
                try:
                    numeric = float(stripped)
                    if numeric.is_integer():
                        return int(numeric)
                    return numeric
                except ValueError:
                    return value if required else cls._OMIT_ARGUMENT

            if schema_type in {"object", "array"}:
                try:
                    value = json.loads(stripped)
                except (json.JSONDecodeError, TypeError):
                    return value if required else cls._OMIT_ARGUMENT

        if schema_type == "integer":
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, int):
                return value
            return value if required else cls._OMIT_ARGUMENT

        if schema_type == "number":
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return value
            return value if required else cls._OMIT_ARGUMENT

        if schema_type == "string":
            if value is None:
                return value if required else cls._OMIT_ARGUMENT
            if isinstance(value, (dict, list)):
                return value if required else cls._OMIT_ARGUMENT
            if not isinstance(value, str):
                return str(value)
            return value

        if schema_type == "boolean":
            if isinstance(value, (int, float)) and value in {0, 1}:
                return bool(value)
            if isinstance(value, bool):
                return value
            return value if required else cls._OMIT_ARGUMENT

        if schema_type == "array":
            if not isinstance(value, list):
                return value if required else cls._OMIT_ARGUMENT
            item_schema = schema.get("items")
            if not isinstance(item_schema, dict):
                return value
            normalized_items: List[Any] = []
            for item in value:
                coerced = cls._coerce_argument_value(item_schema, item, required=True)
                if coerced is cls._OMIT_ARGUMENT:
                    continue
                normalized_items.append(coerced)
            return normalized_items

        if schema_type == "object":
            if not isinstance(value, dict):
                return value if required else cls._OMIT_ARGUMENT

            properties = schema.get("properties")
            additional_properties = schema.get("additionalProperties")
            required_fields = schema.get("required") if isinstance(schema.get("required"), list) else []
            required_field_names = {str(field_name) for field_name in required_fields}

            normalized_object: Dict[str, Any] = {}
            for key, item_value in value.items():
                property_schema = properties.get(key) if isinstance(properties, dict) else None
                if not isinstance(property_schema, dict):
                    if isinstance(additional_properties, dict):
                        property_schema = additional_properties
                    else:
                        normalized_object[key] = item_value
                        continue

                coerced = cls._coerce_argument_value(
                    property_schema,
                    item_value,
                    required=key in required_field_names,
                )
                if coerced is cls._OMIT_ARGUMENT:
                    continue
                normalized_object[key] = coerced

            return normalized_object

        return value

    def normalize_tool_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        server_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidates = [t for t in self.tools if t.get("name") == tool_name]
        if server_name:
            candidates = [t for t in candidates if t.get("server") == server_name]

        tool = candidates[0] if candidates else None
        if not tool:
            return dict(arguments or {})

        schema = tool.get("input_schema") or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        required_fields = schema.get("required") if isinstance(schema, dict) and isinstance(schema.get("required"), list) else []
        if not isinstance(properties, dict):
            return dict(arguments or {})

        required_field_names = {
            str(field_name)
            for field_name in required_fields
        }
        decoded_arguments = decode_portable_paths(dict(arguments or {}))
        normalized_arguments: Dict[str, Any] = {}
        for key, value in decoded_arguments.items():
            property_schema = properties.get(key)
            if not isinstance(property_schema, dict):
                additional_properties = schema.get("additionalProperties") if isinstance(schema, dict) else None
                if isinstance(additional_properties, dict):
                    property_schema = additional_properties
                else:
                    normalized_arguments[key] = value
                    continue

            coerced = self._coerce_argument_value(
                property_schema,
                value,
                required=key in required_field_names,
            )
            if coerced is self._OMIT_ARGUMENT:
                continue
            normalized_arguments[key] = coerced

        return normalized_arguments

    @staticmethod
    def _check_business_success(result_content: str, raw_result: Any) -> bool:
        """
        Protocol-level success does not always mean business success.
        Return False for known error-shaped payloads.
        """
        if hasattr(raw_result, "is_error") and raw_result.is_error:
            return False

        if hasattr(raw_result, "content") and raw_result.content:
            items = raw_result.content if isinstance(raw_result.content, list) else [raw_result.content]
            for item in items:
                if hasattr(item, "is_error") and item.is_error:
                    return False
        elif isinstance(raw_result, list):
            for item in raw_result:
                if hasattr(item, "is_error") and item.is_error:
                    return False

        try:
            parsed = json.loads(result_content)
            if isinstance(parsed, dict):
                if parsed.get("success") is False:
                    return False
                if parsed.get("error"):
                    return False
                return True
            if isinstance(parsed, list):
                return True
        except (json.JSONDecodeError, TypeError):
            # Plain-text success responses are common in official MCP servers.
            # Only treat them as failures when they look like actual runtime errors,
            # not when normal prose happens to contain words like "failed".
            lowered = (result_content or "").lower()
            explicit_error_markers = (
                "error:",
                "exception:",
                "traceback",
                "access denied",
                "permission denied",
                "enoent",
                "no such file",
                "not found",
                "path escapes root",
                "invalid input",
                "validation error",
                "input validation error",
                "tool call failed",
                "mcp error",
            )
            if any(marker in lowered for marker in explicit_error_markers):
                cause = classify_failure_cause("UnstructuredToolResult", result_content or "")
                if cause != FailureCause.UNKNOWN:
                    return False

        return True

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], server_name: Optional[str] = None) -> Dict[str, Any]:
        """Call a tool from connected MCP servers."""
        try:
            candidates = [t for t in self.tools if t.get("name") == tool_name]
            if server_name:
                candidates = [t for t in candidates if t.get("server") == server_name]

            tool = candidates[0] if candidates else None
            if not tool:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found",
                    "available_tools": [t.get("name") for t in self.tools],
                }

            if not tool.get("enabled") or tool.get("server_status") != "connected":
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' is not available",
                    "tool_status": tool.get("server_status"),
                }

            schema = tool.get("input_schema") or {}
            original_arguments = dict(arguments or {})
            arguments = self.normalize_tool_arguments(tool_name, arguments, server_name)
            if tool_name in {"read_file", "read_text_file", "sequentialthinking"}:
                logger.info(
                    "tool call normalization %s server=%s raw=%s raw_types=%s normalized=%s normalized_types=%s",
                    tool_name,
                    server_name or tool.get("server") or "",
                    original_arguments,
                    {key: type(value).__name__ for key, value in original_arguments.items()},
                    arguments,
                    {key: type(value).__name__ for key, value in arguments.items()},
                )
            required_fields = schema.get("required", []) if isinstance(schema, dict) else []
            missing_required = []
            for field_name in required_fields if isinstance(required_fields, list) else []:
                value = arguments.get(field_name)
                if value is None:
                    missing_required.append(str(field_name))
                elif isinstance(value, str) and not value.strip():
                    missing_required.append(str(field_name))

            if missing_required:
                return {
                    "success": False,
                    "error_type": "InputValidationError",
                    "error": (
                        f"Missing required arguments for tool '{tool_name}': "
                        + ", ".join(missing_required)
                    ),
                    "missing_required": missing_required,
                    "tool_name": tool_name,
                    "server": tool.get("server"),
                    "input_schema": schema,
                }

            srv = tool.get("server")
            if not srv:
                return {
                    "success": False,
                    "error": f"Server is not available for tool '{tool_name}'",
                }

            async with self._create_ephemeral_client(srv) as client:
                result = await client.call_tool(tool_name, arguments)

            if hasattr(result, "content") and result.content:
                first = result.content[0] if isinstance(result.content, list) else result.content
                result_content = self._sanitize_text_payload(getattr(first, "text", str(first)))
            elif isinstance(result, list) and result:
                first = result[0]
                result_content = self._sanitize_text_payload(getattr(first, "text", str(first)))
            else:
                result_content = self._sanitize_text_payload(result)

            business_success = self._check_business_success(result_content, result)
            business_error = ""
            if not business_success:
                try:
                    parsed = json.loads(result_content)
                    if isinstance(parsed, dict):
                        business_error = str(parsed.get("error", parsed.get("message", "")))
                except (json.JSONDecodeError, TypeError):
                    business_error = result_content

            return {
                "success": business_success,
                "protocol_success": True,
                "tool_name": tool_name,
                "server": srv,
                "result": result_content,
                "error": business_error,
                "raw_result": self._sanitize_text_payload(result),
                "timestamp": datetime.now().isoformat(),
                "_real_mcp_call": True,
            }

        except Exception as exc:
            logger.error("Tool call failed %s: %s", tool_name, exc)
            return {
                "success": False,
                "error": str(exc),
                "tool_name": tool_name,
                "server": server_name or "",
                "timestamp": datetime.now().isoformat(),
                "_real_mcp_call": True,
            }

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read MCP resource by URI."""
        try:
            resource = next((r for r in self.resources if r.get("uri") == uri), None)
            if not resource:
                return {
                    "success": False,
                    "error": f"Resource '{uri}' not found",
                    "available_resources": [r.get("uri") for r in self.resources],
                }

            srv = resource.get("server")
            if not srv:
                return {
                    "success": False,
                    "error": f"Server is not available for resource '{uri}'",
                }

            async with self._create_ephemeral_client(srv) as client:
                result = await client.read_resource(uri)

            if hasattr(result, "contents") and result.contents:
                content = result.contents[0]
                if hasattr(content, "text"):
                    content_data = self._sanitize_text_payload(content.text)
                    content_type = "text"
                else:
                    content_data = self._sanitize_text_payload(content)
                    content_type = "unknown"
            else:
                content_data = self._sanitize_text_payload(result)
                content_type = "raw"

            return {
                "success": True,
                "uri": uri,
                "server": srv,
                "content": content_data,
                "content_type": content_type,
                "raw_result": self._sanitize_text_payload(result),
                "timestamp": datetime.now().isoformat(),
                "_real_mcp_call": True,
            }

        except Exception as exc:
            logger.error("Read resource failed %s: %s", uri, exc)
            return {
                "success": False,
                "error": str(exc),
                "uri": uri,
                "timestamp": datetime.now().isoformat(),
            }

    async def get_prompt(self, prompt_name: str, arguments: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Get MCP prompt by name."""
        try:
            prompt = next((p for p in self.prompts if p.get("name") == prompt_name), None)
            if not prompt:
                return {
                    "success": False,
                    "error": f"Prompt '{prompt_name}' not found",
                    "available_prompts": [p.get("name") for p in self.prompts],
                }

            srv = prompt.get("server")
            if not srv:
                return {
                    "success": False,
                    "error": f"Server is not available for prompt '{prompt_name}'",
                }

            async with self._create_ephemeral_client(srv) as client:
                result = await client.get_prompt(prompt_name, arguments or {})

            if hasattr(result, "messages") and result.messages:
                messages = []
                for msg in result.messages:
                    if hasattr(msg, "content") and hasattr(msg.content, "text"):
                        messages.append(self._sanitize_text_payload(msg.content.text))
                    elif hasattr(msg, "content"):
                        messages.append(self._sanitize_text_payload(msg.content))
                    else:
                        messages.append(self._sanitize_text_payload(msg))
                prompt_content = "\n".join(messages)
            else:
                prompt_content = self._sanitize_text_payload(result)

            return {
                "success": True,
                "name": prompt_name,
                "server": srv,
                "prompt": prompt_content,
                "arguments": arguments or {},
                "raw_result": self._sanitize_text_payload(result),
                "timestamp": datetime.now().isoformat(),
                "_real_mcp_call": True,
            }

        except Exception as exc:
            logger.error("Get prompt failed %s: %s", prompt_name, exc)
            return {
                "success": False,
                "error": str(exc),
                "name": prompt_name,
                "timestamp": datetime.now().isoformat(),
            }

    async def shutdown(self) -> None:
        """Shutdown all MCP clients."""
        for server_name, client in self.clients.items():
            try:
                if hasattr(client, "close"):
                    await client.close()
            except Exception as exc:
                logger.error("Failed closing client %s: %s", server_name, exc)

        for server in self.servers:
            server["status"] = "disconnected"
            server["client_connected"] = False

        self.clients.clear()
        self.initialized = False


enhanced_mcp_manager = EnhancedMCPManager()
