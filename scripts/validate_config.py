#!/usr/bin/env python3
"""MCP config validator.

Supported server modes:
1) Local stdio: command + args
2) Persistent remote service: url (+ transport)

Console output is intentionally ASCII-only so Windows redirected logs do not
look like mojibake when read from a non-UTF-8 shell.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp_server_contract import OFFICIAL_SERVER_SPECS

CONFIG_PATH = PROJECT_ROOT / "mcp_config.json"

ERRORS: list[str] = []
WARNINGS: list[str] = []

def fail(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def validate_timeout(name: str, srv: dict) -> None:
    timeout = srv.get("timeout", 60)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        warn(f"[{name}] invalid timeout value: {timeout}; expected a positive number")


def validate_remote_server(name: str, srv: dict) -> None:
    url = srv.get("url")
    if not isinstance(url, str) or not url.strip():
        fail(f"[{name}] url is empty or invalid")
        return

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        fail(f"[{name}] url must use http/https: {url}")
        return
    if not parsed.netloc:
        fail(f"[{name}] url is missing host[:port]: {url}")
        return

    transport = srv.get("transport")
    allowed = {"http", "streamable-http", "sse", None}
    if transport not in allowed:
        fail(f"[{name}] invalid transport: {transport}")

    if transport == "sse" and "/sse" not in (parsed.path or ""):
        warn(f"[{name}] transport=sse but URL path does not contain /sse: {parsed.path or '/'}")

    validate_timeout(name, srv)


def validate_local_stdio_server(name: str, srv: dict) -> None:
    command = srv.get("command")
    if not isinstance(command, str) or not command.strip():
        fail(f"[{name}] missing command field")
        return

    if not shutil.which(command):
        fail(f"[{name}] command is not executable or not on PATH: {command}")

    args = srv.get("args", [])
    if not isinstance(args, list):
        fail(f"[{name}] args must be an array")
        args = []

    directory: Path | None = None
    script: str | None = None

    i = 0
    while i < len(args):
        val = args[i]
        if val == "--directory" and i + 1 < len(args):
            directory = Path(args[i + 1])
            i += 2
            continue
        if isinstance(val, str) and (val.endswith(".py") or val.endswith(".js")):
            script = val
        i += 1

    if directory and not directory.exists():
        fail(f"[{name}] --directory path does not exist: {directory}")

    if script:
        full_path = (directory / script) if directory else Path(script)
        if not full_path.exists():
            fail(f"[{name}] script file does not exist: {full_path}")

    env = srv.get("env")
    if env is not None:
        if not isinstance(env, dict):
            fail(f"[{name}] env must be an object")
        else:
            for env_key, env_val in env.items():
                if not isinstance(env_key, str):
                    fail(f"[{name}] env key must be a string: {env_key!r}")
                    continue
                if not isinstance(env_val, str):
                    fail(f"[{name}] env[{env_key}] must be a string")
                    continue
                # Path-like env values are soft-checked because some files are
                # created by the server at runtime.
                if env_key.endswith("_PATH") or env_key.endswith("_FILE"):
                    p = Path(env_val)
                    parent = p.parent
                    if str(parent).strip() and not parent.exists():
                        warn(f"[{name}] env[{env_key}] parent directory does not exist: {parent}")

    validate_timeout(name, srv)


def validate_server(name: str, srv: dict) -> None:
    if not isinstance(srv, dict):
        fail(f"[{name}] config must be an object")
        return

    if srv.get("disabled"):
        warn(f"[{name}] disabled; validation skipped")
        return

    has_url = "url" in srv and srv.get("url") is not None
    has_cmd = "command" in srv and srv.get("command") is not None

    if has_url and has_cmd:
        warn(f"[{name}] both url and command are present; validating as remote url mode")

    if has_url:
        validate_remote_server(name, srv)
        return

    if has_cmd:
        validate_local_stdio_server(name, srv)
        validate_official_server_contract(name, srv)
        return

    fail(f"[{name}] missing url or command")


def validate_official_server_contract(name: str, srv: dict) -> None:
    """Hard guard against accidentally replacing official servers with local wrappers."""
    spec = OFFICIAL_SERVER_SPECS.get(name)
    if not spec:
        return

    if "url" in srv:
        fail(f"[{name}] official server must use stdio; url/SSE wrappers are not allowed")
        return

    command = str(srv.get("command", "")).strip()
    if command.lower() != spec.command.lower():
        fail(f"[{name}] command must be official entry {spec.command!r}; got {command!r}")

    args = srv.get("args", [])
    args_text = " ".join(str(a) for a in args)
    for required_arg in spec.required_args:
        if required_arg not in args_text:
            fail(f"[{name}] args missing official package/command: {required_arg}")

    serialized = json.dumps(srv, ensure_ascii=False)
    for forbidden in (
        "url",
        "external_mcp_servers",
        "filesystem_server.py",
        "fetch_server.py",
        "memory_server.py",
        "sequential_thinking_server.py",
    ):
        if forbidden in serialized:
            fail(f"[{name}] legacy wrapper or pseudo-server marker detected: {forbidden}")


def validate() -> None:
    if not CONFIG_PATH.exists():
        fail(f"config file does not exist: {CONFIG_PATH}")
        return

    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"JSON parse failed: {exc}")
        return

    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        fail('missing or empty mcpServers field; expected {"mcpServers": {...}}')
        return

    for name, srv in servers.items():
        validate_server(name, srv)


def main() -> int:
    print("=" * 50)
    print("MCP config validation")
    print("=" * 50)
    print(f"Config file: {CONFIG_PATH}\n")

    validate()

    for w in WARNINGS:
        print(f"[WARN] {w}")

    if ERRORS:
        for e in ERRORS:
            print(f"[ERROR] {e}")
        print(f"\nValidation failed: {len(ERRORS)} error(s), {len(WARNINGS)} warning(s)")
        return 1

    print(f"Validation passed: 0 error(s), {len(WARNINGS)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
