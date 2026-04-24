#!/usr/bin/env python3
"""
Strict runtime audit for official MCP server wiring.

This script verifies two things:
1. Config contract: the 4 non-CDAR servers must remain official stdio servers.
2. Runtime contract: backend /api/mcp/servers and /api/mcp/tools must expose the
   expected official connection types and tool names.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server_contract import build_runtime_audit_report

CONFIG_PATH = ROOT / "mcp_config.json"
OUT_PATH = ROOT / "experiments" / "results" / "official_mcp_runtime_audit.json"
BACKEND = "http://127.0.0.1:8000"


def http_json(url: str) -> dict:
    with urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    runtime_servers = http_json(f"{BACKEND}/api/mcp/servers")
    runtime_tools = http_json(f"{BACKEND}/api/mcp/tools")
    report = build_runtime_audit_report(config, runtime_servers, runtime_tools)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
