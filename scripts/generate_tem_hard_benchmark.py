#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate TEM-Hard benchmark views from the canonical official-schema TEM-ToolBench-v2.

TEM-Hard is intentionally not a hand-picked "winning" subset. It is a set of
deterministic, auditable views over the existing internal benchmark:

1. recipe_train / recipe_dev / recipe_test
   Hard multi-step success episodes for testing ToolRecipe reuse and retrieval.

2. guard_train_warmup / guard_exact_test / guard_transfer_test /
   guard_success_controls
   Guard stress data for exact repeated failure blocking, transfer limits, and
   false-block resistance.

Important limitation:
The source dataset is still internal and synthetic. TEM-Hard should still be
reported as an internal benchmark, not as an external authoritative benchmark.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from path_portability import MCP_MIRROR_ROOT_TOKEN, encode_portable_paths

SOURCE_DIR = ROOT / "datasets" / "tem_toolbench_v2"
OUT_DIR = ROOT / "datasets" / "tem_hard"
PARAMS_PATH = ROOT / "artifacts" / "algorithm_params.json"
FS_STATE_DIR = SOURCE_DIR / "fs_state"
GENERATED_DIR = FS_STATE_DIR / "generated"
ARCHIVE_LOG_PATH = FS_STATE_DIR / "archive" / "session_log.txt"
CHECKLIST_PATH = FS_STATE_DIR / "checklists" / "review_plan.txt"
PROJECT_NOTES_PATH = FS_STATE_DIR / "projects" / "tem_notes.md"
ALICE_PROFILE_PATH = FS_STATE_DIR / "people" / "alice_profile.txt"

SOURCE_ALL = SOURCE_DIR / "tem_toolbench_v2.jsonl"
SOURCE_SPLITS = {
    "train": SOURCE_DIR / "tem_toolbench_v2_train.jsonl",
    "dev": SOURCE_DIR / "tem_toolbench_v2_dev.jsonl",
    "test": SOURCE_DIR / "tem_toolbench_v2_test.jsonl",
}

OUT_RECIPE_TRAIN = OUT_DIR / "tem_hard_recipe_train.jsonl"
OUT_RECIPE_DEV = OUT_DIR / "tem_hard_recipe_dev.jsonl"
OUT_RECIPE_TEST = OUT_DIR / "tem_hard_recipe_test.jsonl"
OUT_GUARD_TRAIN = OUT_DIR / "tem_hard_guard_train_warmup.jsonl"
OUT_GUARD_EXACT_TEST = OUT_DIR / "tem_hard_guard_exact_test.jsonl"
OUT_GUARD_TRANSFER_TEST = OUT_DIR / "tem_hard_guard_transfer_test.jsonl"
OUT_GUARD_CONTROLS = OUT_DIR / "tem_hard_guard_success_controls.jsonl"
OUT_LIVE_TEST = OUT_DIR / "tem_hard_live_test.jsonl"
OUT_META = OUT_DIR / "tem_hard_meta.json"

SEED = 20260412
STABLE_SERVERS = {"filesystem", "memory", "sequential_thinking"}
EXCLUDED_SERVERS = {"fetch", "cdar_mcp"}
RECIPE_HARD_SCORE_THRESHOLD = 4
GUARD_TRAIN_MIN_SUPPORT = 10
GUARD_TEST_MIN_SUPPORT = 5
GUARD_EXACT_TEST_MAX_PER_FAMILY = 12
GUARD_TRANSFER_TEST_MAX_PER_FAMILY = 12
GUARD_SUCCESS_CONTROLS_PER_FAMILY = 5
TARGETED_HARDENING_SPLIT_COUNTS = {
    "train": 12,
    "dev": 4,
    "test": 8,
}
TARGETED_HARDENING_CATEGORY_OFFSETS = {
    "plan_memory_loop": 8100,
    "plan_memory_filesystem_loop": 8200,
    "plan_filesystem_grounding": 8300,
    "memory_chain_grounding": 8400,
}
TARGETED_HARDENING_SPLIT_OFFSETS = {
    "train": 0,
    "dev": 100,
    "test": 200,
}

HARD_FOCUS = {
    "cross_tool_linking",
    "distractor_resistance",
    "externalized_trace_lookup",
    "grounded_plan_execution",
    "plan_preservation",
    "retrieval_precision",
    "reuse_ready_state",
    "state_recording",
    "tool_effect_verification",
    "verification",
}
VERIFICATION_TOOLS = {
    "read_graph",
    "search_nodes",
    "read_text_file",
    "search_files",
    "sequentialthinking",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(encode_portable_paths(row, project_root=ROOT), ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_tem_params() -> dict[str, Any]:
    raw = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    return raw["tool_execution_memory"]


def posterior_after_failures(params: dict[str, Any], failures: int) -> float:
    prior_alpha = float(params["BAYESIAN_PRIOR_ALPHA"])
    prior_beta = float(params["BAYESIAN_PRIOR_BETA"])
    danger_threshold = float(params["DANGER_THRESHOLD"])
    if abs(prior_beta - 1.0) > 1e-12 or abs(danger_threshold - 0.5) > 1e-12:
        raise RuntimeError(
            "TEM-Hard guard warmup currently supports the calibrated setting "
            "BAYESIAN_PRIOR_BETA=1.0 and DANGER_THRESHOLD=0.5. "
            "Update the generator if the guard math is recalibrated."
        )
    alpha = prior_alpha + failures
    return 1.0 - (danger_threshold ** alpha)


def failures_needed_for_block(params: dict[str, Any]) -> int:
    block_conf = float(params["BAYESIAN_BLOCK_CONFIDENCE"])
    for failures in range(1, 30):
        if posterior_after_failures(params, failures) > block_conf:
            return failures
    raise RuntimeError("Could not derive guard warmup length from current parameters")


def value_hash(arguments: dict[str, Any], preview_len: int) -> str:
    parts: list[str] = []
    for key in sorted(arguments.keys()):
        value = arguments[key]
        preview = str(value)[:preview_len]
        digest = hashlib.md5(preview.encode("utf-8")).hexdigest()[:6]
        parts.append(f"{key}={type(value).__name__}:{digest}")
    return "|".join(parts)


def schema_signature(arguments: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), type(value).__name__) for key, value in arguments.items()))


def chain_signature(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple((str(step.get("server", "")), str(step.get("tool", ""))) for step in row.get("steps", []))


def stable_row(row: dict[str, Any]) -> bool:
    steps = row.get("steps", [])
    if not steps:
        return False
    servers = {str(step.get("server", "")) for step in steps}
    return servers <= STABLE_SERVERS and not (servers & EXCLUDED_SERVERS)


def hard_features(row: dict[str, Any]) -> list[str]:
    steps = row.get("steps", [])
    servers = {str(step.get("server", "")) for step in steps}
    tools = [str(step.get("tool", "")) for step in steps]
    focus = set(row.get("memory_focus", []) or [])
    features: list[str] = []
    if len(steps) >= 5:
        features.append("long_horizon_5plus")
    elif len(steps) >= 3:
        features.append("multi_step_3plus")
    if len(servers) >= 2:
        features.append("cross_server")
    if any(tool in VERIFICATION_TOOLS for tool in tools[1:]):
        features.append("downstream_verification")
    if focus & HARD_FOCUS:
        features.append("memory_relevant_focus")
    if row.get("difficulty") == "hard":
        features.append("source_marked_hard")
    return features


def hard_score(row: dict[str, Any]) -> int:
    score = 0
    steps = row.get("steps", [])
    if len(steps) >= 5:
        score += 2
    elif len(steps) >= 3:
        score += 1
    features = set(hard_features(row))
    score += int("cross_server" in features) * 2
    score += int("downstream_verification" in features)
    score += int("memory_relevant_focus" in features)
    score += int("source_marked_hard" in features)
    return score


def clone_step(step: dict[str, Any], role: str) -> dict[str, Any]:
    cloned = {
        "tool": step.get("tool", ""),
        "server": step.get("server", ""),
        "arguments": dict(step.get("arguments", {})),
        "should_succeed": bool(step.get("should_succeed", True)),
        "error_type": step.get("error_type", ""),
        "error_message": step.get("error_message", ""),
        "expect_contains": list(step.get("expect_contains", []) or []),
        "expect_not_contains": list(step.get("expect_not_contains", []) or []),
        "role": role,
    }
    return cloned


def build_success_control_steps(source_row: dict[str, Any], target_index: int) -> list[dict[str, Any]]:
    """
    Include prerequisite prefix steps so the chosen success control is executable
    as a standalone episode.
    """
    built: list[dict[str, Any]] = []
    for idx, step in enumerate(source_row.get("steps", [])):
        if idx > target_index:
            break
        role = "guard_success_control_target" if idx == target_index else "guard_success_control_setup"
        built.append(clone_step(step, role))
    return built


def annotate_recipe_row(row: dict[str, Any], split: str) -> dict[str, Any]:
    annotated = dict(row)
    sig = chain_signature(row)
    annotated["tem_hard_design"] = {
        "view": "recipe_reuse",
        "source_split": split,
        "source_id": row.get("id", ""),
        "hard_score": hard_score(row),
        "hard_features": hard_features(row),
        "recipe_chain_signature": [f"{server}/{tool}" for server, tool in sig],
        "candidate_tool_leakage_warning": (
            "tools_available may make some recipe families easy; publication "
            "runs should report task_only and task_plus_tools query modes."
        ),
    }
    return annotated


def success_step(
    *,
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    expect_contains: list[str] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "tool": tool,
        "server": server,
        "arguments": dict(arguments or {}),
        "should_succeed": True,
        "error_type": "",
        "error_message": "",
    }
    if expect_contains:
        step["expect_contains"] = list(expect_contains)
    return step


def targeted_recipe_design(row: dict[str, Any], split: str, family: str, hardening_target: str) -> dict[str, Any]:
    sig = chain_signature(row)
    features = hard_features(row)
    if "targeted_bottleneck_hardening" not in features:
        features.append("targeted_bottleneck_hardening")
    if "distractor_candidate_tools" not in features:
        features.append("distractor_candidate_tools")
    return {
        "view": "recipe_reuse_targeted_hardening",
        "source_split": split,
        "source_id": row.get("id", ""),
        "augmentation_family": family,
        "augmentation_seed": SEED,
        "hardening_target": hardening_target,
        "hard_score": hard_score(row) + 1,
        "hard_features": features,
        "recipe_chain_signature": [f"{server}/{tool}" for server, tool in sig],
        "why_added": (
            "Added after router diagnostics showed weak step-conditioned routing "
            "in planning-heavy and memory-grounding categories. These rows are "
            "deterministic internal hardening samples, not an external benchmark."
        ),
        "candidate_tool_leakage_warning": (
            "tools_available deliberately includes plausible distractor tools; "
            "publication runs should report task_only, task_plus_tools, and "
            "candidate-pool size."
        ),
    }


def plan_loop_path(case_number: str) -> Path:
    return GENERATED_DIR / f"plan_loop_h_{case_number}.txt"


def build_plan_memory_loop_hardening(case_number: str, split: str) -> dict[str, Any]:
    entity = f"tem_v2_plan_memory_{case_number}_entity_1"
    signal = f"plan::{case_number}::verify_mcp_tool_health"
    row = {
        "id": f"plan_memory_h_{case_number}",
        "task": (
            f"Targeted hardening: plan once, avoid repeated planning, then store "
            f"and open the memory handoff for case {case_number}"
        ),
        "category": "plan_memory_loop",
        "difficulty": "hard",
        "tools_available": [
            "sequentialthinking",
            "create_entities",
            "search_nodes",
            "read_graph",
            "read_text_file",
            "search_files",
        ],
        "expected_success": True,
        "steps": [
            success_step(
                server="sequential_thinking",
                tool="sequentialthinking",
                arguments={
                    "thought": (
                        f"Plan memory handoff for case {case_number}; after this "
                        "step the correct route leaves planning and writes memory."
                    ),
                    "nextThoughtNeeded": False,
                    "thoughtNumber": 1,
                    "totalThoughts": 1,
                },
                expect_contains=["thoughtNumber", "totalThoughts"],
            ),
            success_step(
                server="memory",
                tool="create_entities",
                arguments={
                    "entities": [
                        {
                            "name": entity,
                            "entityType": "plan",
                            "observations": [signal, "routing-note::do-not-repeat-sequentialthinking"],
                        }
                    ]
                },
                expect_contains=[entity, signal],
            ),
            success_step(
                server="memory",
                tool="search_nodes",
                arguments={"query": signal},
                expect_contains=[entity, signal],
            ),
            success_step(server="memory", tool="read_graph", arguments={}, expect_contains=[entity, signal]),
        ],
        "memory_focus": [
            "plan_preservation",
            "reuse_ready_state",
            "step_conditioned_routing",
            "planning_exit_control",
            "memory_graph_verification",
        ],
    }
    row["tem_hard_design"] = targeted_recipe_design(
        row,
        split,
        "plan_memory_loop_graph_verification",
        "force the router to leave sequentialthinking and complete write-search-read_graph memory verification",
    )
    return row


def build_plan_filesystem_grounding_hardening(case_number: str, split: str) -> dict[str, Any]:
    row = {
        "id": f"plan_filesystem_h_{case_number}",
        "task": (
            f"Targeted hardening: plan a filesystem-only evidence audit with "
            f"memory-word distractors for case {case_number}"
        ),
        "category": "plan_filesystem_grounding",
        "difficulty": "hard",
        "tools_available": [
            "sequentialthinking",
            "list_allowed_directories",
            "search_files",
            "read_text_file",
            "create_entities",
            "search_nodes",
        ],
        "expected_success": True,
        "steps": [
            success_step(
                server="sequential_thinking",
                tool="sequentialthinking",
                arguments={
                    "thought": (
                        f"Plan filesystem grounding for case {case_number}; "
                        "memory terms are distractors and no memory write is needed."
                    ),
                    "nextThoughtNeeded": False,
                    "thoughtNumber": 1,
                    "totalThoughts": 1,
                },
                expect_contains=["thoughtNumber", "totalThoughts"],
            ),
            success_step(
                server="filesystem",
                tool="list_allowed_directories",
                arguments={},
                expect_contains=[str(ROOT)],
            ),
            success_step(
                server="filesystem",
                tool="search_files",
                arguments={"path": str(FS_STATE_DIR / "archive"), "pattern": "session_log.txt"},
                expect_contains=[str(ARCHIVE_LOG_PATH)],
            ),
            success_step(
                server="filesystem",
                tool="read_text_file",
                arguments={"path": str(ARCHIVE_LOG_PATH)},
                expect_contains=["avoid fake benchmark claims", "compare successful tool recipes"],
            ),
            success_step(
                server="filesystem",
                tool="search_files",
                arguments={"path": str(FS_STATE_DIR / "checklists"), "pattern": "review_plan.txt"},
                expect_contains=[str(CHECKLIST_PATH)],
            ),
        ],
        "memory_focus": [
            "grounded_plan_execution",
            "filesystem_grounding",
            "memory_distractor_resistance",
            "step_conditioned_routing",
        ],
    }
    row["tem_hard_design"] = targeted_recipe_design(
        row,
        split,
        "plan_filesystem_with_memory_distractors",
        "separate filesystem grounding from memory-looking lexical cues after planning",
    )
    return row


def build_memory_chain_grounding_hardening(case_number: str, split: str) -> dict[str, Any]:
    entity_person = f"tem_v2_memory_chain_{case_number}_entity_1"
    entity_project = f"tem_v2_memory_chain_{case_number}_entity_2"
    person_signal = f"person-case::{case_number}"
    project_signal = f"project-case::{case_number}"
    row = {
        "id": f"memory_chain_h_{case_number}",
        "task": (
            f"Targeted hardening: write linked memory pointers, open the selected "
            f"node, then ground both pointers in filesystem evidence for case {case_number}"
        ),
        "category": "memory_chain_grounding",
        "difficulty": "hard",
        "tools_available": [
            "create_entities",
            "search_nodes",
            "read_graph",
            "read_text_file",
            "search_files",
            "list_allowed_directories",
        ],
        "expected_success": True,
        "steps": [
            success_step(
                server="memory",
                tool="create_entities",
                arguments={
                    "entities": [
                        {
                            "name": entity_person,
                            "entityType": "file_ref",
                            "observations": [f"{person_signal}::Alice Chen::{ALICE_PROFILE_PATH}"],
                        },
                        {
                            "name": entity_project,
                            "entityType": "file_ref",
                            "observations": [f"{project_signal}::TEM Notes::{PROJECT_NOTES_PATH}"],
                        },
                    ]
                },
                expect_contains=[entity_person, entity_project],
            ),
            success_step(
                server="memory",
                tool="search_nodes",
                arguments={"query": person_signal},
                expect_contains=[entity_person, person_signal],
            ),
            success_step(server="memory", tool="read_graph", arguments={}, expect_contains=[entity_person, entity_project]),
            success_step(
                server="filesystem",
                tool="read_text_file",
                arguments={"path": str(ALICE_PROFILE_PATH)},
                expect_contains=["Alice Chen", "research engineer"],
            ),
            success_step(
                server="filesystem",
                tool="search_files",
                arguments={"path": str(FS_STATE_DIR / "projects"), "pattern": "tem_notes.md"},
                expect_contains=[str(PROJECT_NOTES_PATH)],
            ),
            success_step(
                server="filesystem",
                tool="read_text_file",
                arguments={"path": str(PROJECT_NOTES_PATH)},
                expect_contains=["TEM Notes", "waste_call_rate"],
            ),
        ],
        "memory_focus": [
            "cross_tool_linking",
            "verification",
            "externalized_trace_lookup",
            "graph_grounding",
            "step_conditioned_routing",
        ],
    }
    row["tem_hard_design"] = targeted_recipe_design(
        row,
        split,
        "memory_chain_graph_filesystem_grounding",
        "test memory write-search-read_graph transitions before grounding retrieved pointers with filesystem tools",
    )
    return row


def build_plan_memory_filesystem_loop_hardening(case_number: str, split: str) -> dict[str, Any]:
    entity = f"tem_v2_plan_memory_filesystem_{case_number}_entity_1"
    signal = f"artifact-case::{case_number}"
    artifact_path = plan_loop_path(case_number)
    content = (
        f"case: {case_number}\n"
        "loop: targeted-plan-memory-filesystem\n"
        "signal: reuse-ready-state\n"
        f"memory_pointer: {signal}"
    )
    row = {
        "id": f"plan_memory_fs_h_{case_number}",
        "task": (
            f"Targeted hardening: plan, verify allowed filesystem scope, read a "
            f"checklist, write a memory pointer, persist an artifact, and verify "
            f"both stores for case {case_number}"
        ),
        "category": "plan_memory_filesystem_loop",
        "difficulty": "hard",
        "tools_available": [
            "sequentialthinking",
            "list_allowed_directories",
            "read_text_file",
            "create_entities",
            "create_directory",
            "write_file",
            "search_nodes",
            "search_files",
        ],
        "expected_success": True,
        "steps": [
            success_step(
                server="sequential_thinking",
                tool="sequentialthinking",
                arguments={
                    "thought": (
                        f"Plan cross-server memory/filesystem loop for case {case_number}; "
                        "after planning, alternate tools instead of staying in one server."
                    ),
                    "nextThoughtNeeded": False,
                    "thoughtNumber": 1,
                    "totalThoughts": 1,
                },
                expect_contains=["thoughtNumber", "totalThoughts"],
            ),
            success_step(
                server="filesystem",
                tool="list_allowed_directories",
                arguments={},
                expect_contains=[str(ROOT)],
            ),
            success_step(
                server="filesystem",
                tool="read_text_file",
                arguments={"path": str(CHECKLIST_PATH)},
                expect_contains=["run benchmark", "inspect false blocks"],
            ),
            success_step(
                server="memory",
                tool="create_entities",
                arguments={
                    "entities": [
                        {
                            "name": entity,
                            "entityType": "artifact",
                            "observations": [f"{signal}::{artifact_path}"],
                        }
                    ]
                },
                expect_contains=[entity, str(artifact_path)],
            ),
            success_step(
                server="filesystem",
                tool="create_directory",
                arguments={"path": str(GENERATED_DIR)},
            ),
            success_step(
                server="filesystem",
                tool="write_file",
                arguments={"path": str(artifact_path), "content": content},
                expect_contains=[str(artifact_path)],
            ),
            success_step(
                server="memory",
                tool="search_nodes",
                arguments={"query": signal},
                expect_contains=[entity, signal, str(artifact_path)],
            ),
            success_step(
                server="filesystem",
                tool="search_files",
                arguments={"path": str(GENERATED_DIR), "pattern": artifact_path.name},
                expect_contains=[str(artifact_path)],
            ),
        ],
        "memory_focus": [
            "plan_preservation",
            "reuse_ready_state",
            "tool_effect_verification",
            "cross_server_loop",
            "step_conditioned_routing",
        ],
    }
    row["tem_hard_design"] = targeted_recipe_design(
        row,
        split,
        "plan_memory_filesystem_eight_step_loop",
        "stress long-horizon alternation across planning, filesystem grounding, memory write, file write, and dual verification",
    )
    return row


def build_targeted_hardening_rows(split: str) -> list[dict[str, Any]]:
    count = TARGETED_HARDENING_SPLIT_COUNTS[split]
    split_offset = TARGETED_HARDENING_SPLIT_OFFSETS[split]
    builders = {
        "plan_memory_loop": build_plan_memory_loop_hardening,
        "plan_memory_filesystem_loop": build_plan_memory_filesystem_loop_hardening,
        "plan_filesystem_grounding": build_plan_filesystem_grounding_hardening,
        "memory_chain_grounding": build_memory_chain_grounding_hardening,
    }
    rows: list[dict[str, Any]] = []
    for category, builder in builders.items():
        base = TARGETED_HARDENING_CATEGORY_OFFSETS[category] + split_offset
        for index in range(1, count + 1):
            rows.append(builder(f"{base + index:04d}", split))
    rows.sort(key=lambda item: (item.get("category", ""), item.get("id", "")))
    return rows


def apply_targeted_hardening(recipe_views: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    added_by_split: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "dev", "test"):
        additions = build_targeted_hardening_rows(split)
        existing_ids = {str(row.get("id", "")) for row in recipe_views[split]}
        overlap = sorted(str(row.get("id", "")) for row in additions if str(row.get("id", "")) in existing_ids)
        if overlap:
            raise RuntimeError(f"Targeted hardening IDs overlap existing TEM-Hard rows: {overlap[:5]}")
        recipe_views[split].extend(additions)
        recipe_views[split].sort(key=lambda item: (item.get("category", ""), item.get("id", "")))
        added_by_split[split] = additions
    return {
        "enabled": True,
        "seed": SEED,
        "trigger": "router_diagnostic_and_memory_mechanism_audit_bottlenecks",
        "status": "internal_synthetic_targeted_hardening",
        "split_counts_per_category": dict(TARGETED_HARDENING_SPLIT_COUNTS),
        "target_categories": sorted(TARGETED_HARDENING_CATEGORY_OFFSETS),
        "added_counts": {split: len(rows) for split, rows in added_by_split.items()},
        "added_category_distribution": {split: distribution(rows) for split, rows in added_by_split.items()},
        "design_principles": [
            "Add long-horizon and step-conditioned routing pressure instead of duplicating old templates.",
            "Keep every step executable with current official MCP filesystem, memory, and sequentialthinking servers.",
            "Include plausible distractor candidate tools where the weak category requires disambiguation.",
            "Keep the augmentation clearly marked as internal synthetic hardening, not external authoritative data.",
        ],
    }


def select_recipe_rows(split_rows: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {}
    for split, rows in split_rows.items():
        view = []
        for row in rows:
            if not row.get("expected_success", False):
                continue
            if not stable_row(row):
                continue
            if hard_score(row) < RECIPE_HARD_SCORE_THRESHOLD:
                continue
            view.append(annotate_recipe_row(row, split))
        view.sort(key=lambda item: (item.get("category", ""), item.get("id", "")))
        selected[split] = view
    return selected


def failure_signatures(
    rows: list[dict[str, Any]],
    preview_len: int,
) -> tuple[
    dict[tuple[str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]],
    dict[tuple[str, str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]],
]:
    by_family: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    by_exact: dict[tuple[str, str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        if row.get("expected_success", True):
            continue
        if not stable_row(row):
            continue
        for step in row.get("steps", []):
            if step.get("should_succeed", True):
                continue
            family = (
                str(step.get("server", "")),
                str(step.get("tool", "")),
                str(step.get("error_type", "")),
                str(step.get("error_message", "")),
            )
            exact = family + (value_hash(step.get("arguments", {}) or {}, preview_len),)
            by_family[family].append((row, step))
            by_exact[exact].append((row, step))
    return by_family, by_exact


def success_controls(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[tuple[dict[str, Any], int, dict[str, Any]]]]:
    controls: dict[tuple[str, str], list[tuple[dict[str, Any], int, dict[str, Any]]]] = defaultdict(list)
    seen: set[tuple[str, str, tuple[tuple[str, str], ...], str, int]] = set()
    for row in rows:
        if not row.get("expected_success", False):
            continue
        if not stable_row(row):
            continue
        for index, step in enumerate(row.get("steps", [])):
            server = str(step.get("server", ""))
            tool = str(step.get("tool", ""))
            marker = (
                server,
                tool,
                schema_signature(step.get("arguments", {}) or {}),
                str(row.get("id", "")),
                index,
            )
            if marker in seen:
                continue
            seen.add(marker)
            controls[(server, tool)].append((row, index, step))
    return controls


def build_guard_views(split_rows: dict[str, list[dict[str, Any]]], params: dict[str, Any]) -> dict[str, Any]:
    preview_len = int(params["ARG_VALUE_PREVIEW_LEN"])
    warmup = failures_needed_for_block(params)
    train_family, train_exact = failure_signatures(split_rows["train"], preview_len)
    test_family, test_exact = failure_signatures(split_rows["test"], preview_len)
    controls_by_tool = success_controls(split_rows["test"])

    exact_candidates: list[dict[str, Any]] = []
    for exact, train_items in train_exact.items():
        family = exact[:4]
        test_items = test_exact.get(exact, [])
        if len(train_items) < GUARD_TRAIN_MIN_SUPPORT or len(test_items) < GUARD_TEST_MIN_SUPPORT:
            continue
        exact_candidates.append(
            {
                "exact": exact,
                "family": family,
                "train_support": len(train_items),
                "test_support": len(test_items),
            }
        )
    exact_candidates.sort(key=lambda item: (-item["train_support"], -item["test_support"], item["exact"]))

    selected_families: list[dict[str, Any]] = []
    used_family_keys: set[tuple[str, str, str, str]] = set()
    for candidate in exact_candidates:
        family = candidate["family"]
        if family in used_family_keys:
            # Keep one exact value per family so that transfer tests remain interpretable.
            continue
        server, tool, _, _ = family
        if len(controls_by_tool.get((server, tool), [])) < GUARD_SUCCESS_CONTROLS_PER_FAMILY:
            continue
        selected_families.append(candidate)
        used_family_keys.add(family)

    train_rows: list[dict[str, Any]] = []
    exact_test_rows: list[dict[str, Any]] = []
    transfer_test_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    family_stats: list[dict[str, Any]] = []

    for index, candidate in enumerate(selected_families):
        family_id = f"guard_family_{index:03d}"
        exact = candidate["exact"]
        family = candidate["family"]
        server, tool, error_type, error_message = family
        train_items = train_exact[exact]
        exact_test_items = test_exact.get(exact, [])
        transfer_items = [
            item
            for item in test_family.get(family, [])
            if family + (value_hash(item[1].get("arguments", {}) or {}, preview_len),) != exact
        ]
        control_items = controls_by_tool.get((server, tool), [])

        for attempt, (source_row, source_step) in enumerate(train_items[:warmup], start=1):
            train_rows.append(
                {
                    "id": f"{family_id}_warmup_{attempt:02d}",
                    "task": f"Warm up guard for {server}/{tool} {error_type}",
                    "category": "tem_hard_guard_warmup",
                    "difficulty": "hard",
                    "tools_available": [tool],
                    "expected_success": False,
                    "expected_failure_cause": error_type,
                    "memory_focus": ["failure_replay_guarding", "unsafe_action_blocking"],
                    "tem_hard_design": {
                        "view": "guard_train_warmup",
                        "family_id": family_id,
                        "source_split": "train",
                        "source_id": source_row.get("id", ""),
                        "exact_signature_sha1": hashlib.sha1(repr(exact).encode("utf-8")).hexdigest(),
                        "warmup_attempt": attempt,
                        "warmup_attempts_needed": warmup,
                    },
                    "steps": [clone_step(source_step, "guard_warmup_failure")],
                }
            )

        for attempt, (source_row, source_step) in enumerate(
            exact_test_items[:GUARD_EXACT_TEST_MAX_PER_FAMILY],
            start=1,
        ):
            exact_test_rows.append(
                {
                    "id": f"{family_id}_exact_{attempt:02d}",
                    "task": f"Exact repeated failure replay for {server}/{tool} {error_type}",
                    "category": "tem_hard_guard_exact_replay",
                    "difficulty": "hard",
                    "tools_available": [tool],
                    "expected_success": False,
                    "expected_failure_cause": error_type,
                    "memory_focus": ["failure_replay_guarding", "unsafe_action_blocking"],
                    "tem_hard_design": {
                        "view": "guard_exact_test",
                        "family_id": family_id,
                        "source_split": "test",
                        "source_id": source_row.get("id", ""),
                        "exact_signature_sha1": hashlib.sha1(repr(exact).encode("utf-8")).hexdigest(),
                    },
                    "steps": [clone_step(source_step, "guard_exact_test_failure")],
                }
            )

        for attempt, (source_row, source_step) in enumerate(
            transfer_items[:GUARD_TRANSFER_TEST_MAX_PER_FAMILY],
            start=1,
        ):
            transfer_test_rows.append(
                {
                    "id": f"{family_id}_transfer_{attempt:02d}",
                    "task": f"Same-family transfer failure for {server}/{tool} {error_type}",
                    "category": "tem_hard_guard_transfer",
                    "difficulty": "hard",
                    "tools_available": [tool],
                    "expected_success": False,
                    "expected_failure_cause": error_type,
                    "memory_focus": ["failure_generalization", "unsafe_action_blocking"],
                    "tem_hard_design": {
                        "view": "guard_transfer_test",
                        "family_id": family_id,
                        "source_split": "test",
                        "source_id": source_row.get("id", ""),
                        "trained_exact_signature_sha1": hashlib.sha1(repr(exact).encode("utf-8")).hexdigest(),
                        "expected_current_tem_behavior": (
                            "Current TEM guards use argument-value hashes, so same-family "
                            "different-value failures may remain unblocked. Report this as "
                            "a limitation, not as a runner bug."
                        ),
                    },
                    "steps": [clone_step(source_step, "guard_transfer_test_failure")],
                }
            )

        used_control_ids: set[str] = set()
        for attempt, (source_row, step_index, source_step) in enumerate(control_items, start=1):
            if source_row.get("id", "") in used_control_ids:
                continue
            used_control_ids.add(str(source_row.get("id", "")))
            control_steps = build_success_control_steps(source_row, step_index)
            control_rows.append(
                {
                    "id": f"{family_id}_control_{len(used_control_ids):02d}",
                    "task": f"Success control for {server}/{tool} after guard warmup",
                    "category": "tem_hard_guard_success_control",
                    "difficulty": source_row.get("difficulty", "medium"),
                    "tools_available": [tool],
                    "expected_success": True,
                    "memory_focus": ["false_block_resistance", "schema_disambiguation"],
                    "tem_hard_design": {
                        "view": "guard_success_control",
                        "family_id": family_id,
                        "source_split": "test",
                        "source_id": source_row.get("id", ""),
                        "target_step_index": step_index,
                        "setup_steps": max(len(control_steps) - 1, 0),
                        "paired_error_type": error_type,
                        "paired_error_message": error_message,
                    },
                    "steps": control_steps,
                }
            )
            if len(used_control_ids) >= GUARD_SUCCESS_CONTROLS_PER_FAMILY:
                break

        family_stats.append(
            {
                "family_id": family_id,
                "server": server,
                "tool": tool,
                "error_type": error_type,
                "error_message": error_message,
                "train_exact_support": candidate["train_support"],
                "test_exact_support": candidate["test_support"],
                "test_transfer_support": len(transfer_items),
                "success_control_support": len(control_items),
            }
        )

    return {
        "warmup_attempts_needed": warmup,
        "families": family_stats,
        "train_warmup": train_rows,
        "exact_test": exact_test_rows,
        "transfer_test": transfer_test_rows,
        "success_controls": control_rows,
    }


def distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(row.get("category", "unknown")) for row in rows))


def main() -> None:
    params = load_tem_params()
    source_all = load_jsonl(SOURCE_ALL)
    split_rows = {name: load_jsonl(path) for name, path in SOURCE_SPLITS.items()}

    for row in source_all[:20]:
        for step in row.get("steps", []):
            tool = str(step.get("tool", ""))
            if tool in {
                "memory_add",
                "memory_search",
                "memory_info",
                "memory_clear",
                "write_text_file",
                "search_text",
                "fs_root",
                "fetch_url",
                "head_url",
                "think_stepwise",
                "evaluate_plan",
            }:
                raise RuntimeError(
                    "TEM-Hard source dataset is not the canonical official-schema TEM-ToolBench-v2. "
                    "Detected legacy wrapper tool: "
                    f"{tool}"
                )

    recipe_views = select_recipe_rows(split_rows)
    targeted_hardening = apply_targeted_hardening(recipe_views)
    guard_views = build_guard_views(split_rows, params)

    live_test = (
        recipe_views["test"]
        + guard_views["exact_test"]
        + guard_views["transfer_test"]
        + guard_views["success_controls"]
    )
    live_test.sort(key=lambda item: (item.get("category", ""), item.get("id", "")))

    write_jsonl(OUT_RECIPE_TRAIN, recipe_views["train"])
    write_jsonl(OUT_RECIPE_DEV, recipe_views["dev"])
    write_jsonl(OUT_RECIPE_TEST, recipe_views["test"])
    write_jsonl(OUT_GUARD_TRAIN, guard_views["train_warmup"])
    write_jsonl(OUT_GUARD_EXACT_TEST, guard_views["exact_test"])
    write_jsonl(OUT_GUARD_TRANSFER_TEST, guard_views["transfer_test"])
    write_jsonl(OUT_GUARD_CONTROLS, guard_views["success_controls"])
    write_jsonl(OUT_LIVE_TEST, live_test)

    recipe_chain_families = {
        split: len({chain_signature(row) for row in rows})
        for split, rows in recipe_views.items()
    }
    meta = {
        "name": "TEM-Hard",
        "version": "0.3-official-mcp-schema-portable-paths",
        "path_portability": {
            "root_token": MCP_MIRROR_ROOT_TOKEN,
            "runtime_resolution": "Paths under the repository root are stored with a portable root token and expanded at runtime.",
            "intentional_external_negative_paths": [
                "C:\\Windows\\System32\\drivers\\etc\\hosts",
                "C:\\Windows\\Temp\\plan_loop.txt",
            ],
        },
        "seed": SEED,
        "source_dataset": "TEM-ToolBench-v2",
        "source_dataset_sha256": sha256_file(SOURCE_ALL),
        "source_records": len(source_all),
        "source_schema_type": "official_mcp_servers",
        "status": "internal_synthetic_benchmark",
        "selection_rule": {
            "stable_servers": sorted(STABLE_SERVERS),
            "excluded_servers": sorted(EXCLUDED_SERVERS),
            "recipe_hard_score_threshold": RECIPE_HARD_SCORE_THRESHOLD,
            "recipe_hard_score_features": {
                "long_horizon_5plus": 2,
                "multi_step_3plus": 1,
                "cross_server": 2,
                "downstream_verification": 1,
                "memory_relevant_focus": 1,
                "source_marked_hard": 1,
            },
            "guard_train_min_support": GUARD_TRAIN_MIN_SUPPORT,
            "guard_test_min_support": GUARD_TEST_MIN_SUPPORT,
            "guard_success_controls_per_family": GUARD_SUCCESS_CONTROLS_PER_FAMILY,
            "manual_cherry_pick": False,
            "targeted_hardening": targeted_hardening,
        },
        "guard_calibration": {
            "prior_alpha": params["BAYESIAN_PRIOR_ALPHA"],
            "prior_beta": params["BAYESIAN_PRIOR_BETA"],
            "danger_threshold": params["DANGER_THRESHOLD"],
            "block_confidence": params["BAYESIAN_BLOCK_CONFIDENCE"],
            "warmup_failures_needed_for_block": guard_views["warmup_attempts_needed"],
        },
        "files": {
            "recipe_train": str(OUT_RECIPE_TRAIN.relative_to(ROOT)),
            "recipe_dev": str(OUT_RECIPE_DEV.relative_to(ROOT)),
            "recipe_test": str(OUT_RECIPE_TEST.relative_to(ROOT)),
            "guard_train_warmup": str(OUT_GUARD_TRAIN.relative_to(ROOT)),
            "guard_exact_test": str(OUT_GUARD_EXACT_TEST.relative_to(ROOT)),
            "guard_transfer_test": str(OUT_GUARD_TRANSFER_TEST.relative_to(ROOT)),
            "guard_success_controls": str(OUT_GUARD_CONTROLS.relative_to(ROOT)),
            "live_test": str(OUT_LIVE_TEST.relative_to(ROOT)),
        },
        "counts": {
            "recipe_train": len(recipe_views["train"]),
            "recipe_dev": len(recipe_views["dev"]),
            "recipe_test": len(recipe_views["test"]),
            "recipe_chain_families": recipe_chain_families,
            "guard_train_warmup": len(guard_views["train_warmup"]),
            "guard_exact_test": len(guard_views["exact_test"]),
            "guard_transfer_test": len(guard_views["transfer_test"]),
            "guard_success_controls": len(guard_views["success_controls"]),
            "live_test": len(live_test),
        },
        "category_distribution": {
            "recipe_train": distribution(recipe_views["train"]),
            "recipe_dev": distribution(recipe_views["dev"]),
            "recipe_test": distribution(recipe_views["test"]),
            "live_test": distribution(live_test),
        },
        "guard_family_stats": guard_views["families"],
        "research_purpose": [
            "Maintain the canonical TEM-Hard view over the official MCP schema benchmark.",
            "Evaluate recipe reuse on hard multi-step, cross-server, verification-heavy success episodes.",
            "Evaluate guard exact replay, same-family transfer limits, and false-block resistance separately.",
            "Expose candidate-tool leakage and source-template leakage instead of hiding them.",
            "Target the empirically weak planning-heavy and memory-grounding categories with auditable hardening families.",
        ],
        "limitations": [
            "TEM-Hard is internal and synthetic; it is not an external authoritative benchmark.",
            "Recipe episodes derive from templated TEM-ToolBench-v2 tasks, so lexical baselines must be reported.",
            "Current TEM guard matching is still conservative; same-family transfer is limited by exact and pattern guard rules.",
            "Fixed-step live execution cannot prove open-ended LLM planning gains by itself.",
            "The targeted hardening rows are deterministic internal augmentations driven by observed bottlenecks, not natural task logs.",
        ],
        "notes": [
            "This is the current canonical TEM-Hard built from official MCP tool names.",
            "This repository keeps only the official MCP-schema TEM-Hard mainline artifacts.",
            "Targeted hardening rows are marked with tem_hard_design.view=recipe_reuse_targeted_hardening.",
        ],
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "counts": meta["counts"], "meta": str(OUT_META)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
