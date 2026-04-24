#!/usr/bin/env python3
"""One-click MCP onboarding regression gate.

Runs backend health check, onboarding audit, safe self-tests, and the real
browser smoke. This is intended to be the single command you run after adding
or changing MCP servers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
BACKEND_TOOL_ONBOARDING_AUDIT_URL = "http://127.0.0.1:8000/api/mcp/tool-onboarding-audit"
BACKEND_TOOL_ONBOARDING_RUN_URL = "http://127.0.0.1:8000/api/mcp/tool-onboarding-audit/run"
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def _python_command() -> str:
    return str(PYTHON_EXE) if PYTHON_EXE.exists() else sys.executable or "python"


def _http_json(url: str, timeout_seconds: float = 20.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: float = 45.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _print_section(title: str) -> None:
    print("=" * 72)
    print(title)
    print("=" * 72)


def _run_browser_smoke() -> int:
    command = [_python_command(), str(PROJECT_ROOT / "scripts" / "browser_runtime_smoke.py")]
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    return int(result.returncode)


def main() -> int:
    _print_section("MCP Mirror Onboarding Regression Gate")
    print("Backend:  http://127.0.0.1:8000")
    print("Frontend: http://127.0.0.1:3000")
    print("")

    print("[STEP] Backend health")
    health = _http_json(BACKEND_HEALTH_URL, timeout_seconds=20.0)
    print(json.dumps({
        "status": health.get("status"),
        "mcp_manager": health.get("mcp_manager"),
        "connected_servers": health.get("mcp", {}).get("connected_servers", []),
        "tools_count": health.get("mcp", {}).get("tools_count"),
        "tem_mode": health.get("tem", {}).get("mode"),
        "siliconflow": health.get("providers", {}).get("siliconflow", {}).get("configured"),
        "openrouter": health.get("providers", {}).get("openrouter", {}).get("configured"),
    }, ensure_ascii=False, indent=2))

    print("")
    print("[STEP] Onboarding audit")
    audit = _http_json(BACKEND_TOOL_ONBOARDING_AUDIT_URL, timeout_seconds=45.0)
    print(json.dumps(audit.get("summary", {}), ensure_ascii=False, indent=2))
    if not audit.get("ok", False):
        print("Onboarding audit reported failure.")
        return 1
    if int(audit.get("summary", {}).get("schema_risk_tools", 0) or 0) > 0:
        print("Schema risk tools detected. Fix onboarding warnings before proceeding.")
        return 1

    safe_gate_tools = [
        str(tool.get("tool_key", "")).strip()
        for tool in audit.get("tools", [])
        if isinstance(tool, dict)
        and isinstance(tool.get("self_test"), dict)
        and tool["self_test"].get("safe_to_run")
        and tool["self_test"].get("gate_required")
    ]
    print("")
    print("[STEP] Safe onboarding self-tests")
    print(json.dumps({"safe_gate_tools": safe_gate_tools}, ensure_ascii=False, indent=2))
    if not safe_gate_tools:
        print("No safe gate tools were found. This should not happen for a healthy MCP runtime.")
        return 1

    run_report = _post_json(
        BACKEND_TOOL_ONBOARDING_RUN_URL,
        {
            "tool_keys": safe_gate_tools,
            "execute_safe_only": True,
            "max_tools": len(safe_gate_tools),
        },
        timeout_seconds=90.0,
    )
    print(json.dumps(run_report.get("summary", {}), ensure_ascii=False, indent=2))
    run_summary = run_report.get("summary", {})
    if not run_report.get("ok", False) or int(run_summary.get("failed", 0) or 0) > 0 or int(run_summary.get("gate_failed", 0) or 0) > 0:
        print("Safe onboarding self-tests failed.")
        return 1

    print("")
    print("[STEP] Browser runtime smoke", flush=True)
    smoke_exit = _run_browser_smoke()
    if smoke_exit != 0:
        print("Browser runtime smoke failed.")
        return smoke_exit

    print("")
    print("Onboarding regression gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
