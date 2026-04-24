from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OfficialServerSpec:
    name: str
    command: str
    required_args: tuple[str, ...]
    required_tools: tuple[str, ...]
    forbidden_tools: tuple[str, ...]
    connection_type: str = "local_stdio"


OFFICIAL_SERVER_SPECS: dict[str, OfficialServerSpec] = {
    "filesystem": OfficialServerSpec(
        name="filesystem",
        command="npx",
        required_args=("@modelcontextprotocol/server-filesystem",),
        required_tools=(
            "read_text_file",
            "write_file",
            "search_files",
            "list_allowed_directories",
            "create_directory",
        ),
        forbidden_tools=("fs_root", "write_text_file", "search_text"),
    ),
    "fetch": OfficialServerSpec(
        name="fetch",
        command="uvx",
        required_args=("mcp-server-fetch",),
        required_tools=("fetch",),
        forbidden_tools=("fetch_url", "head_url"),
    ),
    "memory": OfficialServerSpec(
        name="memory",
        command="npx",
        required_args=("@modelcontextprotocol/server-memory",),
        required_tools=(
            "create_entities",
            "add_observations",
            "search_nodes",
            "open_nodes",
            "read_graph",
        ),
        forbidden_tools=("memory_add", "memory_search", "memory_info", "memory_clear"),
    ),
    "sequential_thinking": OfficialServerSpec(
        name="sequential_thinking",
        command="npx",
        required_args=("@modelcontextprotocol/server-sequential-thinking",),
        required_tools=("sequentialthinking",),
        forbidden_tools=("think_stepwise", "evaluate_plan"),
    ),
}


def _normalize_config_servers(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(config, dict):
        return {}
    servers = config.get("mcpServers", config)
    if not isinstance(servers, dict):
        return {}
    return {str(name): value for name, value in servers.items() if isinstance(value, dict)}


def _normalize_runtime_server_map(runtime_servers_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(runtime_servers_payload, dict):
        return {}
    raw_servers = runtime_servers_payload.get("servers", runtime_servers_payload)
    if isinstance(raw_servers, dict):
        candidates = raw_servers.get("servers", [])
    else:
        candidates = raw_servers
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(candidates, list):
        return out
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        out[name] = item
    return out


def _normalize_tools_by_server(runtime_tools_payload: dict[str, Any]) -> dict[str, set[str]]:
    if not isinstance(runtime_tools_payload, dict):
        return {}
    raw_tools = runtime_tools_payload.get("tools", runtime_tools_payload)
    out: dict[str, set[str]] = {}
    if not isinstance(raw_tools, list):
        return out
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        server = str(item.get("server", "")).strip()
        name = str(item.get("name", "")).strip()
        if not server or not name:
            continue
        out.setdefault(server, set()).add(name)
    return out


def classify_server_config(name: str, cfg: dict[str, Any]) -> str:
    if name in OFFICIAL_SERVER_SPECS:
        if cfg.get("url"):
            return "official_server_misconfigured_remote"
        if cfg.get("command"):
            return "official_reference_stdio"
        return "official_server_invalid"
    if cfg.get("url"):
        return "project_or_remote_transport"
    if cfg.get("command"):
        return "custom_local_stdio"
    return "invalid"


def build_server_catalog(
    config: dict[str, Any],
    runtime_servers_payload: dict[str, Any],
    runtime_tools_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    config_servers = _normalize_config_servers(config)
    runtime_server_map = _normalize_runtime_server_map(runtime_servers_payload)
    tools_by_server = _normalize_tools_by_server(runtime_tools_payload)

    names = sorted(set(config_servers) | set(runtime_server_map) | set(tools_by_server))
    catalog: list[dict[str, Any]] = []
    for name in names:
        cfg = config_servers.get(name, {})
        runtime = runtime_server_map.get(name, {})
        catalog.append(
            {
                "name": name,
                "classification": classify_server_config(name, cfg),
                "configured_transport": (
                    "remote"
                    if cfg.get("url")
                    else "stdio"
                    if cfg.get("command")
                    else "unknown"
                ),
                "runtime_connection_type": runtime.get("connection_type", ""),
                "runtime_status": runtime.get("status", ""),
                "runtime_tools": sorted(tools_by_server.get(name, set())),
            }
        )
    return catalog


def build_runtime_audit_report(
    config: dict[str, Any],
    runtime_servers_payload: dict[str, Any],
    runtime_tools_payload: dict[str, Any],
) -> dict[str, Any]:
    config_servers = _normalize_config_servers(config)
    runtime_server_map = _normalize_runtime_server_map(runtime_servers_payload)
    tools_by_server = _normalize_tools_by_server(runtime_tools_payload)

    errors: list[str] = []
    checks: dict[str, Any] = {}
    for name, spec in OFFICIAL_SERVER_SPECS.items():
        cfg = config_servers.get(name, {})
        runtime = runtime_server_map.get(name, {})
        runtime_tools = tools_by_server.get(name, set())
        server_errors: list[str] = []

        if not cfg:
            server_errors.append("config_missing")
        else:
            if cfg.get("url"):
                server_errors.append("configured_as_remote_not_stdio")
            command = str(cfg.get("command", "")).strip()
            if command.lower() != spec.command.lower():
                server_errors.append(f"unexpected_command:{command}")
            args_text = " ".join(str(arg) for arg in cfg.get("args", []))
            for required_arg in spec.required_args:
                if required_arg not in args_text:
                    server_errors.append(f"missing_required_arg:{required_arg}")

        if not runtime:
            server_errors.append("runtime_server_missing")
        else:
            if runtime.get("connection_type") != spec.connection_type:
                server_errors.append(
                    f"unexpected_connection_type:{runtime.get('connection_type')}"
                )
            if runtime.get("status") != "connected":
                server_errors.append(f"unexpected_status:{runtime.get('status')}")

        missing_tools = sorted(tool for tool in spec.required_tools if tool not in runtime_tools)
        forbidden_tools = sorted(tool for tool in spec.forbidden_tools if tool in runtime_tools)
        if missing_tools:
            server_errors.append(f"missing_runtime_tools:{','.join(missing_tools)}")
        if forbidden_tools:
            server_errors.append(
                f"forbidden_runtime_tools_present:{','.join(forbidden_tools)}"
            )

        checks[name] = {
            "ok": not server_errors,
            "config": cfg,
            "runtime": runtime,
            "runtime_tools": sorted(runtime_tools),
            "errors": server_errors,
        }
        errors.extend(f"{name}:{err}" for err in server_errors)

    return {
        "ok": not errors,
        "errors": errors,
        "checks": checks,
        "server_catalog": build_server_catalog(
            config,
            runtime_servers_payload,
            runtime_tools_payload,
        ),
    }
