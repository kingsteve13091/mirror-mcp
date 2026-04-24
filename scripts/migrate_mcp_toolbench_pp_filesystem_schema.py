"""Migrate MCPToolBench++ filesystem single-call data to current official MCP schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.adapters.mcp_toolbench_pp_filesystem_adapter import (  # noqa: E402
    write_mcp_toolbench_pp_filesystem_official_schema,
)


def main() -> None:
    meta = write_mcp_toolbench_pp_filesystem_official_schema()
    print(json.dumps({
        "ok": True,
        "source": meta["source_path"],
        "full_cases": meta["total_official_cases"],
        "read_only_cases": meta["total_readonly_cases"],
        "mutating_cases": meta["total_mutating_cases"],
        "outputs": meta["outputs"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
