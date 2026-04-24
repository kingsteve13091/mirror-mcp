#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Workspace-scoped MCP manager pool for MCP Mirror."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from enhanced_mcp_manager import EnhancedMCPManager
from mcp_config_store import read_mcp_config

logger = logging.getLogger(__name__)

WORKSPACE_MCP_CONFIG_RELATIVE = Path(".mcp-mirror") / "mcp.json"
WORKSPACE_MANAGER_TTL_SECONDS = 15 * 60
WORKSPACE_MANAGER_MAX_SIZE = 8


class WorkspaceMCPConfigError(ValueError):
    """Raised when a workspace MCP config cannot be safely loaded."""


def safe_workspace_root(path_text: str) -> Optional[Path]:
    if not isinstance(path_text, str) or not path_text.strip():
        return None
    try:
        root = Path(path_text).expanduser().resolve()
    except Exception:
        return None
    if not root.exists() or not root.is_dir():
        return None
    return root


def _read_workspace_mcp_config(workspace_root: Path) -> Dict[str, Any]:
    config_path = workspace_root / WORKSPACE_MCP_CONFIG_RELATIVE
    if not config_path.exists():
        return {}
    if not config_path.is_file():
        raise WorkspaceMCPConfigError(f"Workspace MCP config is not a file: {config_path}")
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkspaceMCPConfigError(f"Failed to read workspace MCP config {config_path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise WorkspaceMCPConfigError("workspace mcp.json root must be an object")
    servers = loaded.get("mcpServers", loaded)
    if not isinstance(servers, dict):
        raise WorkspaceMCPConfigError("workspace mcp.json must contain an mcpServers object")
    return {"mcpServers": deepcopy(servers)}


def _extract_filesystem_path_args(args: list[Any]) -> list[str]:
    clean_args = [str(item) for item in args]
    try:
        package_index = clean_args.index("@modelcontextprotocol/server-filesystem")
        return clean_args[package_index + 1 :]
    except ValueError:
        return clean_args


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_path in paths:
        value = str(raw_path or "").strip()
        if not value or value.startswith("-") or value.startswith("@modelcontextprotocol/"):
            continue
        try:
            normalized = str(Path(value).expanduser().resolve()).lower()
        except Exception:
            normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _ensure_workspace_filesystem_root(config: Dict[str, Any], workspace_root: Path) -> None:
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise WorkspaceMCPConfigError("mcpServers must be an object")

    filesystem_config = servers.get("filesystem")
    if not isinstance(filesystem_config, dict):
        filesystem_config = {
            "disabled": False,
            "description": "Official MCP filesystem server",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "timeout": 60,
        }
        servers["filesystem"] = filesystem_config

    args = filesystem_config.get("args")
    if not isinstance(args, list):
        args = ["-y", "@modelcontextprotocol/server-filesystem"]
    args_text = [str(item) for item in args]
    if "@modelcontextprotocol/server-filesystem" not in args_text:
        args_text = ["-y", "@modelcontextprotocol/server-filesystem", *args_text]

    try:
        package_index = args_text.index("@modelcontextprotocol/server-filesystem")
    except ValueError:
        package_index = len(args_text) - 1

    prefix = args_text[: package_index + 1]
    path_args = _extract_filesystem_path_args(args_text)
    merged_paths = _dedupe_paths([*path_args, str(workspace_root)])
    filesystem_config["args"] = [*prefix, *merged_paths]
    filesystem_config.setdefault("disabled", False)
    filesystem_config.setdefault("description", "Official MCP filesystem server")
    filesystem_config.setdefault("timeout", 60)


def build_workspace_mcp_config(workspace_root: str = "") -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Return merged global + workspace MCP config and metadata."""
    global_config = read_mcp_config()
    if not isinstance(global_config.get("mcpServers"), dict):
        global_config["mcpServers"] = {}
    merged = deepcopy(global_config)
    metadata: Dict[str, Any] = {
        "workspace_enabled": False,
        "workspace_root": "",
        "workspace_config_path": "",
        "workspace_servers": [],
        "sources": ["mcp_config.json"],
    }

    root = safe_workspace_root(workspace_root)
    if root is None:
        return merged, metadata

    metadata["workspace_enabled"] = True
    metadata["workspace_root"] = str(root)
    metadata["workspace_config_path"] = str(root / WORKSPACE_MCP_CONFIG_RELATIVE)
    _ensure_workspace_filesystem_root(merged, root)

    workspace_config = _read_workspace_mcp_config(root)
    workspace_servers = workspace_config.get("mcpServers", {})
    if isinstance(workspace_servers, dict) and workspace_servers:
        merged_servers = merged.setdefault("mcpServers", {})
        merged_servers.update(deepcopy(workspace_servers))
        metadata["workspace_servers"] = sorted(str(name) for name in workspace_servers.keys())
        metadata["sources"].append(str(root / WORKSPACE_MCP_CONFIG_RELATIVE))

    return merged, metadata


def _config_cache_key(config: Dict[str, Any], workspace_root: str) -> str:
    payload = {
        "workspace_root": workspace_root,
        "config": config,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _server_config_changed(
    merged_config: Dict[str, Any],
    base_config: Dict[str, Any],
) -> set[str]:
    merged_servers = merged_config.get("mcpServers", {}) if isinstance(merged_config, dict) else {}
    base_servers = base_config if isinstance(base_config, dict) else {}
    if not isinstance(merged_servers, dict):
        return set()
    changed: set[str] = set()
    for server_name, server_config in merged_servers.items():
        if not isinstance(server_name, str) or not server_name.strip():
            continue
        if base_servers.get(server_name) != server_config:
            changed.add(server_name)
    return changed


class WorkspaceMCPPool:
    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}

    async def get_manager(
        self,
        workspace_root: str = "",
        base_manager: Optional[EnhancedMCPManager] = None,
    ) -> tuple[Optional[EnhancedMCPManager], Dict[str, Any]]:
        config, metadata = build_workspace_mcp_config(workspace_root)
        if not metadata.get("workspace_enabled"):
            return None, metadata

        cache_key = _config_cache_key(config, str(metadata.get("workspace_root", "")))
        cached = self._cache.get(cache_key)
        now = time.time()
        if cached:
            cached["last_used"] = now
            return cached["manager"], metadata

        await self._evict_if_needed()
        manager, owned_manager = await self._build_workspace_overlay_manager(
            config=config,
            metadata=metadata,
            base_manager=base_manager,
        )
        self._cache[cache_key] = {
            "manager": manager,
            "owned_manager": owned_manager,
            "last_used": now,
            "metadata": metadata,
        }
        logger.info(
            "workspace MCP manager initialized root=%s servers=%d tools=%d",
            metadata.get("workspace_root", ""),
            len(manager.servers),
            len(manager.tools),
        )
        return manager, metadata

    async def _build_workspace_overlay_manager(
        self,
        *,
        config: Dict[str, Any],
        metadata: Dict[str, Any],
        base_manager: Optional[EnhancedMCPManager],
    ) -> tuple[EnhancedMCPManager, Optional[EnhancedMCPManager]]:
        merged_servers = config.get("mcpServers", {}) if isinstance(config, dict) else {}
        if not isinstance(merged_servers, dict):
            merged_servers = {}

        if not base_manager or not getattr(base_manager, "initialized", False):
            manager = EnhancedMCPManager()
            manager.config = deepcopy(merged_servers)
            await manager._process_mcp_config(manager.config)
            await manager._connect_mcp_servers()
            await manager._refresh_mcp_capabilities()
            manager.initialized = True
            return manager, manager

        base_config = getattr(base_manager, "config", {})
        changed_server_names = _server_config_changed(config, base_config)
        if not changed_server_names:
            return base_manager, None

        overlay_manager = EnhancedMCPManager()
        overlay_manager.initialized = True
        overlay_manager.config = deepcopy(merged_servers)
        overlay_manager.clients = {
            name: client
            for name, client in getattr(base_manager, "clients", {}).items()
            if name not in changed_server_names
        }
        overlay_manager.tools = [
            deepcopy(tool)
            for tool in getattr(base_manager, "tools", [])
            if str(tool.get("server", "")).strip() not in changed_server_names
        ]
        overlay_manager.resources = [
            deepcopy(resource)
            for resource in getattr(base_manager, "resources", [])
            if str(resource.get("server", "")).strip() not in changed_server_names
        ]
        overlay_manager.prompts = [
            deepcopy(prompt)
            for prompt in getattr(base_manager, "prompts", [])
            if str(prompt.get("server", "")).strip() not in changed_server_names
        ]
        overlay_manager.servers = [
            deepcopy(server)
            for server in getattr(base_manager, "servers", [])
            if str(server.get("name", "")).strip() not in changed_server_names
        ]

        owned_manager = EnhancedMCPManager()
        owned_manager.config = {
            server_name: deepcopy(merged_servers.get(server_name, {}))
            for server_name in changed_server_names
            if server_name in merged_servers
        }
        if owned_manager.config:
            await owned_manager._process_mcp_config(owned_manager.config)
            await owned_manager._connect_mcp_servers()
            await owned_manager._refresh_mcp_capabilities()
            owned_manager.initialized = True
            overlay_manager.clients.update(owned_manager.clients)
            overlay_manager.tools.extend(deepcopy(owned_manager.tools))
            overlay_manager.resources.extend(deepcopy(owned_manager.resources))
            overlay_manager.prompts.extend(deepcopy(owned_manager.prompts))
            overlay_manager.servers.extend(deepcopy(owned_manager.servers))

        logger.info(
            "workspace MCP overlay reuse root=%s changed_servers=%s reused_servers=%d",
            metadata.get("workspace_root", ""),
            sorted(changed_server_names),
            len(getattr(base_manager, "servers", [])) - len(changed_server_names),
        )
        return overlay_manager, owned_manager if owned_manager.config else None

    async def _evict_if_needed(self) -> None:
        now = time.time()
        expired_keys = [
            key
            for key, item in self._cache.items()
            if now - float(item.get("last_used", 0.0)) > WORKSPACE_MANAGER_TTL_SECONDS
        ]
        for key in expired_keys:
            await self._remove(key)
        while len(self._cache) >= WORKSPACE_MANAGER_MAX_SIZE:
            oldest_key = min(self._cache, key=lambda key: float(self._cache[key].get("last_used", 0.0)))
            await self._remove(oldest_key)

    async def _remove(self, key: str) -> None:
        item = self._cache.pop(key, None)
        manager = item.get("owned_manager") if isinstance(item, dict) else None
        if manager is None and isinstance(item, dict):
            manager = item.get("manager")
        if manager and hasattr(manager, "shutdown"):
            try:
                await manager.shutdown()
            except Exception as exc:
                logger.warning("failed to shutdown workspace MCP manager: %s", exc)

    async def shutdown(self) -> None:
        keys = list(self._cache.keys())
        for key in keys:
            await self._remove(key)


workspace_mcp_pool = WorkspaceMCPPool()
