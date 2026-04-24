"""
Check dataset availability and basic integrity for TEM experiments.

Output:
- datasets/external/dataset_check_report.json
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
EXTERNAL = DATASETS / "external"
REPORT_PATH = EXTERNAL / "dataset_check_report.json"


REQUIRED_FILES = {
    "tem_toolbench_v2": [
        "datasets/tem_toolbench_v2/tem_toolbench_v2.jsonl",
        "datasets/tem_toolbench_v2/tem_toolbench_v2_train.jsonl",
        "datasets/tem_toolbench_v2/tem_toolbench_v2_dev.jsonl",
        "datasets/tem_toolbench_v2/tem_toolbench_v2_test.jsonl",
        "datasets/tem_toolbench_v2/tem_toolbench_v2_meta.json",
    ],
    "longmemeval": [
        "datasets/external/longmemeval/README.md",
        "datasets/external/longmemeval/longmemeval_s_cleaned.json",
        "datasets/external/longmemeval/longmemeval_m_cleaned.json",
    ],
    "locomo": [
        "datasets/external/locomo/README.MD",
        "datasets/external/locomo/data/locomo10.json",
    ],
    "halumem": [
        "datasets/external/halumem/README.md",
        "datasets/external/halumem/eval/README.md",
        "datasets/external/halumem/data/stage5_1_dialogue_generation.jsonl",
    ],
    "goodai_ltm_benchmark": [
        "datasets/external/goodai_ltm_benchmark/README.md",
        "datasets/external/goodai_ltm_benchmark/datasets/README.md",
        "datasets/external/goodai_ltm_benchmark/configurations/published_benchmarks/benchmark-v3-1k.yml",
    ],
    "bfcl": [
        "datasets/external/bfcl/README.md",
        "datasets/external/bfcl/BFCL_v3_simple.json",
        "datasets/external/bfcl/BFCL_v3_parallel.json",
        "datasets/external/bfcl/BFCL_v3_multi_turn_base.json",
        "datasets/external/bfcl/BFCL_v3_multi_turn_composite.json",
        "datasets/external/bfcl/BFCL_v3_exec_simple.json",
        "datasets/external/bfcl/BFCL_v3_exec_parallel.json",
    ],
    "tau_bench": [
        "datasets/external/tau_bench/README.md",
    ],
    "mcp_toolbench_pp": [
        "datasets/external/mcp_toolbench_pp/README.md",
        "datasets/external/mcp_toolbench_pp/data/file_system/filesystem_0723_single.json",
    ],
    "mcpbench": [
        "datasets/external/mcpbench/README.md",
        "datasets/external/mcpbench/langProBe/WebSearch/data/websearch_300.jsonl",
    ],
    "mcpmark": [
        "datasets/external/mcpmark/README.md",
        "datasets/external/mcpmark/tasks/filesystem/easy/file_context/pattern_matching/meta.json",
    ],
}


def _status(path_str: str) -> dict[str, object]:
    p = ROOT / path_str
    if not p.exists():
        return {"path": path_str, "exists": False, "size": 0}
    size = p.stat().st_size
    return {"path": path_str, "exists": size > 0, "size": size}


def main() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, object]] = {}
    all_ok = True

    for group, files in REQUIRED_FILES.items():
        items = [_status(fp) for fp in files]
        missing = [x for x in items if not x["exists"]]
        report[group] = {
            "required": len(files),
            "available": len(files) - len(missing),
            "ok": len(missing) == 0,
            "files": items,
        }
        if missing:
            all_ok = False

    summary = {
        "all_ok": all_ok,
        "groups": report,
    }

    REPORT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
