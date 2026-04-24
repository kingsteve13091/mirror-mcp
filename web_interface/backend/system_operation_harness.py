# -*- coding: utf-8 -*-

"""System Operation Plane for MCP Mirror.

This harness intentionally lives beside MCP Tool Plane instead of inside the
MCP server registry.  It gives the agent controlled access to workspace-scoped
system actions such as terminal commands, process inspection, browser smoke,
test execution, and log reads.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_workspace_root(value: str) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        path = Path(text).resolve()
    except Exception:
        return None
    if not path.exists() or not path.is_dir():
        return None
    return path


def _truncate_text(value: str, *, max_chars: int = 6000) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]..."


class SystemOperationHarness:
    def __init__(self, *, project_root: Path, logs_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.logs_root = Path(logs_root).resolve()
        self.allowed_log_roots = {
            self.logs_root,
            self.project_root / "web_interface" / "backend",
        }

    def capability_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "action_type": "terminal_command",
                "title": "Terminal command",
                "description": "Run a workspace-scoped read or diagnostic shell command with confirmation.",
                "risk_level": "high",
                "requires_confirmation": True,
            },
            {
                "action_type": "process_control",
                "title": "Process control",
                "description": "Inspect or restart MCP Mirror services in a controlled way.",
                "risk_level": "high",
                "requires_confirmation": True,
            },
            {
                "action_type": "test_runner",
                "title": "Test runner",
                "description": "Run a known regression/test command inside the workspace.",
                "risk_level": "medium",
                "requires_confirmation": False,
            },
            {
                "action_type": "log_read",
                "title": "Log read",
                "description": "Read recent backend/frontend log snippets from allowed project logs.",
                "risk_level": "low",
                "requires_confirmation": False,
            },
            {
                "action_type": "browser_smoke",
                "title": "Browser smoke",
                "description": "Execute an existing browser regression probe script.",
                "risk_level": "medium",
                "requires_confirmation": False,
            },
            {
                "action_type": "workspace_file_op",
                "title": "Workspace file operation",
                "description": "Read or create a file within the workspace with explicit confirmation for writes.",
                "risk_level": "high",
                "requires_confirmation": True,
            },
        ]

    async def execute(
        self,
        *,
        action_type: str,
        payload: Dict[str, Any],
        workspace_root: str = "",
    ) -> Dict[str, Any]:
        normalized = str(action_type or "").strip().lower()
        if normalized == "terminal_command":
            return await self._run_terminal_command(payload, workspace_root=workspace_root)
        if normalized == "process_control":
            return await self._run_process_control(payload)
        if normalized == "test_runner":
            return await self._run_test_runner(payload, workspace_root=workspace_root)
        if normalized == "log_read":
            return await self._run_log_read(payload)
        if normalized == "browser_smoke":
            return await self._run_browser_smoke(payload, workspace_root=workspace_root)
        if normalized == "workspace_file_op":
            return await self._run_workspace_file_op(payload, workspace_root=workspace_root)
        raise ValueError(f"Unsupported system operation action: {action_type}")

    async def _launch_detached_script(
        self,
        *,
        script_relative_path: str,
        delay_seconds: int,
        operation: str,
    ) -> Dict[str, Any]:
        root_text = str(self.project_root).replace("'", "''")
        script_text = script_relative_path.replace("/", "\\").replace("'", "''")
        inner_command = (
            f"Start-Sleep -Seconds {max(0, int(delay_seconds))}; "
            f"Set-Location -LiteralPath '{root_text}'; "
            f"& '.\\{script_text}'"
        )
        escaped_inner = inner_command.replace("'", "''")
        launcher_command = (
            "Start-Process powershell "
            "-WindowStyle Hidden "
            f"-WorkingDirectory '{root_text}' "
            f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command','{escaped_inner}'"
        )
        process = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            launcher_command,
            cwd=str(self.project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        return {
            "success": process.returncode == 0,
            "action_type": "process_control",
            "operation": operation,
            "scheduled": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": _truncate_text(stdout.decode("utf-8", errors="replace")),
            "stderr": _truncate_text(stderr.decode("utf-8", errors="replace")),
            "timestamp": utc_now(),
        }

    async def _run_terminal_command(self, payload: Dict[str, Any], *, workspace_root: str) -> Dict[str, Any]:
        command = str(payload.get("command", "") or "").strip()
        working_directory = str(payload.get("working_directory", "") or "").strip()
        timeout_ms = int(payload.get("timeout_ms", 20000) or 20000)
        root = _safe_workspace_root(workspace_root) or self.project_root
        workdir = Path(working_directory).resolve() if working_directory else root
        if not str(workdir).lower().startswith(str(root).lower()):
            raise ValueError("Working directory is outside the active workspace root.")
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_ms / 1000)
            timed_out = False
        except asyncio.TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            timed_out = True
        return {
            "success": process.returncode == 0 and not timed_out,
            "action_type": "terminal_command",
            "command": command,
            "working_directory": str(workdir),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": _truncate_text(stdout.decode("utf-8", errors="replace")),
            "stderr": _truncate_text(stderr.decode("utf-8", errors="replace")),
            "timestamp": utc_now(),
        }

    async def _run_process_control(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        operation = str(payload.get("operation", "") or "status").strip().lower()
        if operation == "status":
            command = "Get-NetTCPConnection -State Listen -LocalPort 3000,8000,9001 -ErrorAction SilentlyContinue | Select-Object LocalPort,OwningProcess,State | Sort-Object LocalPort | ConvertTo-Json"
        elif operation == "restart_backend":
            return await self._launch_detached_script(
                script_relative_path="scripts\\start_backend.ps1",
                delay_seconds=3,
                operation=operation,
            )
        elif operation == "restart_frontend":
            return await self._launch_detached_script(
                script_relative_path="scripts\\start_frontend.ps1",
                delay_seconds=2,
                operation=operation,
            )
        else:
            raise ValueError(f"Unsupported process_control operation: {operation}")
        return await self._run_terminal_command(
            {
                "command": command,
                "working_directory": str(self.project_root),
                "timeout_ms": 20000 if operation == "status" else 35000,
            },
            workspace_root=str(self.project_root),
        )

    async def _run_test_runner(self, payload: Dict[str, Any], *, workspace_root: str) -> Dict[str, Any]:
        profile = str(payload.get("profile", "") or "smoke").strip().lower()
        root = _safe_workspace_root(workspace_root) or self.project_root
        if profile == "frontend_ci":
            command = "npm run test:ci"
            workdir = self.project_root / "web_interface" / "frontend"
        elif profile == "backend_compile":
            command = "python -m py_compile web_interface\\backend\\app.py"
            workdir = self.project_root
        elif profile == "mcp_onboarding_gate":
            command = "powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\run_mcp_onboarding_gate.ps1"
            workdir = self.project_root
        else:
            command = str(payload.get("command", "") or "").strip()
            workdir = root
        return await self._run_terminal_command(
            {
                "command": command,
                "working_directory": str(workdir),
                "timeout_ms": int(payload.get("timeout_ms", 60000) or 60000),
            },
            workspace_root=str(workdir),
        )

    async def _run_log_read(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        relative_path = str(payload.get("path", "") or "").strip()
        tail = max(1, min(int(payload.get("tail", 120) or 120), 800))
        target = (self.project_root / relative_path).resolve() if relative_path else self.logs_root / "backend_restart_check.out.log"
        if not any(str(target).lower().startswith(str(root).lower()) for root in self.allowed_log_roots):
            raise ValueError("Requested log path is outside allowed log roots.")
        if not target.exists():
            return {
                "success": False,
                "action_type": "log_read",
                "path": str(target),
                "error": "Log file does not exist.",
                "timestamp": utc_now(),
            }
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        snippet = "\n".join(lines[-tail:])
        return {
            "success": True,
            "action_type": "log_read",
            "path": str(target),
            "tail": tail,
            "content": _truncate_text(snippet),
            "timestamp": utc_now(),
        }

    async def _run_browser_smoke(self, payload: Dict[str, Any], *, workspace_root: str) -> Dict[str, Any]:
        stage = str(payload.get("stage", "") or "").strip()
        command = "python scripts\\browser_tool_chain_probe.py"
        if stage:
            command += f" --stage {stage}"
        return await self._run_terminal_command(
            {
                "command": command,
                "working_directory": str(self.project_root),
                "timeout_ms": int(payload.get("timeout_ms", 180000) or 180000),
            },
            workspace_root=str(self.project_root),
        )

    async def _run_workspace_file_op(self, payload: Dict[str, Any], *, workspace_root: str) -> Dict[str, Any]:
        root = _safe_workspace_root(workspace_root) or self.project_root
        operation = str(payload.get("operation", "") or "read").strip().lower()
        path_text = str(payload.get("path", "") or "").strip()
        if not path_text:
            raise ValueError("Workspace file operation requires a path.")
        target = Path(path_text)
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        if not str(target).lower().startswith(str(root).lower()):
            raise ValueError("Workspace file operation path is outside the active workspace root.")
        if operation == "read":
            content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
            return {
                "success": target.exists(),
                "action_type": "workspace_file_op",
                "operation": "read",
                "path": str(target),
                "content": _truncate_text(content),
                "timestamp": utc_now(),
            }
        if operation == "write":
            content = str(payload.get("content", "") or "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {
                "success": True,
                "action_type": "workspace_file_op",
                "operation": "write",
                "path": str(target),
                "bytes_written": len(content.encode("utf-8")),
                "timestamp": utc_now(),
            }
        raise ValueError(f"Unsupported workspace_file_op operation: {operation}")
