"""
Generate TEM-ToolBench-v1 synthetic dataset for tool-execution-memory experiments.

Output:
- datasets/tem_toolbench_v1/tem_toolbench_v1.jsonl
- datasets/tem_toolbench_v1/tem_toolbench_v1_meta.json
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "datasets" / "tem_toolbench_v1"
OUT_JSONL = OUT_DIR / "tem_toolbench_v1.jsonl"
OUT_META = OUT_DIR / "tem_toolbench_v1_meta.json"


@dataclass
class StepTemplate:
    tool: str
    server: str
    args: dict[str, Any]


@dataclass
class EpisodeTemplate:
    category: str
    difficulty: str
    tools_available: list[str]
    success_steps: list[StepTemplate]
    fail_step: StepTemplate
    fail_error_type: str
    fail_error_message: str


def _templates() -> list[EpisodeTemplate]:
    return [
        EpisodeTemplate(
            category="file_ops",
            difficulty="easy",
            tools_available=["list_dir", "read_file", "write_file"],
            success_steps=[
                StepTemplate("list_dir", "fs_srv", {"path": "/project/reports"}),
                StepTemplate("read_file", "fs_srv", {"path": "/project/reports/{name}.txt"}),
            ],
            fail_step=StepTemplate("read_file", "fs_srv", {"path": "/project/secret/{name}.txt"}),
            fail_error_type="PermissionError",
            fail_error_message="permission denied",
        ),
        EpisodeTemplate(
            category="network_api",
            difficulty="medium",
            tools_available=["fetch_url", "http_request", "parse_json"],
            success_steps=[
                StepTemplate("fetch_url", "net_srv", {"url": "https://api.example.com/status?id={id}"}),
                StepTemplate("parse_json", "data_srv", {"schema": "status"}),
            ],
            fail_step=StepTemplate("http_request", "net_srv", {"url": "https://api.example.com/rate_limit?id={id}", "method": "GET"}),
            fail_error_type="HTTPError",
            fail_error_message="429 Too Many Requests",
        ),
        EpisodeTemplate(
            category="data_transform",
            difficulty="medium",
            tools_available=["read_file", "convert_format", "write_file", "resize_image"],
            success_steps=[
                StepTemplate("read_file", "fs_srv", {"path": "/data/input/{name}.csv"}),
                StepTemplate("convert_format", "data_srv", {"from": "csv", "to": "json"}),
                StepTemplate("write_file", "fs_srv", {"path": "/data/output/{name}.json"}),
            ],
            fail_step=StepTemplate("convert_format", "data_srv", {"from": "unknown", "to": "json"}),
            fail_error_type="ValueError",
            fail_error_message="invalid format",
        ),
        EpisodeTemplate(
            category="retrieval_query",
            difficulty="hard",
            tools_available=["query_db", "search_docs", "write_file"],
            success_steps=[
                StepTemplate("query_db", "db_srv", {"sql": "SELECT * FROM orders WHERE id='{id}'"}),
                StepTemplate("write_file", "fs_srv", {"path": "/tmp/order_{id}.json"}),
            ],
            fail_step=StepTemplate("query_db", "db_srv", {"sql": "SELECT * FROM missing_table WHERE id='{id}'"}),
            fail_error_type="ServerError",
            fail_error_message="relation does not exist",
        ),
        EpisodeTemplate(
            category="multimodal_reasoning",
            difficulty="hard",
            tools_available=["analyze_image", "cdar_compositional_decomposed_adaptive_reasoning"],
            success_steps=[
                StepTemplate("analyze_image", "vision_srv", {"image_path": "/images/{name}.png"}),
                StepTemplate(
                    "cdar_compositional_decomposed_adaptive_reasoning",
                    "cdar_mcp",
                    {"query": "Summarize reasoning chain for sample {id}", "depth": 2},
                ),
            ],
            fail_step=StepTemplate(
                "cdar_compositional_decomposed_adaptive_reasoning",
                "cdar_mcp",
                {"query": "Run tool with invalid profile {id}", "depth": -1},
            ),
            fail_error_type="BusinessError",
            fail_error_message="invalid reasoning depth",
        ),
    ]


def _materialize_step(step: StepTemplate, episode_id: str, index: int) -> dict[str, Any]:
    values = {
        "id": f"{episode_id}_{index}",
        "name": f"sample_{episode_id}_{index}",
    }
    args = {
        k: (v.format(**values) if isinstance(v, str) else v)
        for k, v in step.args.items()
    }
    return {
        "tool": step.tool,
        "server": step.server,
        "arguments": args,
    }


def generate_dataset(total_per_category: int = 20, fail_ratio: float = 0.4, seed: int = 20260410) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    templates = _templates()
    episodes: list[dict[str, Any]] = []

    for t in templates:
        fail_count = int(round(total_per_category * fail_ratio))
        success_count = total_per_category - fail_count

        for i in range(success_count):
            eid = f"{t.category}_s_{i+1:03d}"
            steps = [
                {
                    **_materialize_step(st, eid, idx),
                    "should_succeed": True,
                    "error_type": "",
                    "error_message": "",
                }
                for idx, st in enumerate(t.success_steps, start=1)
            ]
            episodes.append(
                {
                    "id": eid,
                    "task": f"{t.category} success workflow {i+1}",
                    "category": t.category,
                    "difficulty": t.difficulty,
                    "tools_available": t.tools_available,
                    "expected_success": True,
                    "steps": steps,
                }
            )

        for i in range(fail_count):
            eid = f"{t.category}_f_{i+1:03d}"
            prefix = [
                {
                    **_materialize_step(st, eid, idx),
                    "should_succeed": True,
                    "error_type": "",
                    "error_message": "",
                }
                for idx, st in enumerate(t.success_steps[: max(1, len(t.success_steps) - 1)], start=1)
            ]
            failing = {
                **_materialize_step(t.fail_step, eid, len(prefix) + 1),
                "should_succeed": False,
                "error_type": t.fail_error_type,
                "error_message": t.fail_error_message,
            }
            episodes.append(
                {
                    "id": eid,
                    "task": f"{t.category} failure workflow {i+1}",
                    "category": t.category,
                    "difficulty": t.difficulty,
                    "tools_available": t.tools_available,
                    "expected_success": False,
                    "expected_failure_cause": t.fail_error_type,
                    "steps": prefix + [failing],
                }
            )

    rng.shuffle(episodes)
    return episodes


def write_outputs(episodes: list[dict[str, Any]], seed: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for ep in episodes:
            f.write(json.dumps(ep, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {
        "name": "TEM-ToolBench-v1",
        "version": "1.0",
        "seed": seed,
        "total_episodes": len(episodes),
        "categories": {},
        "splits": {
            "success_episodes": sum(1 for e in episodes if e["expected_success"]),
            "failure_episodes": sum(1 for e in episodes if not e["expected_success"]),
        },
        "schema": {
            "fields": [
                "id",
                "task",
                "category",
                "difficulty",
                "tools_available",
                "expected_success",
                "steps",
            ],
            "step_fields": [
                "tool",
                "server",
                "arguments",
                "should_succeed",
                "error_type",
                "error_message",
            ],
        },
    }

    for ep in episodes:
        cat = ep["category"]
        if cat not in summary["categories"]:
            summary["categories"][cat] = {"total": 0, "success": 0, "failure": 0}
        summary["categories"][cat]["total"] += 1
        if ep["expected_success"]:
            summary["categories"][cat]["success"] += 1
        else:
            summary["categories"][cat]["failure"] += 1

    OUT_META.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    seed = 20260410
    episodes = generate_dataset(total_per_category=20, fail_ratio=0.4, seed=seed)
    write_outputs(episodes, seed=seed)
    print(json.dumps({"dataset": str(OUT_JSONL), "meta": str(OUT_META), "episodes": len(episodes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
