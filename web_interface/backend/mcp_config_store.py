#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Persistent MCP server configuration store.

This module is intentionally small and strict:
- `mcp_config.json` remains the single source of truth.
- Official reference servers are protected from UI edits.
- Writes are atomic so a failed save cannot corrupt the runtime config.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server_contract import OFFICIAL_SERVER_SPECS, classify_server_config


CONFIG_PATH = PROJECT_ROOT / "mcp_config.json"
SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_MCP_TIMEOUT_SECONDS = 60
MIN_MCP_TIMEOUT_SECONDS = 1
MAX_MCP_TIMEOUT_SECONDS = 600
ALLOWED_REMOTE_TRANSPORTS = {"sse", "http", "streamable-http"}
ALLOWED_SERVER_MODES = {"stdio", "remote"}


class MCPConfigError(ValueError):
    """Raised when an MCP config update is invalid."""


class MCPServerConfigRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    mode: str = "stdio"
    disabled: bool = False
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    transport: Optional[str] = None
    timeout: int = DEFAULT_MCP_TIMEOUT_SECONDS


def read_mcp_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"mcpServers": {}}
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, dict):
        raise MCPConfigError("mcp_config.json root must be an object")
    servers = loaded.get("mcpServers")
    if not isinstance(servers, dict):
        loaded["mcpServers"] = {}
    return loaded


def write_mcp_config(config: Dict[str, Any]) -> None:
    if not isinstance(config.get("mcpServers"), dict):
        raise MCPConfigError("mcpServers must be an object")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(config, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(CONFIG_PATH.parent),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(serialized)
        tmp.write("\n")
        tmp_path = Path(tmp.name)

    os.replace(tmp_path, CONFIG_PATH)


def _validate_server_name(name: str) -> str:
    normalized = name.strip()
    if not SERVER_NAME_PATTERN.match(normalized):
        raise MCPConfigError("Server name must use only letters, numbers, underscore, or dash")
    return normalized


def _validate_timeout(timeout: int) -> int:
    if not isinstance(timeout, int):
        raise MCPConfigError("timeout must be an integer number of seconds")
    if timeout < MIN_MCP_TIMEOUT_SECONDS or timeout > MAX_MCP_TIMEOUT_SECONDS:
        raise MCPConfigError(
            f"timeout must be between {MIN_MCP_TIMEOUT_SECONDS} and {MAX_MCP_TIMEOUT_SECONDS} seconds"
        )
    return timeout


def _clean_env(env: Dict[str, str]) -> Dict[str, str]:
    cleaned: Dict[str, str] = {}
    for key, value in (env or {}).items():
        clean_key = str(key).strip()
        if not clean_key:
            raise MCPConfigError("env keys cannot be empty")
        cleaned[clean_key] = str(value)
    return cleaned


def _clean_args(args: List[str]) -> List[str]:
    return [str(arg) for arg in (args or [])]


def build_server_config(request: MCPServerConfigRequest) -> tuple[str, Dict[str, Any]]:
    name = _validate_server_name(request.name)
    mode = (request.mode or "").strip().lower()
    if mode not in ALLOWED_SERVER_MODES:
        raise MCPConfigError(f"mode must be one of: {', '.join(sorted(ALLOWED_SERVER_MODES))}")

    timeout = _validate_timeout(request.timeout)
    config: Dict[str, Any] = {
        "disabled": bool(request.disabled),
        "description": (request.description or "").strip() or f"Custom MCP server {name}",
        "timeout": timeout,
    }

    if mode == "remote":
        url = (request.url or "").strip()
        if not url:
            raise MCPConfigError("remote MCP server requires url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MCPConfigError("remote MCP url must be a valid http(s) URL")

        transport = (request.transport or "sse").strip().lower()
        if transport not in ALLOWED_REMOTE_TRANSPORTS:
            raise MCPConfigError(f"transport must be one of: {', '.join(sorted(ALLOWED_REMOTE_TRANSPORTS))}")

        config.update(
            {
                "url": url,
                "transport": transport,
            }
        )
        return name, config

    command = (request.command or "").strip()
    if not command:
        raise MCPConfigError("stdio MCP server requires command")

    config.update(
        {
            "command": command,
            "args": _clean_args(request.args),
        }
    )
    env = _clean_env(request.env)
    if env:
        config["env"] = env
    return name, config


def list_mcp_server_configs() -> Dict[str, Any]:
    config = read_mcp_config()
    servers = config.get("mcpServers", {})
    items = []
    for name, server_config in servers.items():
        if not isinstance(server_config, dict):
            continue
        mode = "remote" if server_config.get("url") else "stdio" if server_config.get("command") else "unknown"
        items.append(
            {
                "name": name,
                "mode": mode,
                "editable": name not in OFFICIAL_SERVER_SPECS,
                "classification": classify_server_config(name, server_config),
                "config": deepcopy(server_config),
            }
        )
    return {
        "config_path": str(CONFIG_PATH),
        "servers": items,
        "protected_servers": sorted(OFFICIAL_SERVER_SPECS.keys()),
    }


def upsert_mcp_server_config(request: MCPServerConfigRequest) -> Dict[str, Any]:
    name, server_config = build_server_config(request)
    if name in OFFICIAL_SERVER_SPECS:
        raise MCPConfigError(
            f"{name} is an official reference server and is protected from UI edits"
        )

    config = read_mcp_config()
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise MCPConfigError("mcpServers must be an object")
    servers[name] = server_config
    write_mcp_config(config)
    return {
        "name": name,
        "config": deepcopy(server_config),
        "config_path": str(CONFIG_PATH),
    }


def delete_mcp_server_config(name: str) -> Dict[str, Any]:
    normalized = _validate_server_name(name)
    if normalized in OFFICIAL_SERVER_SPECS:
        raise MCPConfigError(
            f"{normalized} is an official reference server and cannot be deleted from the UI"
        )

    config = read_mcp_config()
    servers = config.setdefault("mcpServers", {})
    if normalized not in servers:
        raise MCPConfigError(f"MCP server not found: {normalized}")
    removed = deepcopy(servers.pop(normalized))
    write_mcp_config(config)
    return {
        "name": normalized,
        "removed": removed,
        "config_path": str(CONFIG_PATH),
    }
