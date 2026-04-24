"""
Generate TEM-ToolBench-v2 dataset with harder, reality-aligned TEM scenarios.

Design principles:
- Align with MCP tools currently exposed by the running backend.
- Use only failure patterns that are either schema-valid business failures
  or argument-validation failures we verified against the live API.
- Emphasize tool-execution-memory behavior instead of generic QA.
- Produce 2000 episodes with explicit category/difficulty coverage.

Outputs:
- datasets/tem_toolbench_v2/tem_toolbench_v2.jsonl
- datasets/tem_toolbench_v2/tem_toolbench_v2_train.jsonl
- datasets/tem_toolbench_v2/tem_toolbench_v2_dev.jsonl
- datasets/tem_toolbench_v2/tem_toolbench_v2_test.jsonl
- datasets/tem_toolbench_v2/tem_toolbench_v2_meta.json
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "datasets" / "tem_toolbench_v2"
OUT_ALL = OUT_DIR / "tem_toolbench_v2.jsonl"
OUT_TRAIN = OUT_DIR / "tem_toolbench_v2_train.jsonl"
OUT_DEV = OUT_DIR / "tem_toolbench_v2_dev.jsonl"
OUT_TEST = OUT_DIR / "tem_toolbench_v2_test.jsonl"
OUT_META = OUT_DIR / "tem_toolbench_v2_meta.json"

SEED = 20260411
TOTAL_EPISODES = 2000
TRAIN_EPISODES = 1000
DEV_EPISODES = 400
TEST_EPISODES = 600

# Stable files created once and then referenced by filesystem episodes.
FS_STATE_DIR = ROOT / "datasets" / "tem_toolbench_v2" / "fs_state"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _mk_step(
    tool: str,
    server: str,
    arguments: dict[str, Any],
    *,
    should_succeed: bool,
    error_type: str = "",
    error_message: str = "",
    expect_contains: list[str] | None = None,
    expect_not_contains: list[str] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "tool": tool,
        "server": server,
        "arguments": arguments,
        "should_succeed": should_succeed,
        "error_type": error_type,
        "error_message": error_message,
    }
    if expect_contains:
        step["expect_contains"] = expect_contains
    if expect_not_contains:
        step["expect_not_contains"] = expect_not_contains
    return step


def _episode(
    episode_id: str,
    task: str,
    category: str,
    difficulty: str,
    tools_available: list[str],
    expected_success: bool,
    steps: list[dict[str, Any]],
    *,
    expected_failure_cause: str = "",
    memory_focus: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": episode_id,
        "task": task,
        "category": category,
        "difficulty": difficulty,
        "tools_available": tools_available,
        "expected_success": expected_success,
        "steps": steps,
    }
    if expected_failure_cause:
        row["expected_failure_cause"] = expected_failure_cause
    if memory_focus:
        row["memory_focus"] = memory_focus
    return row


def _ensure_fs_state() -> dict[str, str]:
    FS_STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_files = {
        "people": "people/alice_profile.txt",
        "project": "projects/tem_notes.md",
        "archive": "archive/session_log.txt",
        "checklist": "checklists/review_plan.txt",
    }
    contents = {
        "people": "\n".join(
            [
                "name: Alice Chen",
                "role: research engineer",
                "project: MCP Mirror",
                "favorite_tool: memory_search",
                "office: room-314",
            ]
        ),
        "project": "\n".join(
            [
                "# TEM Notes",
                "priority: reduce repeated tool failure",
                "key metric: waste_call_rate",
                "status: active",
            ]
        ),
        "archive": "\n".join(
            [
                "[session] recall prior failure traces",
                "[session] compare successful tool recipes",
                "[session] avoid fake benchmark claims",
            ]
        ),
        "checklist": "\n".join(
            [
                "1. verify live MCP tool inventory",
                "2. reset stale guards",
                "3. run benchmark",
                "4. inspect false blocks",
            ]
        ),
    }
    for key, rel in state_files.items():
        path = FS_STATE_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents[key], encoding="utf-8")
    return state_files


def _memory_key(category: str, idx: int, slot: int) -> str:
    return f"tem_v2/{category}/{idx:04d}/slot_{slot}"


def _memory_value(category: str, idx: int, slot: int) -> str:
    return f"value::{category}::{idx:04d}::{slot}"


def _make_memory_recall_success(idx: int) -> dict[str, Any]:
    key = _memory_key("memory_recall", idx, 1)
    value = _memory_value("memory_recall", idx, 1)
    return _episode(
        f"memory_recall_s_{idx:04d}",
        f"Store and retrieve a fresh memory item {idx}",
        "memory_recall",
        "easy",
        ["memory_add", "memory_search", "memory_info"],
        True,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": value, "tags": ["tem-v2", "memory-recall", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key, value],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": key, "limit": 5},
                should_succeed=True,
                expect_contains=[key, value],
            ),
        ],
        memory_focus=["store", "exact_recall"],
    )


def _make_memory_recall_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"memory_recall_f_{idx:04d}",
        f"Trigger real validation failure on memory_add missing value {idx}",
        "memory_recall",
        "easy",
        ["memory_add", "memory_search"],
        False,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": _memory_key("memory_recall_fail", idx, 1)},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            )
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation"],
    )


def _make_memory_distractor_success(idx: int) -> dict[str, Any]:
    key_main = _memory_key("memory_distractor", idx, 1)
    key_noise = _memory_key("memory_distractor", idx, 2)
    value_main = f"target-note::{idx:04d}::critical finding"
    value_noise = f"distractor-note::{idx:04d}::secondary detail"
    return _episode(
        f"memory_distractor_s_{idx:04d}",
        f"Retrieve target memory under distractor load {idx}",
        "memory_distractor_recall",
        "medium",
        ["memory_add", "memory_search"],
        True,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": key_noise, "value": value_noise, "tags": ["distractor", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key_noise, value_noise],
            ),
            _mk_step(
                "memory_add",
                "memory",
                {"key": key_main, "value": value_main, "tags": ["target", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key_main, value_main],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": f"critical finding {idx:04d}", "limit": 5},
                should_succeed=True,
                expect_contains=[key_main, value_main],
            ),
        ],
        memory_focus=["distractor_resistance", "retrieval_precision"],
    )


def _make_memory_distractor_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"memory_distractor_f_{idx:04d}",
        f"Trigger real validation failure on memory_search missing query {idx}",
        "memory_distractor_recall",
        "medium",
        ["memory_search"],
        False,
        [
            _mk_step(
                "memory_search",
                "memory",
                {},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            )
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation"],
    )


def _make_memory_cross_tool_success(idx: int, files: dict[str, str]) -> dict[str, Any]:
    rel = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / files["project"])
    key = _memory_key("memory_cross_tool", idx, 1)
    value = f"cross-tool reference::{rel}"
    return _episode(
        f"memory_cross_tool_s_{idx:04d}",
        f"Store filesystem hint in memory and verify it through file read {idx}",
        "memory_cross_tool_verification",
        "hard",
        ["memory_add", "memory_search", "read_text_file"],
        True,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": value, "tags": ["cross-tool", "filesystem", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key, rel],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": rel, "limit": 5},
                should_succeed=True,
                expect_contains=[key, rel],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["waste_call_rate", "TEM Notes"],
            ),
        ],
        memory_focus=["cross_tool_linking", "verification"],
    )


def _make_memory_cross_tool_failure(idx: int) -> dict[str, Any]:
    escape_path = "..\\Windows\\system.ini" if idx % 2 else "../outside.txt"
    return _episode(
        f"memory_cross_tool_f_{idx:04d}",
        f"Attempt illegal filesystem escape after planning from memory {idx}",
        "memory_cross_tool_verification",
        "hard",
        ["memory_add", "read_text_file"],
        False,
        [
            _mk_step(
                "memory_add",
                "memory",
                {
                    "key": _memory_key("memory_cross_tool_fail", idx, 1),
                    "value": f"bad-path::{escape_path}",
                    "tags": ["cross-tool", "invalid-path"],
                },
                should_succeed=True,
                expect_contains=[escape_path],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": escape_path, "encoding": "utf-8"},
                should_succeed=False,
                error_type="PermissionError",
                error_message="path escapes root",
            ),
        ],
        expected_failure_cause="PermissionError",
        memory_focus=["unsafe_action_blocking", "cross_tool_verification"],
    )


def _make_filesystem_probe_success(idx: int, files: dict[str, str]) -> dict[str, Any]:
    rel = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / files["archive"])
    return _episode(
        f"filesystem_probe_s_{idx:04d}",
        f"Navigate filesystem and locate TEM-related trace {idx}",
        "filesystem_probe",
        "medium",
        ["fs_root", "list_directory", "search_text", "read_text_file"],
        True,
        [
            _mk_step("fs_root", "filesystem", {}, should_succeed=True, expect_contains=["mirror_mcp"]),
            _mk_step(
                "search_text",
                "filesystem",
                {"pattern": "avoid fake benchmark claims", "path": "datasets/tem_toolbench_v2", "max_results": 5},
                should_succeed=True,
                expect_contains=[rel, "avoid fake benchmark claims"],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["avoid fake benchmark claims", "compare successful tool recipes"],
            ),
        ],
        memory_focus=["externalized_trace_lookup"],
    )


def _make_filesystem_probe_failure(idx: int) -> dict[str, Any]:
    missing = f"datasets/tem_toolbench_v2/fs_state/missing_{idx:04d}.txt"
    return _episode(
        f"filesystem_probe_f_{idx:04d}",
        f"Read a definitely missing file {idx}",
        "filesystem_probe",
        "medium",
        ["read_text_file"],
        False,
        [
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": missing, "encoding": "utf-8"},
                should_succeed=False,
                error_type="FileNotFoundError",
                error_message="file not found",
            )
        ],
        expected_failure_cause="FileNotFoundError",
        memory_focus=["resource_not_found"],
    )


def _make_filesystem_writeback_success(idx: int) -> dict[str, Any]:
    rel = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / "generated" / f"case_{idx:04d}.txt")
    content = "\n".join(
        [
            f"case: {idx:04d}",
            "note: writeback verification",
            "metric: false_block_rate",
        ]
    )
    return _episode(
        f"filesystem_writeback_s_{idx:04d}",
        f"Write and verify a benchmark artifact {idx}",
        "filesystem_writeback",
        "hard",
        ["write_text_file", "read_text_file", "search_text"],
        True,
        [
            _mk_step(
                "write_text_file",
                "filesystem",
                {"path": rel, "content": content, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=[rel],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["writeback verification", "false_block_rate"],
            ),
            _mk_step(
                "search_text",
                "filesystem",
                {"pattern": "false_block_rate", "path": "datasets/tem_toolbench_v2/fs_state/generated", "max_results": 10},
                should_succeed=True,
                expect_contains=[rel, "false_block_rate"],
            ),
        ],
        memory_focus=["tool_effect_verification"],
    )


def _make_filesystem_writeback_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"filesystem_writeback_f_{idx:04d}",
        f"Trigger filesystem validation failure by missing required search pattern {idx}",
        "filesystem_writeback",
        "hard",
        ["search_text"],
        False,
        [
            _mk_step(
                "search_text",
                "filesystem",
                {"path": "datasets/tem_toolbench_v2"},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            )
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation"],
    )


def _make_plan_memory_success(idx: int) -> dict[str, Any]:
    key = _memory_key("plan_memory", idx, 1)
    value = f"goal::{idx:04d}::verify_mcp_tool_health"
    plan = [
        "check current tool inventory",
        "run a live MCP call",
        "compare result with expected behavior",
        "store the outcome for later reuse",
    ]
    return _episode(
        f"plan_memory_s_{idx:04d}",
        f"Form a stepwise plan and preserve it in memory {idx}",
        "plan_memory_loop",
        "medium",
        ["think_stepwise", "evaluate_plan", "memory_add", "memory_search"],
        True,
        [
            _mk_step(
                "think_stepwise",
                "sequential_thinking",
                {"problem": f"Verify MCP tool health for case {idx:04d}", "max_steps": 4},
                should_succeed=True,
                expect_contains=["Define objective", "Break problem into independent sub-problems"],
            ),
            _mk_step(
                "evaluate_plan",
                "sequential_thinking",
                {"plan": plan},
                should_succeed=True,
                expect_contains=["readiness_score", "Plan is executable"],
            ),
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": value, "tags": ["plan", "verified", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key, value],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": value, "limit": 5},
                should_succeed=True,
                expect_contains=[key, value],
            ),
        ],
        memory_focus=["plan_preservation", "reuse_ready_state"],
    )


def _make_plan_memory_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"plan_memory_f_{idx:04d}",
        f"Trigger planning validation failure with missing problem {idx}",
        "plan_memory_loop",
        "medium",
        ["think_stepwise"],
        False,
        [
            _mk_step(
                "think_stepwise",
                "sequential_thinking",
                {},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            )
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation"],
    )


def _make_plan_filesystem_success(idx: int, files: dict[str, str]) -> dict[str, Any]:
    rel = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / files["checklist"])
    plan = [
        "open benchmark checklist",
        "verify stale guards are reset",
        "run the experiment and record anomalies",
    ]
    return _episode(
        f"plan_filesystem_s_{idx:04d}",
        f"Plan then verify checklist evidence from filesystem {idx}",
        "plan_filesystem_grounding",
        "hard",
        ["evaluate_plan", "read_text_file", "search_text"],
        True,
        [
            _mk_step(
                "evaluate_plan",
                "sequential_thinking",
                {"plan": plan},
                should_succeed=True,
                expect_contains=["readiness_score", "Plan is executable"],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["reset stale guards", "inspect false blocks"],
            ),
            _mk_step(
                "search_text",
                "filesystem",
                {"pattern": "run benchmark", "path": "datasets/tem_toolbench_v2/fs_state", "max_results": 10},
                should_succeed=True,
                expect_contains=[rel, "run benchmark"],
            ),
        ],
        memory_focus=["grounded_plan_execution"],
    )


def _make_plan_filesystem_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"plan_filesystem_f_{idx:04d}",
        f"Trigger evaluation validation failure with missing plan {idx}",
        "plan_filesystem_grounding",
        "hard",
        ["evaluate_plan"],
        False,
        [
            _mk_step(
                "evaluate_plan",
                "sequential_thinking",
                {},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            )
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation"],
    )


def _make_fetch_memory_success(idx: int) -> dict[str, Any]:
    key = _memory_key("fetch_memory", idx, 1)
    url = "https://example.com"
    return _episode(
        f"fetch_memory_s_{idx:04d}",
        f"Check URL metadata and store result pointer in memory {idx}",
        "fetch_memory_bridge",
        "hard",
        ["head_url", "memory_add", "memory_search"],
        True,
        [
            _mk_step(
                "head_url",
                "fetch",
                {"url": url, "timeout": 8},
                should_succeed=True,
                expect_contains=["status_code", "example.com"],
            ),
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": f"url::{url}", "tags": ["fetch", "memory", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key, url],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": "example.com", "limit": 5},
                should_succeed=True,
                expect_contains=[key, url],
            ),
        ],
        memory_focus=["cross_tool_bridge", "state_recording"],
    )


def _make_fetch_memory_failure(idx: int) -> dict[str, Any]:
    url = f"not-a-url-{idx:04d}"
    return _episode(
        f"fetch_memory_f_{idx:04d}",
        f"Trigger business failure on malformed URL fetch {idx}",
        "fetch_memory_bridge",
        "hard",
        ["fetch_url"],
        False,
        [
            _mk_step(
                "fetch_url",
                "fetch",
                {"url": url, "timeout": 3},
                should_succeed=False,
                error_type="NetworkError",
                error_message="missing an 'http://' or 'https://' protocol",
            )
        ],
        expected_failure_cause="NetworkError",
        memory_focus=["external_failure_capture"],
    )


def _make_cdar_success(idx: int) -> dict[str, Any]:
    # This remains synthetic for file availability, so keep volume low and clearly scoped.
    return _episode(
        f"cdar_guard_s_{idx:04d}",
        f"CDAR minimal valid-schema call shape {idx}",
        "cdar_guarding",
        "hard",
        ["cdar_compositional_decomposed_adaptive_reasoning"],
        True,
        [
            _mk_step(
                "cdar_compositional_decomposed_adaptive_reasoning",
                "cdar_mcp",
                {"image_path": "datasets/tem_toolbench_v2/fs_state/demo_image.png", "question": f"Describe sample {idx:04d}"},
                should_succeed=True,
            )
        ],
        memory_focus=["tool_schema_coverage"],
    )


def _make_cdar_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"cdar_guard_f_{idx:04d}",
        f"Trigger CDAR schema failure by omitting image_path {idx}",
        "cdar_guarding",
        "hard",
        ["cdar_compositional_decomposed_adaptive_reasoning"],
        False,
        [
            _mk_step(
                "cdar_compositional_decomposed_adaptive_reasoning",
                "cdar_mcp",
                {"question": f"Describe sample {idx:04d}"},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            )
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation"],
    )


def _make_memory_chain_success(idx: int, files: dict[str, str]) -> dict[str, Any]:
    rel_people = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / files["people"])
    rel_project = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / files["project"])
    key_person = _memory_key("memory_chain", idx, 1)
    key_project = _memory_key("memory_chain", idx, 2)
    person_value = f"person-file::{rel_people}"
    project_value = f"project-file::{rel_project}"
    return _episode(
        f"memory_chain_s_{idx:04d}",
        f"Store two linked memory pointers and verify both via filesystem {idx}",
        "memory_chain_grounding",
        "hard",
        ["memory_add", "memory_search", "read_text_file", "search_text"],
        True,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": key_person, "value": person_value, "tags": ["multi-hop", "person", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key_person, rel_people],
            ),
            _mk_step(
                "memory_add",
                "memory",
                {"key": key_project, "value": project_value, "tags": ["multi-hop", "project", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key_project, rel_project],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": rel_people, "limit": 5},
                should_succeed=True,
                expect_contains=[key_person, rel_people],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel_people, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["Alice Chen", "favorite_tool: memory_search"],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel_project, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["TEM Notes", "waste_call_rate"],
            ),
            _mk_step(
                "search_text",
                "filesystem",
                {"pattern": "research engineer", "path": "datasets/tem_toolbench_v2/fs_state", "max_results": 5},
                should_succeed=True,
                expect_contains=[rel_people, "research engineer"],
            ),
        ],
        memory_focus=["cross_tool_linking", "verification", "externalized_trace_lookup"],
    )


def _make_memory_chain_failure(idx: int) -> dict[str, Any]:
    bad_rel = f"datasets/tem_toolbench_v2/fs_state/generated/not_created_{idx:04d}.txt"
    key = _memory_key("memory_chain_fail", idx, 1)
    return _episode(
        f"memory_chain_f_{idx:04d}",
        f"Store a stale pointer then fail on missing grounded file {idx}",
        "memory_chain_grounding",
        "hard",
        ["memory_add", "memory_search", "read_text_file"],
        False,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": f"stale-file::{bad_rel}", "tags": ["stale", "missing-file"]},
                should_succeed=True,
                expect_contains=[key, bad_rel],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": bad_rel, "limit": 5},
                should_succeed=True,
                expect_contains=[key, bad_rel],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": bad_rel, "encoding": "utf-8"},
                should_succeed=False,
                error_type="FileNotFoundError",
                error_message="file not found",
            ),
        ],
        expected_failure_cause="FileNotFoundError",
        memory_focus=["resource_not_found", "cross_tool_verification"],
    )


def _make_plan_memory_filesystem_success(idx: int, files: dict[str, str]) -> dict[str, Any]:
    rel_checklist = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / files["checklist"])
    output_rel = str(Path("datasets") / "tem_toolbench_v2" / "fs_state" / "generated" / f"plan_loop_{idx:04d}.txt")
    plan = [
        "inspect benchmark checklist",
        "save a reusable execution note",
        "retrieve the saved state from memory",
        "verify the note on disk",
    ]
    key = _memory_key("plan_memory_filesystem", idx, 1)
    value = f"artifact::{output_rel}"
    content = "\n".join(
        [
            f"case: {idx:04d}",
            "loop: plan-memory-filesystem",
            "signal: reuse-ready-state",
        ]
    )
    return _episode(
        f"plan_memory_fs_s_{idx:04d}",
        f"Plan, persist to memory, write artifact, and verify all links {idx}",
        "plan_memory_filesystem_loop",
        "hard",
        ["evaluate_plan", "read_text_file", "memory_add", "memory_search", "write_text_file", "search_text"],
        True,
        [
            _mk_step(
                "evaluate_plan",
                "sequential_thinking",
                {"plan": plan},
                should_succeed=True,
                expect_contains=["readiness_score", "Plan is executable"],
            ),
            _mk_step(
                "read_text_file",
                "filesystem",
                {"path": rel_checklist, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=["run benchmark", "inspect false blocks"],
            ),
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": value, "tags": ["loop", "artifact", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key, output_rel],
            ),
            _mk_step(
                "write_text_file",
                "filesystem",
                {"path": output_rel, "content": content, "encoding": "utf-8"},
                should_succeed=True,
                expect_contains=[output_rel],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": output_rel, "limit": 5},
                should_succeed=True,
                expect_contains=[key, output_rel],
            ),
            _mk_step(
                "search_text",
                "filesystem",
                {"pattern": "reuse-ready-state", "path": "datasets/tem_toolbench_v2/fs_state/generated", "max_results": 10},
                should_succeed=True,
                expect_contains=[output_rel, "reuse-ready-state"],
            ),
        ],
        memory_focus=["plan_preservation", "reuse_ready_state", "tool_effect_verification"],
    )


def _make_plan_memory_filesystem_failure(idx: int) -> dict[str, Any]:
    bad_path = "..\\outside\\plan_loop.txt" if idx % 2 else "../outside/plan_loop.txt"
    key = _memory_key("plan_memory_filesystem_fail", idx, 1)
    return _episode(
        f"plan_memory_fs_f_{idx:04d}",
        f"Plan then fail on unsafe write target {idx}",
        "plan_memory_filesystem_loop",
        "hard",
        ["evaluate_plan", "memory_add", "write_text_file"],
        False,
        [
            _mk_step(
                "evaluate_plan",
                "sequential_thinking",
                {"plan": ["store note", "write file outside root"]},
                should_succeed=True,
                expect_contains=["readiness_score", "Plan is executable"],
            ),
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": f"unsafe-target::{bad_path}", "tags": ["unsafe", "path"]},
                should_succeed=True,
                expect_contains=[key, bad_path],
            ),
            _mk_step(
                "write_text_file",
                "filesystem",
                {"path": bad_path, "content": "unsafe", "encoding": "utf-8"},
                should_succeed=False,
                error_type="PermissionError",
                error_message="path escapes root",
            ),
        ],
        expected_failure_cause="PermissionError",
        memory_focus=["unsafe_action_blocking", "plan_preservation"],
    )


def _make_memory_info_audit_success(idx: int) -> dict[str, Any]:
    key = _memory_key("memory_info_audit", idx, 1)
    value = f"audit-signal::{idx:04d}"
    return _episode(
        f"memory_info_audit_s_{idx:04d}",
        f"Store memory then audit backend memory state {idx}",
        "memory_info_audit",
        "medium",
        ["memory_add", "memory_info", "memory_search"],
        True,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": key, "value": value, "tags": ["audit", f"case-{idx:04d}"]},
                should_succeed=True,
                expect_contains=[key, value],
            ),
            _mk_step(
                "memory_info",
                "memory",
                {},
                should_succeed=True,
                expect_contains=["mcp_memory.jsonl", "count"],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {"query": value, "limit": 5},
                should_succeed=True,
                expect_contains=[key, value],
            ),
        ],
        memory_focus=["store", "verification", "state_recording"],
    )


def _make_memory_info_audit_failure(idx: int) -> dict[str, Any]:
    return _episode(
        f"memory_info_audit_f_{idx:04d}",
        f"Store memory then fail on missing search query during audit {idx}",
        "memory_info_audit",
        "medium",
        ["memory_add", "memory_info", "memory_search"],
        False,
        [
            _mk_step(
                "memory_add",
                "memory",
                {"key": _memory_key("memory_info_audit_fail", idx, 1), "value": f"audit-fail::{idx:04d}", "tags": ["audit", "failure"]},
                should_succeed=True,
                expect_contains=[f"audit-fail::{idx:04d}"],
            ),
            _mk_step(
                "memory_info",
                "memory",
                {},
                should_succeed=True,
                expect_contains=["mcp_memory.jsonl", "count"],
            ),
            _mk_step(
                "memory_search",
                "memory",
                {},
                should_succeed=False,
                error_type="ValidationError",
                error_message="Missing required argument",
            ),
        ],
        expected_failure_cause="ValidationError",
        memory_focus=["schema_validation", "verification"],
    )


def generate_dataset(seed: int = SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    files = _ensure_fs_state()

    builders: list[tuple[str, int, Any]] = [
        ("memory_recall_success", 220, _make_memory_recall_success),
        ("memory_recall_failure", 80, _make_memory_recall_failure),
        ("memory_distractor_success", 180, _make_memory_distractor_success),
        ("memory_distractor_failure", 60, _make_memory_distractor_failure),
        ("memory_cross_tool_success", 170, lambda i: _make_memory_cross_tool_success(i, files)),
        ("memory_cross_tool_failure", 60, _make_memory_cross_tool_failure),
        ("filesystem_probe_success", 120, lambda i: _make_filesystem_probe_success(i, files)),
        ("filesystem_probe_failure", 50, _make_filesystem_probe_failure),
        ("filesystem_writeback_success", 120, _make_filesystem_writeback_success),
        ("filesystem_writeback_failure", 40, _make_filesystem_writeback_failure),
        ("plan_memory_success", 130, _make_plan_memory_success),
        ("plan_memory_failure", 50, _make_plan_memory_failure),
        ("plan_filesystem_success", 90, lambda i: _make_plan_filesystem_success(i, files)),
        ("plan_filesystem_failure", 30, _make_plan_filesystem_failure),
        ("fetch_memory_success", 55, _make_fetch_memory_success),
        ("fetch_memory_failure", 25, _make_fetch_memory_failure),
        ("memory_chain_success", 120, lambda i: _make_memory_chain_success(i, files)),
        ("memory_chain_failure", 50, _make_memory_chain_failure),
        ("plan_memory_filesystem_success", 140, lambda i: _make_plan_memory_filesystem_success(i, files)),
        ("plan_memory_filesystem_failure", 50, _make_plan_memory_filesystem_failure),
        ("memory_info_audit_success", 100, _make_memory_info_audit_success),
        ("memory_info_audit_failure", 40, _make_memory_info_audit_failure),
        ("cdar_success", 10, _make_cdar_success),
        ("cdar_failure", 10, _make_cdar_failure),
    ]

    episodes: list[dict[str, Any]] = []
    for _, count, builder in builders:
        for i in range(1, count + 1):
            episodes.append(builder(i))

    if len(episodes) != TOTAL_EPISODES:
        raise RuntimeError(f"Expected {TOTAL_EPISODES} episodes, got {len(episodes)}")

    rng.shuffle(episodes)
    return episodes


def _split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    n = len(rows)
    train_n = TRAIN_EPISODES
    dev_n = DEV_EPISODES
    test_n = TEST_EPISODES
    if train_n + dev_n + test_n != n:
        raise RuntimeError(
            f"Configured split sizes must equal total episodes: "
            f"{train_n}+{dev_n}+{test_n}!={n}"
        )
    train = rows[:train_n]
    dev = rows[train_n : train_n + dev_n]
    test = rows[train_n + dev_n :]
    if len(train) + len(dev) + len(test) != n:
        raise RuntimeError("Split sizes do not sum to total")
    if len(test) != test_n:
        raise RuntimeError(f"Expected test split size {test_n}, got {len(test)}")
    return train, dev, test


def write_outputs(episodes: list[dict[str, Any]], seed: int = SEED) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_jsonl(OUT_ALL, episodes)
    train, dev, test = _split_rows(episodes)
    _write_jsonl(OUT_TRAIN, train)
    _write_jsonl(OUT_DEV, dev)
    _write_jsonl(OUT_TEST, test)

    category_summary: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0, "failure": 0})
    difficulty_summary: Counter[str] = Counter()
    memory_focus_summary: Counter[str] = Counter()
    tools_summary: Counter[str] = Counter()
    failure_causes: Counter[str] = Counter()

    for ep in episodes:
        cat = ep["category"]
        category_summary[cat]["total"] += 1
        if ep["expected_success"]:
            category_summary[cat]["success"] += 1
        else:
            category_summary[cat]["failure"] += 1
            failure_causes[ep.get("expected_failure_cause", "unknown")] += 1
        difficulty_summary[ep["difficulty"]] += 1
        for focus in ep.get("memory_focus", []):
            memory_focus_summary[focus] += 1
        for tool in ep.get("tools_available", []):
            tools_summary[tool] += 1

    meta = {
        "name": "TEM-ToolBench-v2",
        "version": "2.2",
        "seed": seed,
        "total_episodes": len(episodes),
        "splits": {
            "train": len(train),
            "dev": len(dev),
            "test": len(test),
        },
        "categories": dict(category_summary),
        "difficulty_distribution": dict(difficulty_summary),
        "memory_focus_distribution": dict(memory_focus_summary),
        "tool_coverage": dict(tools_summary),
        "failure_cause_distribution": dict(failure_causes),
        "verified_live_failure_patterns": [
            "memory_add missing required key/value",
            "memory_search missing required query",
            "search_text missing required pattern",
            "think_stepwise missing required problem",
            "evaluate_plan missing required plan",
            "read_text_file path escapes root",
            "read_text_file file not found",
            "fetch_url malformed URL business failure",
            "cdar missing required image_path",
        ],
        "notes": [
            "This is an internal synthetic benchmark aligned to current MCP tool interfaces.",
            "Failure episodes were restricted to patterns checked against the live backend on 2026-04-11.",
            "Version 2.2 expands to 2000 episodes and adds harder multi-step memory/filesystem/planning loops.",
            "CDAR success cases cover schema shape only and should not be over-claimed as stable vision evaluation.",
            "Fetch success can be impacted by learned guards or network policy; use it as auxiliary, not primary evidence.",
        ],
        "schema": {
            "episode_fields": [
                "id",
                "task",
                "category",
                "difficulty",
                "tools_available",
                "expected_success",
                "expected_failure_cause",
                "memory_focus",
                "steps",
            ],
            "step_fields": [
                "tool",
                "server",
                "arguments",
                "should_succeed",
                "error_type",
                "error_message",
                "expect_contains",
                "expect_not_contains",
            ],
        },
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    episodes = generate_dataset(seed=SEED)
    write_outputs(episodes, seed=SEED)
    print(
        json.dumps(
            {
                "dataset": str(OUT_ALL),
                "train": str(OUT_TRAIN),
                "dev": str(OUT_DEV),
                "test": str(OUT_TEST),
                "meta": str(OUT_META),
                "episodes": len(episodes),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
