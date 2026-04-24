#!/usr/bin/env python3
"""Repeatable local browser runtime smoke check for MCP Mirror.

This script uses a locally installed Edge/Chrome browser in headless mode and
uses the DevTools protocol through websockets. It verifies the real frontend
against a running backend/frontend pair instead of relying on mock UI checks.

Requirements:
- Backend is running at http://127.0.0.1:8000
- Frontend is running at http://127.0.0.1:3000
- Edge or Chrome is installed
- Python package `websockets` is available
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets

FRONTEND_URL = "http://127.0.0.1:3000/"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
BACKEND_AUTO_TOOL_ROUTING_URL = "http://127.0.0.1:8000/api/runtime/auto-tool-routing"
BACKEND_TOOL_ONBOARDING_AUDIT_URL = "http://127.0.0.1:8000/api/mcp/tool-onboarding-audit"
BACKEND_TOOL_ONBOARDING_RUN_URL = "http://127.0.0.1:8000/api/mcp/tool-onboarding-audit/run"
BACKEND_REGRESSION_SANDBOX_BEGIN_URL = "http://127.0.0.1:8000/api/regression-sandbox/begin"
BACKEND_REGRESSION_SANDBOX_RESTORE_URL = "http://127.0.0.1:8000/api/regression-sandbox/restore"


def _pick_devtools_port() -> int:
    configured = os.environ.get("MCP_MIRROR_SMOKE_DEVTOOLS_PORT", "").strip()
    if configured:
        return int(configured)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


DEVTOOLS_PORT = _pick_devtools_port()
DEVTOOLS_VERSION_URL = f"http://127.0.0.1:{DEVTOOLS_PORT}/json/version"
DEVTOOLS_LIST_URL = f"http://127.0.0.1:{DEVTOOLS_PORT}/json/list"
SMOKE_CHAT_MODEL_ID = "Qwen/Qwen3-8B"
SMOKE_VL_MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
CDP_DEFAULT_TIMEOUT_SECONDS = 12.0
CDP_LONG_TIMEOUT_SECONDS = 55.0
CDP_MODEL_TIMEOUT_SECONDS = 190.0
CDP_VISION_TIMEOUT_SECONDS = 330.0
UPLOAD_SUMMARY_TOKEN = "UploadSummary:"
UPLOAD_MARKER = "FINAL_MARKER: outside-upload-browser-smoke-success"
VISION_SUMMARY_TOKEN = "VisionSummary:"
WORKSPACE_SMOKE_MARKER = "WORKSPACE_MARKER: workspace-browser-smoke-success"
WORKSPACE_SERVER_NAME = "workspace_docs"
WORKSPACE_AGENT_NAME = "workspace-docs-agent"
WORKSPACE_SWITCH_MARKER = "WORKSPACE_SWITCH_MARKER: switched-workspace-browser-smoke-success"
WORKSPACE_SWITCH_SERVER_NAME = "workspace_notes"
WORKSPACE_SWITCH_AGENT_NAME = "workspace-notes-agent"


def _full_frontend_reset_script(model_id: str) -> str:
    return f"""
(() => {{
  const settingsKey = 'mcp_chat_settings';
  let settings = {{}};
  try {{
    settings = JSON.parse(window.localStorage.getItem(settingsKey) || '{{}}');
  }} catch (error) {{
    settings = {{}};
  }}
  window.localStorage.setItem(settingsKey, JSON.stringify({{
    ...settings,
    language: 'en',
    confirmToolCalls: true,
    autoToolRoutingMode: 'memory_plane_plus_fallback',
    enableWorkspaceContext: false,
    workspaceContextRoot: '',
    workspaceContextAgentName: '',
    workspaceContextIncludeAgentProfile: true,
    workspaceContextIncludeMemoryFile: true,
    workspaceContextIncludeChatlogs: false,
    sessionAllowMCPs: [],
    sessionBlockMCPTools: [],
  }}));
  window.localStorage.setItem('mcp_selected_model', '{model_id}');
  window.localStorage.removeItem('mcp_chat_current_session');
  window.localStorage.removeItem('mcp_chat_client_id');
  window.sessionStorage.clear();
  return true;
}})()
"""


def _find_browser() -> str:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError("No supported browser found. Install Edge or Chrome first.")


def _http_json(url: str, timeout_seconds: float = 5.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: float = 10.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _begin_regression_sandbox() -> dict[str, Any]:
    return _post_json(
        BACKEND_REGRESSION_SANDBOX_BEGIN_URL,
        {
            "label": "browser_runtime_smoke",
            "include_uploads": True,
        },
        timeout_seconds=60.0,
    )


def _restore_regression_sandbox(sandbox_id: str) -> dict[str, Any]:
    return _post_json(
        BACKEND_REGRESSION_SANDBOX_RESTORE_URL,
        {"sandbox_id": sandbox_id},
        timeout_seconds=120.0,
    )


def _wait_for_url_json(url: str, timeout_seconds: float = 20.0) -> Any:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return _http_json(url)
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _create_browser_upload_fixture() -> Path:
    outside_dir = Path(tempfile.gettempdir()) / "mcp_mirror_browser_uploads"
    outside_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = outside_dir / "browser_smoke_resume.txt"
    filler = [f"Noise line {index:03d}: filler text for browser smoke." for index in range(80)]
    filler.extend(
        [
            "Candidate name: Browser Smoke",
            "Research focus: MCP orchestration and tool memory governance.",
            UPLOAD_MARKER,
        ]
    )
    fixture_path.write_text("\n".join(filler) + "\n", encoding="utf-8")
    return fixture_path


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _create_browser_image_fixture() -> Path:
    outside_dir = Path(tempfile.gettempdir()) / "mcp_mirror_browser_uploads"
    outside_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = outside_dir / "browser_smoke_red.png"
    width = 64
    height = 64
    row = b"\x00" + (b"\xff\x00\x00" * width)
    raw = row * height
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )
    fixture_path.write_bytes(png)
    return fixture_path


def _create_workspace_smoke_fixture() -> dict[str, Any]:
    workspace_root = Path(tempfile.gettempdir()) / f"mcp_mirror_workspace_smoke_{uuid.uuid4().hex}"
    workspace_root.mkdir(parents=True, exist_ok=True)

    docs_dir = workspace_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    sample_doc = docs_dir / "workspace_note.txt"
    sample_doc.write_text(
        "\n".join(
            [
                "Workspace browser smoke fixture",
                "This file exists to validate workspace-scoped MCP routing.",
                WORKSPACE_SMOKE_MARKER,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_meta_root = workspace_root / ".mcp-mirror"
    (workspace_meta_root / "agents" / WORKSPACE_AGENT_NAME).mkdir(parents=True, exist_ok=True)
    (workspace_meta_root / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    WORKSPACE_SERVER_NAME: {
                        "disabled": False,
                        "description": "Workspace scoped docs server",
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                            str(workspace_root),
                        ],
                        "timeout": 60,
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (workspace_meta_root / "agents" / WORKSPACE_AGENT_NAME / "agent.yaml").write_text(
        "\n".join(
            [
                f"name: {WORKSPACE_AGENT_NAME}",
                "description: Workspace-only MCP visibility test agent",
                f"allowMCPs:",
                f"  - {WORKSPACE_SERVER_NAME}",
                "blockMCPTools:",
                "  - filesystem.read_file",
                "isConfirmCallTool: false",
                f"modelKey: {SMOKE_CHAT_MODEL_ID}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "workspace_root": str(workspace_root),
        "agent_name": WORKSPACE_AGENT_NAME,
        "server_name": WORKSPACE_SERVER_NAME,
        "sample_doc_path": str(sample_doc),
        "sample_doc_name": sample_doc.name,
        "marker": WORKSPACE_SMOKE_MARKER,
    }


def _create_workspace_switch_fixture() -> dict[str, Any]:
    workspace_root = Path(tempfile.gettempdir()) / f"mcp_mirror_workspace_switch_{uuid.uuid4().hex}"
    workspace_root.mkdir(parents=True, exist_ok=True)

    notes_dir = workspace_root / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    sample_doc = notes_dir / "switch_note.txt"
    sample_doc.write_text(
        "\n".join(
            [
                "Workspace switch browser smoke fixture",
                "This file exists to validate live workspace switching.",
                WORKSPACE_SWITCH_MARKER,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    workspace_meta_root = workspace_root / ".mcp-mirror"
    (workspace_meta_root / "agents" / WORKSPACE_SWITCH_AGENT_NAME).mkdir(parents=True, exist_ok=True)
    (workspace_meta_root / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    WORKSPACE_SWITCH_SERVER_NAME: {
                        "disabled": False,
                        "description": "Workspace switch scoped notes server",
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                            str(workspace_root),
                        ],
                        "timeout": 60,
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (workspace_meta_root / "agents" / WORKSPACE_SWITCH_AGENT_NAME / "agent.yaml").write_text(
        "\n".join(
            [
                f"name: {WORKSPACE_SWITCH_AGENT_NAME}",
                "description: Alternate workspace MCP visibility test agent",
                "allowMCPs:",
                f"  - {WORKSPACE_SWITCH_SERVER_NAME}",
                "blockMCPTools:",
                f"  - {WORKSPACE_SWITCH_SERVER_NAME}.read_file",
                "isConfirmCallTool: false",
                f"modelKey: {SMOKE_CHAT_MODEL_ID}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "workspace_root": str(workspace_root),
        "agent_name": WORKSPACE_SWITCH_AGENT_NAME,
        "server_name": WORKSPACE_SWITCH_SERVER_NAME,
        "sample_doc_path": str(sample_doc),
        "sample_doc_name": sample_doc.name,
        "marker": WORKSPACE_SWITCH_MARKER,
    }


@dataclass
class SmokeCheckResult:
    name: str
    ok: bool
    details: dict[str, Any]


class DevToolsSession:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None

    async def __aenter__(self) -> "DevToolsSession":
        self._ws = await websockets.connect(self.ws_url, max_size=20_000_000)
        self._recv_task = asyncio.create_task(self._recv_loop())
        await self.call("Runtime.enable")
        await self.call("Page.enable")
        await self.call("Page.bringToFront")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            while True:
                message = json.loads(await self._ws.recv())
                message_id = message.get("id")
                if message_id in self._pending:
                    future = self._pending.pop(message_id)
                    if not future.done():
                        future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(exc)
            self._pending.clear()

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: float = CDP_DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        assert self._ws is not None
        message_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[message_id] = future
        await self._ws.send(json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }))
        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except Exception:
            self._pending.pop(message_id, None)
            raise

    async def eval(self, expression: str, timeout_seconds: float = CDP_DEFAULT_TIMEOUT_SECONDS) -> Any:
        response = await self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        }, timeout_seconds=timeout_seconds)
        result = response.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(f"Runtime.evaluate failed: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")


def _start_browser() -> subprocess.Popen:
    browser = _find_browser()
    user_data_dir = Path(tempfile.gettempdir()) / f"mcp_mirror_browser_smoke_{uuid.uuid4().hex}"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--lang=en-US",
            f"--remote-debugging-port={DEVTOOLS_PORT}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={user_data_dir}",
            FRONTEND_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            _http_json(DEVTOOLS_VERSION_URL)
            return process
        except Exception:
            time.sleep(0.5)
    process.terminate()
    raise RuntimeError("Timed out waiting for browser DevTools endpoint.")


def _get_page_ws_url() -> str:
    deadline = time.time() + 20
    last_pages: Any = []
    while time.time() < deadline:
        pages = _http_json(DEVTOOLS_LIST_URL)
        last_pages = pages
        frontend_pages = [
            page for page in pages
            if page.get("type") == "page"
            and str(page.get("url", "")).rstrip("/") == FRONTEND_URL.rstrip("/")
            and page.get("webSocketDebuggerUrl")
        ]
        if frontend_pages:
            return frontend_pages[-1]["webSocketDebuggerUrl"]
        any_pages = [
            page for page in pages
            if page.get("type") == "page" and page.get("webSocketDebuggerUrl")
        ]
        if any_pages:
            return any_pages[-1]["webSocketDebuggerUrl"]
        time.sleep(0.4)
    raise RuntimeError(
        f"Could not find browser page in DevTools target list for {FRONTEND_URL}: "
        + json.dumps(last_pages, ensure_ascii=True)
    )


async def _wait_for_document_ready(session: DevToolsSession, timeout_seconds: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        try:
            last_state = await session.eval(r"""
(() => ({
  href: window.location.href,
  readyState: document.readyState,
  hasBody: Boolean(document.body),
  bodySample: document.body ? (document.body.innerText || '').slice(0, 300) : '',
}))()
""", timeout_seconds=CDP_LONG_TIMEOUT_SECONDS)
            if last_state.get("hasBody") and last_state.get("readyState") in ("interactive", "complete"):
                return last_state
        except Exception as exc:
            last_state = {"error": repr(exc)}
        await asyncio.sleep(0.5)
    return last_state


async def _eval_with_retries(
    session: DevToolsSession,
    expression: str,
    *,
    label: str,
    timeout_seconds: float = CDP_LONG_TIMEOUT_SECONDS,
    attempts: int = 3,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await session.eval(expression, timeout_seconds=timeout_seconds)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.8 + attempt * 0.6)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error!r}")


async def _wait_for_app_ready(session: DevToolsSession, timeout_seconds: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = await session.eval(r"""
(() => {
  const body = document.body.innerText;
  const buttons = Array.from(document.querySelectorAll('button'));
  return {
    title: document.title,
    hasComposer: !!document.querySelector('textarea'),
    hasRuntimeSummary: body.includes('MCP Mirror') && body.includes('TEM') && body.includes('full_tem'),
    hasModelCatalogEntry: body.includes('Qwen3-8B') || body.includes('Gemma 4 26B'),
    buttonCount: buttons.length,
    bodySample: body.slice(0, 800),
  };
})()
""")
        if (
            last_state.get("hasComposer")
            and last_state.get("hasRuntimeSummary")
            and last_state.get("hasModelCatalogEntry")
            and int(last_state.get("buttonCount") or 0) >= 8
        ):
            return last_state
        await asyncio.sleep(1)
    return last_state


async def _wait_for_realtime_ready(session: DevToolsSession, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_state: dict[str, Any] = {}
    while time.time() < deadline:
        last_state = await session.eval(r"""
(() => {
  const body = document.body.innerText;
  return {
    hasBootstrapError: body.includes('Failed to load runtime bootstrap'),
    hasPendingQueue: body.includes('pending queue'),
    hasRealtimeConnected: body.includes('Realtime connected'),
    hasWaitingRealtime: body.includes('Waiting for realtime connection'),
    bodySample: body.slice(0, 1000),
  };
})()
""")
        if last_state.get("hasRealtimeConnected") and not last_state.get("hasWaitingRealtime"):
            return last_state
        await asyncio.sleep(1)
    return last_state


async def _navigate_reset_and_wait(
    session: DevToolsSession,
    reset_script: str,
    settle_seconds: float = 2.0,
) -> None:
    await session.call("Page.navigate", {"url": FRONTEND_URL}, timeout_seconds=CDP_LONG_TIMEOUT_SECONDS)
    await _wait_for_document_ready(session)
    await _eval_with_retries(session, reset_script, label="frontend reset")
    await session.call("Page.navigate", {"url": FRONTEND_URL}, timeout_seconds=CDP_LONG_TIMEOUT_SECONDS)
    await _wait_for_document_ready(session)
    await asyncio.sleep(settle_seconds)
    await _wait_for_app_ready(session)
    await _wait_for_realtime_ready(session)


async def _wait_for_workspace_settings_applied(
    session: DevToolsSession,
    fixture: dict[str, Any],
    *,
    timeout_seconds: float = 25.0,
) -> Any:
    deadline = time.time() + timeout_seconds
    expression = r"""
(() => {
  const fixture = __FIXTURE_JSON__;
  let settings = {};
  try {
    settings = JSON.parse(window.localStorage.getItem('mcp_chat_settings') || '{}');
  } catch (error) {
    settings = {};
  }
  const storageOk =
    settings.enableWorkspaceContext === true
    && String(settings.workspaceContextRoot || '').trim() === fixture.workspace_root
    && String(settings.workspaceContextAgentName || '').trim() === fixture.agent_name;
  return {
    ok: storageOk,
    settings,
    bodySample: (document.body.textContent || document.body.innerText || '').slice(0, 2400),
  };
})()
"""
    last_state: Any = {"ok": False, "settings": {}, "bodySample": ""}
    while time.time() < deadline:
        last_state = await session.eval(
            expression.replace("__FIXTURE_JSON__", json.dumps(fixture, ensure_ascii=True)),
            timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
        )
        if isinstance(last_state, dict) and last_state.get("ok"):
            return last_state
        await asyncio.sleep(0.75)
    return last_state


async def _run_smoke() -> list[SmokeCheckResult]:
    ws_url = _get_page_ws_url()
    results: list[SmokeCheckResult] = []

    onboarding_audit = _http_json(BACKEND_TOOL_ONBOARDING_AUDIT_URL)
    onboarding_tools = onboarding_audit.get("tools", []) if isinstance(onboarding_audit, dict) else []
    safe_gate_tools = [
        tool.get("tool_key")
        for tool in onboarding_tools
        if isinstance(tool, dict)
        and isinstance(tool.get("self_test"), dict)
        and tool["self_test"].get("safe_to_run")
        and tool["self_test"].get("gate_required")
    ]
    onboarding_gate_ok = bool(
        isinstance(onboarding_audit, dict)
        and onboarding_audit.get("summary", {}).get("total_tools", 0) > 0
        and onboarding_audit.get("summary", {}).get("schema_risk_tools", 0) == 0
        and any(str(tool.get("tool_key", "")).strip() == "fetch.fetch" for tool in onboarding_tools if isinstance(tool, dict))
        and len(safe_gate_tools) > 0
    )
    results.append(SmokeCheckResult(
        "tool_onboarding_audit_gate",
        onboarding_gate_ok,
        {
            "summary": onboarding_audit.get("summary", {}),
            "safe_gate_tools": safe_gate_tools,
            "has_fetch_fetch": any(
                str(tool.get("tool_key", "")).strip() == "fetch.fetch"
                for tool in onboarding_tools
                if isinstance(tool, dict)
            ),
        },
    ))

    onboarding_run = _post_json(
        BACKEND_TOOL_ONBOARDING_RUN_URL,
        {"tool_keys": safe_gate_tools, "execute_safe_only": True, "max_tools": len(safe_gate_tools) or 50},
        timeout_seconds=45.0,
    )
    results.append(SmokeCheckResult(
        "tool_onboarding_self_tests",
        bool(
            onboarding_run.get("ok")
            and onboarding_run.get("summary", {}).get("gate_failed", 1) == 0
            and onboarding_run.get("summary", {}).get("failed", 1) == 0
        ),
        onboarding_run,
    ))

    workspace_fixture = _create_workspace_smoke_fixture()
    workspace_switch_fixture = _create_workspace_switch_fixture()
    workspace_query = urllib.parse.urlencode({"workspace_root": workspace_fixture["workspace_root"]})
    workspace_audit = _http_json(f"{BACKEND_TOOL_ONBOARDING_AUDIT_URL}?{workspace_query}", timeout_seconds=45.0)
    workspace_tools = workspace_audit.get("tools", []) if isinstance(workspace_audit, dict) else []
    workspace_tool_keys = [
        str(tool.get("tool_key", ""))
        for tool in workspace_tools
        if isinstance(tool, dict)
    ]
    workspace_safe_gate_tools = [
        str(tool.get("tool_key", ""))
        for tool in workspace_tools
        if isinstance(tool, dict)
        and str(tool.get("server", "")).strip() == workspace_fixture["server_name"]
        and isinstance(tool.get("self_test"), dict)
        and tool["self_test"].get("safe_to_run")
        and tool["self_test"].get("gate_required")
    ]
    workspace_audit_ok = bool(
        isinstance(workspace_audit, dict)
        and workspace_audit.get("ok")
        and workspace_audit.get("workspace_mcp", {}).get("workspace_enabled")
        and workspace_fixture["server_name"] in workspace_audit.get("workspace_mcp", {}).get("workspace_servers", [])
        and any(key.startswith(f"{workspace_fixture['server_name']}.") for key in workspace_tool_keys)
    )
    results.append(SmokeCheckResult(
        "workspace_tool_onboarding_audit_gate",
        workspace_audit_ok,
        {
            "workspace_root": workspace_fixture["workspace_root"],
            "workspace_mcp": workspace_audit.get("workspace_mcp", {}) if isinstance(workspace_audit, dict) else {},
            "summary": workspace_audit.get("summary", {}) if isinstance(workspace_audit, dict) else {},
            "workspace_tool_keys": workspace_tool_keys,
            "workspace_safe_gate_tools": workspace_safe_gate_tools,
        },
    ))

    workspace_run = _post_json(
        BACKEND_TOOL_ONBOARDING_RUN_URL,
        {
            "tool_keys": workspace_safe_gate_tools,
            "execute_safe_only": True,
            "max_tools": len(workspace_safe_gate_tools) or 20,
            "workspace_root": workspace_fixture["workspace_root"],
        },
        timeout_seconds=45.0,
    )
    results.append(SmokeCheckResult(
        "workspace_tool_onboarding_self_tests",
        bool(
            workspace_run.get("ok")
            and workspace_run.get("workspace_mcp", {}).get("workspace_enabled")
            and workspace_fixture["server_name"] in workspace_run.get("workspace_mcp", {}).get("workspace_servers", [])
            and workspace_run.get("summary", {}).get("gate_failed", 1) == 0
            and workspace_run.get("summary", {}).get("failed", 1) == 0
        ),
        workspace_run,
    ))

    async with DevToolsSession(ws_url) as session:
        await _navigate_reset_and_wait(session, _full_frontend_reset_script('Qwen/Qwen3-8B'))
        homepage = await _wait_for_app_ready(session)
        realtime = await _wait_for_realtime_ready(session)
        results.append(SmokeCheckResult(
            "homepage",
            bool(
                homepage.get("hasComposer")
                and homepage.get("hasRuntimeSummary")
                and homepage.get("hasModelCatalogEntry")
                and realtime.get("hasRealtimeConnected")
                and not realtime.get("hasBootstrapError")
            ),
            {
                **homepage,
                "realtime": realtime,
            },
        ))

        model_switch = await session.eval(r"""
(async () => {
  const buttons = Array.from(document.querySelectorAll('button'));
  const modelButton = buttons[0];
  if (!modelButton) {
    return { ok: false, reason: 'model button missing' };
  }
  modelButton.click();
  await new Promise((resolve) => setTimeout(resolve, 700));
  const options = Array.from(document.querySelectorAll('[role="option"]'));
  const option = options.find((el) => (el.innerText || '').includes('Gemma 4 26B'));
  if (!option) {
    return { ok: false, reason: 'Gemma option missing', optionCount: options.length };
  }
  option.click();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  return {
    ok: (buttons[0].innerText || '').includes('Gemma 4 26B'),
    selected: (buttons[0].innerText || '').trim(),
  };
})()
""")
        results.append(SmokeCheckResult("model_switch", bool(model_switch.get("ok")), model_switch))

        await _navigate_reset_and_wait(session, _full_frontend_reset_script('Qwen/Qwen3-8B'))
        tem_panel = await session.eval(r"""
(async () => {
  const buttons = Array.from(document.querySelectorAll('button'));
  const temButton = buttons[3];
  if (!temButton) {
    return { ok: false, reason: 'TEM button missing' };
  }
  temButton.click();
  await new Promise((resolve) => setTimeout(resolve, 1500));
  const body = document.body.innerText;
  return {
    ok: body.includes('recipe') && body.includes('failure guard') && body.includes('TEM'),
    hasEvaluationTab: body.includes('Memory Evaluation') || body.includes('benchmark') || body.includes('Evaluation'),
    hasParameterLearning: body.includes('feedback') || body.includes('exploration') || body.includes('runtime'),
    bodySample: body.slice(0, 1200),
  };
})()
""")
        results.append(SmokeCheckResult("tem_panel", bool(tem_panel.get("ok")), tem_panel))

        await _navigate_reset_and_wait(session, _full_frontend_reset_script('Qwen/Qwen3-8B'))
        health_panel = await session.eval(r"""
(async () => {
  const buttons = Array.from(document.querySelectorAll('button'));
  const healthButton = buttons[4];
  if (!healthButton) {
    return { ok: false, reason: 'health button missing' };
  }
  healthButton.click();
  await new Promise((resolve) => setTimeout(resolve, 1500));
  const body = document.body.innerText;
  const hasHealthSummary =
    body.includes('/health')
    && body.includes('/api/system/bootstrap')
    && body.includes('/api/mcp/tool-onboarding-audit');
  const hasProviderSection =
    body.includes('OpenRouter')
    && (body.includes('SiliconFlow') || body.includes('siliconflow'));
  const hasToolAuditMetrics =
    body.includes('auto_executable_tools')
    || body.includes('Auto executable tools')
    || body.includes('HEALTH.AUTOEXECUTABLETOOLS')
    || body.includes('health.autoExecutableTools');
  return {
    ok: hasHealthSummary && hasProviderSection && hasToolAuditMetrics,
    hasHealthSummary,
    hasProviderSection,
    hasToolAuditMetrics,
    hasDiagnostics: body.includes('/api/memory-plane') && body.includes('/api/tem/benchmark'),
    hasMcpRuntime: body.includes('cdar_mcp') && body.includes('filesystem') && body.includes('sequential_thinking'),
    bodySample: body.slice(0, 1600),
  };
})()
""")
        results.append(SmokeCheckResult("health_panel", bool(health_panel.get("ok")), health_panel))

        workspace_setup_script = r"""
(() => {
  const fixture = __FIXTURE_JSON__;
  const settingsKey = 'mcp_chat_settings';
  let settings = {};
  try {
    settings = JSON.parse(window.localStorage.getItem(settingsKey) || '{}');
  } catch (error) {
    settings = {};
  }
  window.localStorage.setItem(settingsKey, JSON.stringify({
    ...settings,
    language: 'en',
    confirmToolCalls: true,
    autoToolRoutingMode: 'memory_plane_plus_fallback',
    enableWorkspaceContext: true,
    workspaceContextRoot: fixture.workspace_root,
    workspaceContextAgentName: fixture.agent_name,
    workspaceContextIncludeAgentProfile: true,
    workspaceContextIncludeMemoryFile: true,
    workspaceContextIncludeChatlogs: false,
    sessionAllowMCPs: [],
    sessionBlockMCPTools: [],
  }));
  window.localStorage.setItem('mcp_selected_model', '__CHAT_MODEL_ID__');
  window.localStorage.removeItem('mcp_chat_current_session');
  window.localStorage.removeItem('mcp_chat_client_id');
  window.sessionStorage.clear();
  return true;
})()
"""
        workspace_setup_script = (
            workspace_setup_script
            .replace("__FIXTURE_JSON__", json.dumps(workspace_fixture, ensure_ascii=True))
            .replace("__CHAT_MODEL_ID__", SMOKE_CHAT_MODEL_ID)
        )
        await _navigate_reset_and_wait(session, workspace_setup_script, settle_seconds=3)
        workspace_settings_ready = await _wait_for_workspace_settings_applied(session, workspace_fixture)
        await session.eval(r"""
(() => {
  const settingsButton = Array.from(document.querySelectorAll('button'))
    .find((button) => (button.getAttribute('title') || '').includes('Settings'));
  if (settingsButton) {
    settingsButton.click();
    return true;
  }
  return false;
})()
""")
        await asyncio.sleep(2)
        workspace_settings = await session.eval(r"""
(async () => {
  const fixture = __FIXTURE_JSON__;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let body = '';
  const setInputValue = (input, nextValue) => {
    if (!input) {
      return;
    }
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) {
      setter.call(input, nextValue);
    } else {
      input.value = nextValue;
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await sleep(1500);
    body = document.body.textContent || document.body.innerText || '';
    const workspaceToggleLabel = Array.from(document.querySelectorAll('label'))
      .find((label) => (label.innerText || '').includes('Workspace file context'));
    const workspaceToggle = workspaceToggleLabel?.querySelector('input[type="checkbox"]');
    if (workspaceToggle && !workspaceToggle.checked) {
      workspaceToggle.click();
      await sleep(400);
    }
    const rootInput = Array.from(document.querySelectorAll('input'))
      .find((input) => (input.getAttribute('placeholder') || '').includes('Workspace root'));
    const agentInput = Array.from(document.querySelectorAll('input'))
      .find((input) => (input.getAttribute('placeholder') || '').includes('Agent name'));
    if (rootInput && rootInput.value !== fixture.workspace_root) {
      setInputValue(rootInput, fixture.workspace_root);
      await sleep(200);
    }
    if (agentInput && agentInput.value !== fixture.agent_name) {
      setInputValue(agentInput, fixture.agent_name);
      await sleep(200);
    }
    body = document.body.textContent || document.body.innerText || '';
    const hasWorkspacePool = body.includes('Current workspace MCP pool')
      && body.includes(fixture.server_name)
      && body.includes(fixture.workspace_root);
    const hasAgentVisibility = body.includes('Active agent profile')
      && body.includes('Allowed MCP servers')
      && body.includes(fixture.server_name);
    const auditToggle = Array.from(document.querySelectorAll('button'))
      .find((button) => (button.innerText || '').includes('Run onboarding gate'));
    if (auditToggle && !body.includes(`${fixture.server_name}.list_allowed_directories`)) {
      auditToggle.click();
      await sleep(500);
      body = document.body.innerText;
    }
    const workspaceSummary = Array.from(document.querySelectorAll('summary'))
      .find((summary) => (summary.innerText || '').includes(fixture.server_name));
    if (workspaceSummary && !body.includes(`${fixture.server_name}.list_allowed_directories`)) {
      workspaceSummary.click();
      await sleep(500);
      body = document.body.innerText;
    }
    const hasOnboardingAudit =
      (body.includes('One-click regression check after adding an MCP server') || body.includes('Run onboarding gate'))
      && body.includes(`${fixture.server_name}.list_allowed_directories`);
    const hasWorkspaceOverview = body.includes('Workspace server overview')
      || body.includes('Expand to inspect the full tool list');
    const hasMinimalSelfTest = body.includes('Minimal self-test')
      || body.includes('self-test ready')
      || body.includes('latest:');
    const workspaceHeading = Array.from(document.querySelectorAll('div,span,h2,h3,h4'))
      .find((element) => (element.innerText || '').includes('Current workspace MCP pool'));
    if (workspaceHeading) {
      workspaceHeading.scrollIntoView({ block: 'center' });
      await sleep(300);
      body = document.body.textContent || document.body.innerText || '';
    }
    if (hasWorkspacePool && hasAgentVisibility && hasOnboardingAudit && hasWorkspaceOverview && hasMinimalSelfTest && body.includes(`${fixture.server_name}.list_allowed_directories`)) {
      break;
    }
  }

  return {
    ok:
      body.includes('Current workspace MCP pool')
      && body.includes(fixture.server_name)
      && body.includes(fixture.workspace_root)
      && body.includes('Active agent profile')
      && body.includes('Allowed MCP servers')
      && body.includes(fixture.server_name)
      && (body.includes('One-click regression check after adding an MCP server') || body.includes('Run onboarding gate'))
      && body.includes(`${fixture.server_name}.list_allowed_directories`)
      && (body.includes('Workspace server overview') || body.includes('Expand to inspect the full tool list'))
      && (body.includes('Minimal self-test') || body.includes('self-test ready') || body.includes('latest:')),
    hasWorkspacePool: body.includes('Current workspace MCP pool') && body.includes(fixture.server_name),
    hasAgentVisibility: body.includes('Active agent profile') && body.includes('Allowed MCP servers') && body.includes(fixture.server_name),
    hasOnboardingTool: body.includes(`${fixture.server_name}.list_allowed_directories`),
    hasRegressionEntry: body.includes('Run onboarding gate') || body.includes('One-click regression check after adding an MCP server'),
    settingsReady: __SETTINGS_READY__,
    bodySample: body.slice(0, 4200),
  };
})()
"""
        .replace("__FIXTURE_JSON__", json.dumps(workspace_fixture, ensure_ascii=True))
        .replace("__SETTINGS_READY__", "true" if workspace_settings_ready.get("ok") else "false"), timeout_seconds=CDP_LONG_TIMEOUT_SECONDS)
        results.append(SmokeCheckResult("workspace_settings_mcp_pool", bool(workspace_settings.get("ok")), workspace_settings))

        await _navigate_reset_and_wait(session, workspace_setup_script, settle_seconds=3)
        workspace_chat = await session.eval(r"""
(async () => {
  const fixture = __FIXTURE_JSON__;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const body = document.body.innerText;
    if (body.includes('Realtime connected') && document.querySelector('textarea')) {
      break;
    }
    await sleep(1000);
  }
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return { ok: false, reason: 'textarea missing', bodySample: document.body.innerText.slice(0, 1800) };
  }
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(
    textarea,
    `Read @./docs/${fixture.sample_doc_name} from the current workspace. Use the workspace MCP tool if needed, then answer in one sentence starting with "WorkspaceSummary:" and include the exact WORKSPACE_MARKER line.`,
  );
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(400);
  const sendButton = Array.from(document.querySelectorAll('button')).at(-1);
  if (!sendButton || sendButton.disabled) {
    return { ok: false, reason: 'send button unavailable', bodySample: document.body.innerText.slice(0, 2200) };
  }
  sendButton.click();

  let body = '';
  let deliveryBadge = '';
  for (let attempt = 0; attempt < 180; attempt += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const hasWorkspaceToolBlock =
      body.includes('Tool call')
      && (
        body.includes(`${fixture.server_name}.read_text_file`)
        || body.includes(`${fixture.server_name}.read_file`)
      );
    const hasDisallowedGlobalTool =
      body.includes('filesystem.read_text_file')
      || body.includes('filesystem.read_file');
    const hasSummary = body.includes('WorkspaceSummary:') && body.includes(fixture.marker);
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (hasWorkspaceToolBlock && hasSummary && !hasDisallowedGlobalTool) {
      return {
        ok: true,
        hasWorkspaceToolBlock,
        hasSummary,
        hasDisallowedGlobalTool,
        deliveryBadge,
        bodySample: body.slice(0, 3600),
      };
    }
    if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
      return {
        ok: false,
        reason: `delivery ${deliveryBadge}`,
        hasWorkspaceToolBlock,
        hasSummary,
        hasDisallowedGlobalTool,
        deliveryBadge,
        bodySample: body.slice(0, 3600),
      };
    }
  }
  return {
    ok: false,
    reason: 'timed out waiting for workspace-scoped natural tool chat',
    deliveryBadge,
    bodySample: document.body.innerText.slice(0, 3600),
  };
})()
""".replace("__FIXTURE_JSON__", json.dumps(workspace_fixture, ensure_ascii=True)), timeout_seconds=CDP_MODEL_TIMEOUT_SECONDS)
        results.append(SmokeCheckResult("workspace_scoped_natural_tool_chat", bool(workspace_chat.get("ok")), workspace_chat))

        workspace_switch_setup_script = r"""
(() => {
  const fixture = __FIXTURE_JSON__;
  const settingsKey = 'mcp_chat_settings';
  let settings = {};
  try {
    settings = JSON.parse(window.localStorage.getItem(settingsKey) || '{}');
  } catch (error) {
    settings = {};
  }
  window.localStorage.setItem(settingsKey, JSON.stringify({
    ...settings,
    language: 'en',
    confirmToolCalls: true,
    autoToolRoutingMode: 'memory_plane_plus_fallback',
    enableWorkspaceContext: true,
    workspaceContextRoot: fixture.workspace_root,
    workspaceContextAgentName: fixture.agent_name,
    workspaceContextIncludeAgentProfile: true,
    workspaceContextIncludeMemoryFile: true,
    workspaceContextIncludeChatlogs: false,
    sessionAllowMCPs: [],
    sessionBlockMCPTools: [],
  }));
  window.localStorage.setItem('mcp_selected_model', '__CHAT_MODEL_ID__');
  window.localStorage.removeItem('mcp_chat_current_session');
  window.localStorage.removeItem('mcp_chat_client_id');
  window.sessionStorage.clear();
  return true;
})()
"""
        workspace_switch_setup_script = (
            workspace_switch_setup_script
            .replace("__FIXTURE_JSON__", json.dumps(workspace_switch_fixture, ensure_ascii=True))
            .replace("__CHAT_MODEL_ID__", SMOKE_CHAT_MODEL_ID)
        )
        await _navigate_reset_and_wait(session, workspace_switch_setup_script, settle_seconds=3)
        workspace_switch_ready = await _wait_for_workspace_settings_applied(session, workspace_switch_fixture)
        await session.eval(r"""
(() => {
  const settingsButton = Array.from(document.querySelectorAll('button'))
    .find((button) => (button.getAttribute('title') || '').includes('Settings'));
  if (settingsButton) {
    settingsButton.click();
    return true;
  }
  return false;
})()
""")
        await asyncio.sleep(2)
        workspace_switch_settings = await session.eval(r"""
(async () => {
  const first = __FIRST_FIXTURE_JSON__;
  const second = __SECOND_FIXTURE_JSON__;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let body = '';
  const setInputValue = (input, nextValue) => {
    if (!input) {
      return;
    }
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) {
      setter.call(input, nextValue);
    } else {
      input.value = nextValue;
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await sleep(1000);
    body = document.body.textContent || document.body.innerText || '';
    const workspaceToggleLabel = Array.from(document.querySelectorAll('label'))
      .find((label) => (label.innerText || '').includes('Workspace file context'));
    const workspaceToggle = workspaceToggleLabel?.querySelector('input[type="checkbox"]');
    if (workspaceToggle && !workspaceToggle.checked) {
      workspaceToggle.click();
      await sleep(400);
    }
    const rootInput = Array.from(document.querySelectorAll('input'))
      .find((input) => (input.getAttribute('placeholder') || '').includes('Workspace root'));
    const agentInput = Array.from(document.querySelectorAll('input'))
      .find((input) => (input.getAttribute('placeholder') || '').includes('Agent name'));
    if (rootInput && rootInput.value !== second.workspace_root) {
      setInputValue(rootInput, second.workspace_root);
      await sleep(200);
    }
    if (agentInput && agentInput.value !== second.agent_name) {
      setInputValue(agentInput, second.agent_name);
      await sleep(200);
    }
    body = document.body.textContent || document.body.innerText || '';
    const workspaceHeading = Array.from(document.querySelectorAll('div,span,h2,h3,h4'))
      .find((element) => (element.innerText || '').includes('Current workspace MCP pool'));
    if (workspaceHeading) {
      workspaceHeading.scrollIntoView({ block: 'center' });
      await sleep(300);
      body = document.body.textContent || document.body.innerText || '';
    }
    const auditToggle = Array.from(document.querySelectorAll('button'))
      .find((button) => (button.innerText || '').includes('Run onboarding gate'));
    if (auditToggle && !body.includes(`${second.server_name}.list_allowed_directories`)) {
      auditToggle.click();
      await sleep(500);
      body = document.body.textContent || document.body.innerText || '';
    }
    const summary = Array.from(document.querySelectorAll('summary'))
      .find((item) => (item.innerText || '').includes(second.server_name));
    if (summary && !body.includes(`${second.server_name}.list_allowed_directories`)) {
      summary.click();
      await sleep(500);
      body = document.body.textContent || document.body.innerText || '';
    }
    if (
      body.includes('Current workspace MCP pool')
      && body.includes(second.workspace_root)
      && body.includes(second.server_name)
      && body.includes(`${second.server_name}.list_allowed_directories`)
      
      && (body.includes('Workspace server overview') || body.includes('Expand to inspect the full tool list'))
      && !body.includes(first.workspace_root)
    ) {
      break;
    }
  }
  return {
    ok:
      body.includes('Current workspace MCP pool')
      && body.includes(second.workspace_root)
      && body.includes(second.server_name)
      && body.includes(`${second.server_name}.list_allowed_directories`)
      && (body.includes('Workspace server overview') || body.includes('Expand to inspect the full tool list'))
      && (body.includes('Minimal self-test') || body.includes('self-test ready') || body.includes('latest:'))
      
      && !body.includes(first.workspace_root),
    hasWorkspacePool: body.includes('Current workspace MCP pool') && body.includes(second.server_name),
    hasOnboardingTool: body.includes(`${second.server_name}.list_allowed_directories`),
    hasRegressionEntry: body.includes('Run onboarding gate') || body.includes('One-click regression check after adding an MCP server'),
    hasFirstWorkspaceLeak: body.includes(first.workspace_root),
    settingsReady: __SETTINGS_READY__,
    bodySample: body.slice(0, 4200),
  };
})()
"""
        .replace("__FIRST_FIXTURE_JSON__", json.dumps(workspace_fixture, ensure_ascii=True))
        .replace("__SECOND_FIXTURE_JSON__", json.dumps(workspace_switch_fixture, ensure_ascii=True))
        .replace("__SETTINGS_READY__", "true" if workspace_switch_ready.get("ok") else "false"), timeout_seconds=CDP_LONG_TIMEOUT_SECONDS)
        await _navigate_reset_and_wait(session, workspace_switch_setup_script, settle_seconds=3)
        workspace_switch_chat = await session.eval(r"""
(async () => {
  const first = __FIRST_FIXTURE_JSON__;
  const second = __SECOND_FIXTURE_JSON__;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const body = document.body.innerText;
    if (body.includes('Realtime connected') && document.querySelector('textarea')) {
      break;
    }
    await sleep(1000);
  }
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return { ok: false, reason: 'textarea missing after workspace switch', bodySample: document.body.innerText.slice(0, 2600) };
  }
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(
    textarea,
    `Read @./notes/${second.sample_doc_name} from the current workspace. Use the workspace MCP tool if needed, then answer in one sentence starting with "SwitchSummary:" and include the exact WORKSPACE_SWITCH_MARKER line.`,
  );
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(400);
  const sendButton = Array.from(document.querySelectorAll('button')).at(-1);
  if (!sendButton || sendButton.disabled) {
    return { ok: false, reason: 'send button unavailable after workspace switch', bodySample: document.body.innerText.slice(0, 2600) };
  }
  sendButton.click();

  let body = '';
  let deliveryBadge = '';
  for (let attempt = 0; attempt < 180; attempt += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const hasSecondToolBlock =
      body.includes('Tool call')
      && (
        body.includes(`${second.server_name}.read_text_file`)
        || body.includes(`${second.server_name}.read_file`)
      );
    const hasFirstWorkspaceLeak =
      body.includes(`${first.server_name}.read_text_file`)
      || body.includes(`${first.server_name}.read_file`)
      || body.includes(first.workspace_root);
    const hasGlobalLeak =
      body.includes('filesystem.read_text_file')
      || body.includes('filesystem.read_file');
    const hasSummary = body.includes('SwitchSummary:') && body.includes(second.marker);
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (hasSecondToolBlock && hasSummary && !hasFirstWorkspaceLeak && !hasGlobalLeak) {
      return {
        ok: true,
        hasSecondToolBlock,
        hasSummary,
        hasFirstWorkspaceLeak,
        hasGlobalLeak,
        deliveryBadge,
        bodySample: body.slice(0, 4200),
      };
    }
    if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
      return {
        ok: false,
        reason: `delivery ${deliveryBadge}`,
        hasSecondToolBlock,
        hasSummary,
        hasFirstWorkspaceLeak,
        hasGlobalLeak,
        deliveryBadge,
        bodySample: body.slice(0, 4200),
      };
    }
  }
  return {
    ok: false,
    reason: 'timed out waiting for switched workspace scoped chat',
    deliveryBadge,
    bodySample: document.body.innerText.slice(0, 4200),
  };
})()
"""
        .replace("__FIRST_FIXTURE_JSON__", json.dumps(workspace_fixture, ensure_ascii=True))
        .replace("__SECOND_FIXTURE_JSON__", json.dumps(workspace_switch_fixture, ensure_ascii=True)), timeout_seconds=CDP_MODEL_TIMEOUT_SECONDS)
        workspace_switch_result = {
            "ok": bool(workspace_switch_settings.get("ok")) and bool(workspace_switch_chat.get("ok")),
            "settings": workspace_switch_settings,
            "chat": workspace_switch_chat,
        }
        results.append(SmokeCheckResult("workspace_switch_root_visibility_chat", bool(workspace_switch_result.get("ok")), workspace_switch_result))

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(_full_frontend_reset_script('Qwen/Qwen3-8B'))
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(_full_frontend_reset_script('Qwen/Qwen3-8B'))
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)
        normal_chat = await session.eval(r"""
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let body = '';
  for (let i = 0; i < 30; i += 1) {
    body = document.body.innerText;
    if (body.includes('Realtime connected') && document.querySelector('textarea')) {
      break;
    }
    await sleep(1000);
  }
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return {
      ok: false,
      reason: 'textarea missing',
      bodySample: document.body.innerText.slice(0, 1400),
    };
  }

  const text = 'What is the purpose of Tool Execution Memory in this system? Answer in one short paragraph and do not call any external tool unless truly necessary.';
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(textarea, text);
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(300);

  const buttons = Array.from(document.querySelectorAll('button'));
  const sendButton = buttons[buttons.length - 1];
  if (!sendButton || sendButton.disabled) {
    return {
      ok: false,
      reason: 'send button unavailable',
      bodySample: document.body.innerText.slice(0, 1600),
    };
  }
  sendButton.click();

  let deliveryBadge = '';
  for (let i = 0; i < 150; i += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const hasAssistantAnswer = body.includes('Tool Execution Memory') || body.includes('TEM');
    const hasToolResult =
      body.includes('Tool call')
      || body.includes('filesystem.read')
      || body.includes('fetch.fetch')
      || body.includes('cdar_mcp.')
      || body.includes('sequentialthinking');
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (hasAssistantAnswer && !hasToolResult) {
      return {
        ok: true,
        hasAssistantAnswer,
        hasToolResult,
        deliveryBadge,
        bodySample: body.slice(0, 2400),
      };
    }
    if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
      return {
        ok: false,
        reason: `delivery ${deliveryBadge}`,
        hasAssistantAnswer,
        hasToolResult,
        deliveryBadge,
        bodySample: body.slice(0, 2400),
      };
    }
  }

  const hasAssistantAnswer = body.includes('Tool Execution Memory') || body.includes('TEM');
  const hasToolResult =
    body.includes('Tool call')
    || body.includes('filesystem.read')
    || body.includes('fetch.fetch')
    || body.includes('cdar_mcp.')
    || body.includes('sequentialthinking');
  return {
    ok: false,
    reason: 'timed out waiting for normal chat result',
    hasAssistantAnswer,
    hasToolResult,
    deliveryBadge,
    bodySample: body.slice(0, 2400),
  };
})()
""", timeout_seconds=CDP_MODEL_TIMEOUT_SECONDS)
        results.append(SmokeCheckResult("normal_chat_no_tool", bool(normal_chat.get("ok")), normal_chat))

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(_full_frontend_reset_script('Qwen/Qwen3-8B'))
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)
        natural_auto_tool = await session.eval(r"""
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let body = '';
  for (let i = 0; i < 30; i += 1) {
    body = document.body.innerText;
    if (body.includes('Realtime connected') && document.querySelector('textarea')) {
      break;
    }
    await sleep(1000);
  }
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return {
      ok: false,
      reason: 'textarea missing',
      bodySample: document.body.innerText.slice(0, 1400),
    };
  }
  const text = 'Please open http://127.0.0.1:8000/health with the appropriate tool. After using the tool, answer in one sentence that starts with "Endpoint summary:".';
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(textarea, text);
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(300);
  const buttons = Array.from(document.querySelectorAll('button'));
  const sendButton = buttons[buttons.length - 1];
  if (!sendButton || sendButton.disabled) {
    return {
      ok: false,
      reason: 'send button unavailable',
      buttonCount: buttons.length,
      bodySample: document.body.innerText.slice(0, 1600),
    };
  }
  sendButton.click();

  let deliveryBadge = '';
  for (let i = 0; i < 150; i += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const toolIndex = body.indexOf('fetch.fetch');
    const hasToolSection =
      body.includes('Tool call')
      && toolIndex >= 0
      && (
        body.includes('Details')
        || body.includes('Hide')
        || body.includes('Result summary')
        || body.includes('Arguments')
        || body.includes('ARGUMENTS')
      );
    const summaryIndex = body.indexOf('Endpoint summary:');
    const hasSummary = summaryIndex >= 0 && !body.includes('model summary step failed') && !body.includes('Summary failure:');
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (hasToolSection && hasSummary) {
      return {
        ok: true,
        hasToolBlock: hasToolSection,
        hasSummary,
        toolIndex,
        summaryIndex,
        deliveryBadge,
        bodySample: body.slice(0, 2600),
      };
    }
    if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
      return {
        ok: false,
        reason: `delivery ${deliveryBadge}`,
        hasToolBlock: hasToolSection,
        hasSummary,
        deliveryBadge,
        bodySample: body.slice(0, 2600),
      };
    }
  }

  const toolIndex = body.indexOf('fetch.fetch');
  const hasToolSection =
    body.includes('Tool call')
    && toolIndex >= 0
    && (
      body.includes('Details')
      || body.includes('Hide')
      || body.includes('Result summary')
      || body.includes('Arguments')
      || body.includes('ARGUMENTS')
    );
  const summaryIndex = body.indexOf('Endpoint summary:');
  const hasSummary = summaryIndex >= 0 && !body.includes('model summary step failed') && !body.includes('Summary failure:');
  return {
    ok: false,
    reason: 'timed out waiting for auto-tool chat result',
    hasToolBlock: hasToolSection,
    hasSummary,
    deliveryBadge,
    bodySample: body.slice(0, 2600),
  };
})()
""", timeout_seconds=CDP_MODEL_TIMEOUT_SECONDS)
        results.append(SmokeCheckResult("natural_auto_tool_chat", bool(natural_auto_tool.get("ok")), natural_auto_tool))

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(_full_frontend_reset_script('Qwen/Qwen3-8B'))
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)
        upload_fixture = _create_browser_upload_fixture()
        fixture_payload = {
            "name": upload_fixture.name,
            "mime_type": "text/plain",
            "base64": base64.b64encode(upload_fixture.read_bytes()).decode("ascii"),
            "summary_token": UPLOAD_SUMMARY_TOKEN,
            "marker": UPLOAD_MARKER,
        }
        upload_script = r"""
(async () => {{
  const fixture = __FIXTURE_JSON__;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const decodeBase64 = (value) => Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
  const textarea = document.querySelector('textarea');
  const attachmentInput = document.querySelector('[data-testid="attachment-input"]');
  if (!textarea || !(attachmentInput instanceof HTMLInputElement)) {
    return {
      ok: false,
      reason: 'composer or attachment input missing',
      bodySample: document.body.innerText.slice(0, 1800),
    };
  }

  const file = new File([decodeBase64(fixture.base64)], fixture.name, { type: fixture.mime_type });
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  attachmentInput.files = dataTransfer.files;
  attachmentInput.dispatchEvent(new Event('change', { bubbles: true }));

  let body = '';
  for (let i = 0; i < 60; i += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const hasPendingAttachment = body.includes(fixture.name);
    const hasTransparencyHint =
      body.includes('Visible text is truncated; the model will not see the full body.')
      || body.includes('Attachment body text was parsed, but the UI hides the full content');
    if (hasPendingAttachment && hasTransparencyHint) {
      break;
    }
  }

  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(
    textarea,
    'Please inspect the uploaded file and tell me the exact FINAL_MARKER line. Use the appropriate filesystem reading tool automatically if needed. Reply in one sentence starting with "UploadSummary:".',
  );
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(300);

  const buttons = Array.from(document.querySelectorAll('button'));
  const sendButton = buttons[buttons.length - 1];
  if (!sendButton || sendButton.disabled) {
    return {
      ok: false,
      reason: 'send button unavailable after upload',
      bodySample: document.body.innerText.slice(0, 2200),
    };
  }
  sendButton.click();

  let deliveryBadge = '';
  for (let i = 0; i < 180; i += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const hasToolCard =
      body.includes('Tool call')
      && (
        body.includes('filesystem.read_text_file')
        || body.includes('filesystem.read_file')
      );
    const hasAssistantSummary = body.includes(fixture.summary_token) && body.includes(fixture.marker);
    const hasFalseEmptyClaim = body.includes('file is empty') || body.includes('no FINAL_MARKER line was found');
    const keepsAttachmentHidden =
      (
        body.includes('Attachment body text was parsed, but the message bubble hides the file body')
        || body.includes('Result summary')
        || body.includes('Result hidden.')
      )
      && !body.includes('Research focus: MCP orchestration and tool memory governance.');
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (hasToolCard && hasAssistantSummary && keepsAttachmentHidden && !hasFalseEmptyClaim) {
      return {
        ok: true,
        hasToolCard,
        hasAssistantSummary,
        keepsAttachmentHidden,
        hasFalseEmptyClaim,
        deliveryBadge,
        bodySample: body.slice(0, 3200),
      };
    }
    if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
      return {
        ok: false,
        reason: `delivery ${deliveryBadge}`,
        hasToolCard,
        hasAssistantSummary,
        keepsAttachmentHidden,
        hasFalseEmptyClaim,
        bodySample: body.slice(0, 3200),
      };
    }
  }

  return {
    ok: false,
    reason: 'timed out waiting for uploaded attachment auto-tool result',
    deliveryBadge,
    bodySample: document.body.innerText.slice(0, 3200),
  };
}})()
"""
        upload_script = upload_script.replace("__FIXTURE_JSON__", json.dumps(fixture_payload, ensure_ascii=True))
        upload_result = await session.eval(
            upload_script,
            timeout_seconds=CDP_MODEL_TIMEOUT_SECONDS,
        )
        results.append(SmokeCheckResult("uploaded_attachment_auto_tool_chat", bool(upload_result.get("ok")), upload_result))

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(_full_frontend_reset_script(SMOKE_VL_MODEL_ID))
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)
        image_fixture = _create_browser_image_fixture()
        image_fixture_payload = {
            "name": image_fixture.name,
            "mime_type": "image/png",
            "base64": base64.b64encode(image_fixture.read_bytes()).decode("ascii"),
            "summary_token": VISION_SUMMARY_TOKEN,
        }
        image_script = r"""
(async () => {
  const fixture = __FIXTURE_JSON__;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const decodeBase64 = (value) => Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
  const textarea = document.querySelector('textarea');
  const attachmentInput = document.querySelector('[data-testid="attachment-input"]');
  if (!textarea || !(attachmentInput instanceof HTMLInputElement)) {
    return {
      ok: false,
      reason: 'composer or attachment input missing',
      bodySample: document.body.innerText.slice(0, 1800),
    };
  }

  const file = new File([decodeBase64(fixture.base64)], fixture.name, { type: fixture.mime_type });
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  attachmentInput.files = dataTransfer.files;
  attachmentInput.dispatchEvent(new Event('change', { bubbles: true }));

  let body = '';
  let hasImageQueued = false;
  let hasVlModel = false;
  for (let i = 0; i < 60; i += 1) {
    await sleep(1000);
    body = document.body.innerText;
    hasImageQueued = body.includes(fixture.name) && body.includes('Image uploaded. It will be sent as visual input when the current model is multimodal');
    hasVlModel = body.includes('Qwen3-VL-8B-Instruct');
    if (hasImageQueued && hasVlModel) {
      break;
    }
  }

  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(
    textarea,
    'Look at the uploaded image and answer in one short sentence that starts with "VisionSummary:". State the dominant color only.',
  );
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(300);

  const buttons = Array.from(document.querySelectorAll('button'));
  const sendButton = buttons[buttons.length - 1];
  if (!sendButton || sendButton.disabled) {
    return {
      ok: false,
      reason: 'send button unavailable after image upload',
      hasImageQueued,
      hasVlModel,
      bodySample: document.body.innerText.slice(0, 2200),
    };
  }
  sendButton.click();

  let deliveryBadge = '';
  for (let i = 0; i < 180; i += 1) {
    await sleep(1000);
    body = document.body.innerText;
    const hasVisionSummary =
      body.includes(fixture.summary_token)
      && /\b(red|reddish)\b/i.test(body);
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (hasVisionSummary) {
      return {
        ok: true,
        hasImageQueued,
        hasVlModel,
        hasVisionSummary,
        deliveryBadge,
        bodySample: body.slice(0, 2800),
      };
    }
    if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
      return {
        ok: false,
        reason: `delivery ${deliveryBadge}`,
        hasImageQueued,
        hasVlModel,
        bodySample: body.slice(0, 2800),
      };
    }
  }

  return {
    ok: false,
    reason: 'timed out waiting for VL image understanding result',
    hasImageQueued,
    hasVlModel,
    deliveryBadge,
    bodySample: document.body.innerText.slice(0, 2800),
  };
})()
"""
        image_script = image_script.replace("__FIXTURE_JSON__", json.dumps(image_fixture_payload, ensure_ascii=True))
        image_result = await session.eval(
            image_script,
            timeout_seconds=CDP_VISION_TIMEOUT_SECONDS,
        )
        results.append(SmokeCheckResult("vl_image_understanding_chat", bool(image_result.get("ok")), image_result))

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(r"""
(() => {
  window.localStorage.removeItem('mcp_chat_current_session');
  window.localStorage.removeItem('mcp_chat_client_id');
  window.sessionStorage.clear();
  return true;
})()
""")
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)
        direct_tool = await session.eval(r"""
(async () => {
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return { ok: false, reason: 'textarea missing' };
  }
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(textarea, '@filesystem.list_allowed_directories');
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 500));
  let buttons = Array.from(document.querySelectorAll('button'));
  const sendButton = buttons[buttons.length - 1];
  if (!sendButton || sendButton.disabled) {
    return { ok: false, reason: 'run tool button unavailable', buttonCount: buttons.length };
  }
  sendButton.click();
  await new Promise((resolve) => setTimeout(resolve, 800));
  buttons = Array.from(document.querySelectorAll('button'));
  const confirmButton = buttons[buttons.length - 1];
  const bodyBeforeConfirm = document.body.innerText;
  if (!confirmButton || !bodyBeforeConfirm.includes('list_allowed_directories')) {
    return { ok: false, reason: 'confirm dialog missing', bodySample: bodyBeforeConfirm.slice(0, 1400) };
  }
  confirmButton.click();
  let body = '';
  let deliveryBadge = '';
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    body = document.body.innerText;
    deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
      .map((el) => (el.innerText || '').trim())
      .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
    if (
      body.includes('Tool call')
      && body.includes('filesystem.list_allowed_directories')
    ) {
      break;
    }
  }
  const hasToolResult =
    body.includes('Tool call')
    && body.includes('filesystem.list_allowed_directories');
  const hasDirectory = body.includes('D:\\\\mirror_mcp') || body.includes('D:\\mirror_mcp');
  const hasPendingOnly = body.includes('pending queue') && !hasToolResult;
  return {
    ok: hasToolResult && hasDirectory && !body.includes('Tool name is required'),
    hasToolResult,
    hasDirectory,
    hasPendingOnly,
    deliveryBadge,
    bodySample: body.slice(0, 2200),
  };
})()
""", timeout_seconds=CDP_LONG_TIMEOUT_SECONDS)
        results.append(SmokeCheckResult("direct_tool_call", bool(direct_tool.get("ok")), direct_tool))

        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await session.eval(_full_frontend_reset_script('Qwen/Qwen3-8B'))
        await session.call("Page.navigate", {"url": FRONTEND_URL})
        await asyncio.sleep(2)
        await _wait_for_app_ready(session)
        await _wait_for_realtime_ready(session)
        multi_turn = await session.eval(r"""
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const setTextarea = (textarea, text) => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, text);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const clickSend = () => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const sendButton = buttons[buttons.length - 1];
    if (!sendButton || sendButton.disabled) {
      return false;
    }
    sendButton.click();
    return true;
  };
  const waitFor = async (predicate, timeoutSeconds = 170) => {
    let body = '';
    let deliveryBadge = '';
    for (let i = 0; i < timeoutSeconds; i += 1) {
      await sleep(1000);
      body = document.body.innerText;
      deliveryBadge = Array.from(document.querySelectorAll('span,div,button'))
        .map((el) => (el.innerText || '').trim())
        .find((text) => text === 'sent' || text === 'failed' || text === 'blocked') || '';
      if (predicate(body, deliveryBadge)) {
        return { ok: true, body, deliveryBadge };
      }
      if (deliveryBadge === 'failed' || deliveryBadge === 'blocked') {
        return { ok: false, body, deliveryBadge, reason: `delivery ${deliveryBadge}` };
      }
    }
    return { ok: false, body: document.body.innerText, deliveryBadge, reason: 'timeout' };
  };

  let body = '';
  for (let i = 0; i < 30; i += 1) {
    body = document.body.innerText;
    if (body.includes('Realtime connected') && document.querySelector('textarea')) {
      break;
    }
    await sleep(1000);
  }
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return { ok: false, reason: 'textarea missing', bodySample: document.body.innerText.slice(0, 2000) };
  }

  setTextarea(
    textarea,
    'Please read D:\\\\mirror_mcp\\\\artifacts\\\\manual_test\\\\notes.txt with the appropriate filesystem tool. Then answer one sentence starting with "FirstTurnSummary:" and include the phrase "browser smoke".',
  );
  await sleep(300);
  if (!clickSend()) {
    return { ok: false, reason: 'first send unavailable', bodySample: document.body.innerText.slice(0, 2200) };
  }
  const first = await waitFor((text) => (
    text.includes('FirstTurnSummary:')
    && text.includes('browser smoke')
    && text.includes('Tool call')
    && (
      text.includes('filesystem.read_text_file')
      || text.includes('filesystem.read_file')
    )
  ));
  if (!first.ok) {
    return {
      ok: false,
      phase: 'first_turn',
      reason: first.reason,
      deliveryBadge: first.deliveryBadge,
      bodySample: first.body.slice(0, 3200),
    };
  }

  setTextarea(
    textarea,
    'Based only on the previous turn, answer one sentence starting with "SecondTurnSummary:" and tell me what phrase I asked you to include. Do not call an external tool unless truly necessary.',
  );
  await sleep(300);
  if (!clickSend()) {
    return { ok: false, reason: 'second send unavailable', bodySample: document.body.innerText.slice(0, 3200) };
  }
  const second = await waitFor((text) => {
    const hasSecond = text.includes('SecondTurnSummary:') && text.includes('browser smoke');
    if (!hasSecond) {
      return false;
    }
    const secondIndex = text.lastIndexOf('SecondTurnSummary:');
    const secondTail = text.slice(secondIndex);
    return !secondTail.includes('Tool call');
  });
  const fullBody = second.body || document.body.innerText;
  const secondIndex = fullBody.lastIndexOf('SecondTurnSummary:');
  const secondTail = secondIndex >= 0 ? fullBody.slice(secondIndex) : '';
  return {
    ok: Boolean(second.ok),
    firstTurnOk: true,
    secondTurnOk: Boolean(second.ok),
    secondTurnUsedTool: secondTail.includes('Tool call'),
    deliveryBadge: second.deliveryBadge,
    bodySample: fullBody.slice(0, 3600),
  };
})()
""", timeout_seconds=CDP_MODEL_TIMEOUT_SECONDS * 2)
        results.append(SmokeCheckResult("multi_turn_followup_no_unneeded_tool", bool(multi_turn.get("ok")), multi_turn))

    return results


def main() -> int:
    _wait_for_url_json(BACKEND_HEALTH_URL, timeout_seconds=20.0)
    auto_tool_routing = _post_json(BACKEND_AUTO_TOOL_ROUTING_URL, {"mode": "memory_plane_plus_fallback"})
    if str(auto_tool_routing.get("mode")) != "memory_plane_plus_fallback":
        raise RuntimeError(
            "Failed to set backend auto tool routing to memory_plane_plus_fallback: "
            + json.dumps(auto_tool_routing, ensure_ascii=True)
        )
    sandbox = _begin_regression_sandbox()
    sandbox_id = str(sandbox.get("sandbox_id", "")).strip()
    if not sandbox_id:
        raise RuntimeError(f"Failed to create regression sandbox: {json.dumps(sandbox, ensure_ascii=True)}")
    process = _start_browser()
    try:
        results = asyncio.run(_run_smoke())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        _restore_regression_sandbox(sandbox_id)

    all_ok = True
    print("=" * 68)
    print("MCP Mirror Browser Runtime Smoke Check")
    print("=" * 68)
    print(json.dumps({"sandbox_id": sandbox_id}, ensure_ascii=False, indent=2))
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}")
        print(json.dumps(result.details, ensure_ascii=False, indent=2))
        if not result.ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
