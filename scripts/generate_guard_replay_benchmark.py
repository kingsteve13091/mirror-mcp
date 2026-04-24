#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate a reproducible guard-replay benchmark from TEM-ToolBench-v2.

Research goal:
- test whether learned guards can stop repeated identical failures
- test whether those guards avoid blocking near-neighbor successful calls

This script is intentionally rule-based and deterministic. It does not hand-pick
episodes. Families are selected by fixed support thresholds over the source
dataset and matched with same-tool successful controls.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from path_portability import MCP_MIRROR_ROOT_TOKEN, encode_portable_paths

DATASET_DIR = ROOT / "datasets" / "tem_toolbench_v2"
SOURCE_DATASET = DATASET_DIR / "tem_toolbench_v2.jsonl"
OUTPUT_DATASET = DATASET_DIR / "tem_guard_replay_benchmark.jsonl"
OUTPUT_META = DATASET_DIR / "tem_guard_replay_benchmark_meta.json"
PARAMS_PATH = ROOT / "artifacts" / "algorithm_params.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def build_schema(arguments: dict[str, Any]) -> dict[str, str]:
    schema: dict[str, str] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            schema[key] = "str"
        elif isinstance(value, bool):
            schema[key] = "bool"
        elif isinstance(value, int):
            schema[key] = "int"
        elif isinstance(value, float):
            schema[key] = "float"
        elif isinstance(value, list):
            schema[key] = "list"
        elif isinstance(value, dict):
            schema[key] = "dict"
        else:
            schema[key] = type(value).__name__
    return schema


def schema_similarity(a: dict[str, str], b: dict[str, str]) -> float:
    if not a and not b:
        return 1.0
    keys_a = set(a)
    keys_b = set(b)
    union = keys_a | keys_b
    if not union:
        return 0.0
    overlap = keys_a & keys_b
    jaccard = len(overlap) / len(union)
    if not overlap:
        return jaccard
    type_match = sum(1 for key in overlap if a.get(key) == b.get(key)) / len(overlap)
    return (jaccard + type_match) / 2.0


def clone_step(step: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "tool": step.get("tool", ""),
        "server": step.get("server", ""),
        "arguments": encode_portable_paths(dict(step.get("arguments", {})), project_root=ROOT),
        "should_succeed": bool(step.get("should_succeed", True)),
        "error_type": step.get("error_type", ""),
        "error_message": step.get("error_message", ""),
        "expect_contains": encode_portable_paths(list(step.get("expect_contains", []) or []), project_root=ROOT),
        "expect_not_contains": encode_portable_paths(list(step.get("expect_not_contains", []) or []), project_root=ROOT),
        "role": role,
    }


def load_tem_params() -> dict[str, Any]:
    raw = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    return raw["tool_execution_memory"]


def failure_posterior_after_failures(prior_alpha: float, prior_beta: float, failures: int, danger_threshold: float) -> float:
    # For the current calibrated system beta stays at prior under repeated failures
    # without any confirming successes. The current calibration uses danger=0.5 and
    # prior_beta=1.0, so P(failure) reduces to 1 - I_x(alpha, beta).
    # We keep the benchmark generator explicit about this assumption to avoid hidden magic.
    if abs(prior_beta - 1.0) > 1e-12 or abs(danger_threshold - 0.5) > 1e-12:
        raise RuntimeError(
            "Guard replay benchmark currently supports the calibrated setting "
            "prior_beta=1.0 and danger_threshold=0.5 only. "
            "Regenerate logic before using new calibration values."
        )
    alpha = prior_alpha + failures
    return 1.0 - (danger_threshold ** alpha)


def observed_failures_needed_for_block(params: dict[str, Any]) -> int:
    prior_alpha = float(params["BAYESIAN_PRIOR_ALPHA"])
    prior_beta = float(params["BAYESIAN_PRIOR_BETA"])
    block_conf = float(params["BAYESIAN_BLOCK_CONFIDENCE"])
    danger_threshold = float(params["DANGER_THRESHOLD"])
    for failures in range(1, 20):
        posterior = failure_posterior_after_failures(prior_alpha, prior_beta, failures, danger_threshold)
        if posterior > block_conf:
            return failures
    raise RuntimeError("Could not find failure count needed for block under current calibration")


def main() -> None:
    rows = load_jsonl(SOURCE_DATASET)
    params = load_tem_params()
    failures_needed_for_block = observed_failures_needed_for_block(params)
    replay_attempts = failures_needed_for_block + 1

    allowed_servers = {"filesystem", "memory", "sequential_thinking"}
    excluded_servers = {"fetch", "cdar_mcp"}
    min_failure_support = 30
    success_controls_per_family = 2

    failures: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    successes: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)

    for episode in rows:
        for step in episode.get("steps", []):
            server = str(step.get("server", ""))
            tool = str(step.get("tool", ""))
            if server in excluded_servers or server not in allowed_servers:
                continue
            if step.get("should_succeed", True):
                successes[(server, tool)].append((episode, step))
            else:
                key = (
                    server,
                    tool,
                    str(step.get("error_type", "")),
                    str(step.get("error_message", "")),
                )
                failures[key].append((episode, step))

    selected_rows: list[dict[str, Any]] = []
    family_stats: list[dict[str, Any]] = []
    ranked_families = sorted(failures.items(), key=lambda item: len(item[1]), reverse=True)

    family_index = 0
    for family_key, family_failures in ranked_families:
        server, tool, error_type, error_message = family_key
        tool_successes = successes.get((server, tool), [])
        if len(family_failures) < min_failure_support or len(tool_successes) < success_controls_per_family:
            continue

        source_failure_episode, source_failure_step = family_failures[0]
        failure_schema = build_schema(source_failure_step.get("arguments", {}))

        scored_controls: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
        for success_episode, success_step in tool_successes:
            score = schema_similarity(failure_schema, build_schema(success_step.get("arguments", {})))
            scored_controls.append((score, success_episode.get("id", ""), success_episode, success_step))
        scored_controls.sort(key=lambda item: (item[0], item[1]), reverse=True)

        family_id = f"family_{family_index:03d}"
        family_index += 1

        replay_steps: list[dict[str, Any]] = []
        for attempt in range(1, replay_attempts + 1):
            role = "target_failure_replay" if attempt == replay_attempts else "warmup_failure"
            replay_steps.append(clone_step(source_failure_step, role=role))

        selected_rows.append(
            {
                "id": f"{family_id}_replay",
                "task": f"Replay repeated failure for {server}/{tool} -> {error_type}",
                "category": "guard_replay_failure",
                "difficulty": "hard",
                "tools_available": [tool],
                "expected_success": False,
                "expected_failure_cause": error_type,
                "memory_focus": ["unsafe_action_blocking", "failure_replay_guarding"],
                "benchmark_design": {
                    "family_id": family_id,
                    "replay_attempts": replay_attempts,
                    "failures_needed_for_block": failures_needed_for_block,
                    "target_replay_index": replay_attempts,
                },
                "benchmark_family": {
                    "server": server,
                    "tool": tool,
                    "error_type": error_type,
                    "error_message": error_message,
                    "source_episode": source_failure_episode.get("id", ""),
                },
                "steps": replay_steps,
            }
        )

        used_success_episode_ids: set[str] = set()
        controls_added = 0
        for _, _, success_episode, success_step in scored_controls:
            success_episode_id = success_episode.get("id", "")
            if success_episode_id in used_success_episode_ids:
                continue
            used_success_episode_ids.add(success_episode_id)
            controls_added += 1
            selected_rows.append(
                {
                    "id": f"{family_id}_control_{controls_added:02d}",
                    "task": f"Near-neighbor success control for {server}/{tool}",
                    "category": "guard_replay_control",
                    "difficulty": success_episode.get("difficulty", "medium"),
                    "tools_available": [tool],
                    "expected_success": True,
                    "memory_focus": ["false_block_resistance", "schema_disambiguation"],
                    "benchmark_design": {
                        "family_id": family_id,
                        "replay_attempts": replay_attempts,
                        "failures_needed_for_block": failures_needed_for_block,
                        "target_replay_index": replay_attempts,
                    },
                    "benchmark_family": {
                        "server": server,
                        "tool": tool,
                        "paired_failure_error_type": error_type,
                        "paired_failure_error_message": error_message,
                        "source_episode": success_episode_id,
                    },
                    "steps": [clone_step(success_step, role="success_control")],
                }
            )
            if controls_added >= success_controls_per_family:
                break

        if controls_added < success_controls_per_family:
            # Drop incomplete family to preserve fixed design balance.
            selected_rows = selected_rows[: -(1 + controls_added)]
            family_index -= 1
            continue

        family_stats.append(
            {
                "family_id": family_id,
                "server": server,
                "tool": tool,
                "error_type": error_type,
                "error_message": error_message,
                "failure_support": len(family_failures),
                "success_support": len(tool_successes),
            }
        )

    OUTPUT_DATASET.write_text(
        "\n".join(json.dumps(encode_portable_paths(row, project_root=ROOT), ensure_ascii=False) for row in selected_rows) + "\n",
        encoding="utf-8",
    )

    meta = {
        "name": "TEM-Guard-Replay-Benchmark",
        "version": "1.1",
        "source_dataset": "TEM-ToolBench-v2",
        "source_records": len(rows),
        "selection_rule": {
            "allowed_servers": sorted(allowed_servers),
            "excluded_servers": sorted(excluded_servers),
            "min_failure_support": min_failure_support,
            "success_controls_per_family": success_controls_per_family,
            "family_sort": "descending failure support",
            "manual_cherry_pick": False,
            "path_portability_root_token": MCP_MIRROR_ROOT_TOKEN,
        },
        "guard_calibration": {
            "prior_alpha": params["BAYESIAN_PRIOR_ALPHA"],
            "prior_beta": params["BAYESIAN_PRIOR_BETA"],
            "danger_threshold": params["DANGER_THRESHOLD"],
            "block_confidence": params["BAYESIAN_BLOCK_CONFIDENCE"],
            "failures_needed_for_block": failures_needed_for_block,
            "replay_attempts": replay_attempts,
        },
        "episodes": len(selected_rows),
        "families": len(family_stats),
        "family_stats": family_stats,
        "research_purpose": [
            "Measure whether learned guards can prevent repeated identical failing tool calls.",
            "Measure false-block resistance on same-tool near-neighbor successful calls.",
            "Provide a deterministic guard stress test that is independent of open-ended planning quality.",
        ],
    }
    OUTPUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "episodes": len(selected_rows),
                "families": len(family_stats),
                "output_dataset": str(OUTPUT_DATASET),
                "output_meta": str(OUTPUT_META),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
