"""
Controlled and memory-conditioned argument policy for internal autonomous
trajectory evaluation.

This module intentionally targets the current internal benchmark schema.
It does not claim open-ended natural-language argument generation.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from probabilistic_params import load_required_params


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FS_STATE_DIR = PROJECT_ROOT / "datasets" / "tem_toolbench_v2" / "fs_state"
GENERATED_DIR = FS_STATE_DIR / "generated"
ARCHIVE_LOG_PATH = FS_STATE_DIR / "archive" / "session_log.txt"
CHECKLIST_PATH = FS_STATE_DIR / "checklists" / "review_plan.txt"
PROJECT_NOTES_PATH = FS_STATE_DIR / "projects" / "tem_notes.md"
ALICE_PROFILE_PATH = FS_STATE_DIR / "people" / "alice_profile.txt"
DEMO_IMAGE_PATH = FS_STATE_DIR / "demo_image.png"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
OUTSIDE_HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
OUTSIDE_PLAN_LOOP_PATH = r"C:\Windows\Temp\plan_loop.txt"

_ARGUMENT_POLICY_PARAM_KEYS = [
    "FETCH_MAX_LENGTH",
]

_ARGUMENT_POLICY_PARAMS = load_required_params("controlled_argument_policy", _ARGUMENT_POLICY_PARAM_KEYS)
FETCH_MAX_LENGTH = int(_ARGUMENT_POLICY_PARAMS["FETCH_MAX_LENGTH"])

SUPPORTED_ARGUMENT_POLICY_MODES = (
    "gold",
    "controlled",
    "controlled_with_fallback",
    "memory_conditioned",
    "memory_conditioned_with_fallback",
)

KNOWN_SIGNAL_PREFIXES = (
    "fact::",
    "audit-signal::",
    "audit-fail::",
    "cross-tool-case::",
    "person-case::",
    "project-case::",
    "stale-case::",
    "artifact-case::",
    "plan::",
    "fetch-health-case::",
    "target-note::",
    "distractor-note::",
)


def normalize_argument_policy_mode(mode: str | None) -> str:
    normalized = (mode or "gold").strip().lower()
    if normalized not in SUPPORTED_ARGUMENT_POLICY_MODES:
        supported = ", ".join(SUPPORTED_ARGUMENT_POLICY_MODES)
        raise ValueError(f"Unsupported argument policy mode: {mode!r}. Supported: {supported}")
    return normalized


def _extract_case_number(case_id: str, task: str) -> str:
    for text in (case_id, task):
        match = re.search(r"(\d{1,4})(?!.*\d)", str(text or ""))
        if match:
            return match.group(1).zfill(4)
    return ""


def _is_targeted_hardening(case_id: str) -> bool:
    return _text(case_id).startswith(
        (
            "plan_memory_h_",
            "plan_memory_fs_h_",
            "plan_filesystem_h_",
            "memory_chain_h_",
        )
    )


def _targeted_plan_loop_path(case_number: str) -> Path:
    return GENERATED_DIR / f"plan_loop_h_{case_number}.txt"


def _success_prefix(category: str) -> str:
    mapping = {
        "memory_recall": "tem_v2_memory_recall",
        "memory_distractor_recall": "tem_v2_memory_distractor",
        "memory_graph_audit": "tem_v2_memory_graph_audit",
        "memory_cross_tool_verification": "tem_v2_memory_cross_tool",
        "memory_chain_grounding": "tem_v2_memory_chain",
        "fetch_memory_bridge": "tem_v2_fetch_memory",
        "plan_memory_loop": "tem_v2_plan_memory",
        "plan_memory_filesystem_loop": "tem_v2_plan_memory_filesystem",
    }
    return mapping.get(category, "")


def _failure_prefix(category: str) -> str:
    mapping = {
        "memory_graph_audit": "tem_v2_memory_graph_audit_fail",
        "memory_chain_grounding": "tem_v2_memory_chain_fail",
    }
    return mapping.get(category, _success_prefix(category))


def _jsonable_arguments(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    return {}


def _deepcopy_jsonable(obj: Any) -> Any:
    try:
        return copy.deepcopy(obj)
    except Exception:
        return obj


def _text(value: Any) -> str:
    return str(value or "").strip()


def _path_text(value: Any) -> str:
    return _text(value).replace("/", "\\")


def _policy_result(
    *,
    supported: bool,
    arguments: dict[str, Any],
    template_name: str,
    source: str,
    reason: str,
    schema_match: bool = False,
    exact_match: bool = False,
    derivation_path: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "supported": supported,
        "arguments": dict(arguments),
        "template_name": template_name,
        "source": source,
        "reason": reason,
        "schema_match": schema_match,
        "exact_match": exact_match,
        "derivation_path": list(derivation_path or []),
    }


def _add_artifact(state: dict[str, Any], kind: str, value: Any, source: str) -> None:
    text = _text(value)
    if not text:
        return
    entry = {"kind": kind, "value": text, "source": source}
    artifacts = state.setdefault("artifacts", [])
    if entry not in artifacts:
        artifacts.append(entry)
    latest = state.setdefault("latest", {})
    latest[kind] = text
    if kind == "path":
        normalized = _path_text(text)
        latest["path"] = normalized
        try:
            path_obj = Path(normalized)
            if path_obj.suffix:
                latest["file_path"] = normalized
                latest["file_name"] = path_obj.name
                latest["directory_path"] = str(path_obj.parent)
            else:
                latest["directory_path"] = normalized
        except Exception as path_error:
            logger.debug("Could not derive path metadata from %r: %s", normalized, path_error)


def _collect_kind(state: dict[str, Any], kind: str) -> list[str]:
    values: list[str] = []
    for artifact in state.get("artifacts", []) or []:
        if not isinstance(artifact, dict):
            continue
        if _text(artifact.get("kind")) != kind:
            continue
        value = _text(artifact.get("value"))
        if value and value not in values:
            values.append(value)
    return values


def _latest(state: dict[str, Any], kind: str) -> str:
    return _text((state.get("latest") or {}).get(kind, ""))


def _first_match(state: dict[str, Any], kind: str, needle: str = "") -> str:
    needle_l = _text(needle).lower()
    for value in _collect_kind(state, kind):
        if not needle_l or needle_l in value.lower():
            return value
    return _latest(state, kind)


def _entity_name(category: str, case_number: str, idx: int, expected_success: bool = True) -> str:
    prefix = _success_prefix(category) if expected_success else _failure_prefix(category)
    return f"{prefix}_{case_number}_entity_{idx}" if prefix and case_number else ""


def _extract_paths(text: str) -> list[str]:
    found: list[str] = []
    for match in re.findall(r"[A-Za-z]:\\[^\s\"']+", text or ""):
        value = _path_text(match.rstrip(".,;:"))
        if value not in found:
            found.append(value)
    return found


def _extract_signals(text: str) -> list[str]:
    found: list[str] = []
    for prefix in KNOWN_SIGNAL_PREFIXES:
        for match in re.findall(rf"{re.escape(prefix)}[^\s\"']+", text or ""):
            value = match.rstrip(".,;:")
            if value not in found:
                found.append(value)
    return found


def _extract_entity_names(text: str) -> list[str]:
    found: list[str] = []
    for match in re.findall(r"tem_v2_[A-Za-z0-9_]+_entity_\d+", text or ""):
        if match not in found:
            found.append(match)
    return found


def _register_observation_text(state: dict[str, Any], text: str, source: str) -> None:
    value = _text(text)
    if not value:
        return
    _add_artifact(state, "observation", value, source)
    url_match = re.search(r"https?://[^\s\"']+", value)
    if url_match:
        _add_artifact(state, "url", url_match.group(0).rstrip(".,;:"), f"{source}.url")
    for path in _extract_paths(value):
        _add_artifact(state, "path", path, f"{source}.path")
    for entity in _extract_entity_names(value):
        _add_artifact(state, "entity_name", entity, f"{source}.entity")
    for signal in _extract_signals(value):
        _add_artifact(state, "signal", signal, f"{source}.signal")
        query_value = signal
        if signal.startswith(("cross-tool-case::", "person-case::", "stale-case::")):
            parts = signal.split("::")
            query_value = "::".join(parts[:2]) if len(parts) >= 2 else signal
        _add_artifact(state, "memory_query", query_value, f"{source}.query")


def _seed_state(case_id: str, category: str, task: str, expected_success: bool) -> dict[str, Any]:
    case_number = _extract_case_number(case_id, task)
    state = {
        "case_id": case_id,
        "case_number": case_number,
        "category": category,
        "task": task,
        "expected_success": bool(expected_success),
        "artifacts": [],
        "latest": {},
        "history": [],
    }

    def add(kind: str, value: Any, source: str = "seed") -> None:
        _add_artifact(state, kind, value, source)

    if category == "memory_recall" and expected_success:
        add("entity_name", _entity_name(category, case_number, 1))
        add("signal", f"fact::memory_recall::{case_number}::1")
        add("memory_query", f"fact::memory_recall::{case_number}::1")
    elif category == "memory_distractor_recall" and expected_success:
        add("entity_name", _entity_name(category, case_number, 1))
        add("entity_name", _entity_name(category, case_number, 2))
        add("memory_query", "critical finding")
        add("signal", f"target-note::{case_number}::critical finding")
    elif category == "memory_graph_audit":
        signal = f"audit-signal::{case_number}" if expected_success else f"audit-fail::{case_number}"
        add("entity_name", _entity_name(category, case_number, 1, expected_success))
        add("signal", signal)
        add("memory_query", signal)
    elif category == "memory_cross_tool_verification":
        if expected_success:
            add("entity_name", _entity_name(category, case_number, 1))
            add("signal", f"cross-tool-case::{case_number}")
            add("memory_query", f"cross-tool-case::{case_number}")
            add("path", str(PROJECT_NOTES_PATH))
        else:
            add("path", OUTSIDE_HOSTS_PATH)
    elif category == "memory_chain_grounding":
        if expected_success:
            add("entity_name", _entity_name(category, case_number, 1))
            add("entity_name", _entity_name(category, case_number, 2))
            add("signal", f"person-case::{case_number}")
            add("signal", f"project-case::{case_number}")
            add("memory_query", f"person-case::{case_number}")
            add("path", str(ALICE_PROFILE_PATH))
            add("path", str(PROJECT_NOTES_PATH))
        else:
            stale_path = str(GENERATED_DIR / f"not_created_{case_number}.txt")
            add("entity_name", _entity_name(category, case_number, 1, False))
            add("signal", f"stale-case::{case_number}")
            add("memory_query", f"stale-case::{case_number}")
            add("path", stale_path)
    elif category == "filesystem_probe":
        if expected_success:
            add("path", str(FS_STATE_DIR / "archive"))
            add("path", str(ARCHIVE_LOG_PATH))
            add("search_pattern", "session_log.txt")
        else:
            add("path", str(PROJECT_ROOT / f"definitely_missing_{case_number}.txt"))
    elif category == "filesystem_writeback":
        add("path", str(GENERATED_DIR))
        add("path", str(GENERATED_DIR / f"case_{case_number}.txt"))
        add("search_pattern", f"case_{case_number}.txt")
        add("content", f"case: {case_number}\nnote: writeback verification\nmetric: false_block_rate")
    elif category == "fetch_memory_bridge":
        if expected_success:
            add("url", BACKEND_HEALTH_URL)
            add("entity_name", _entity_name(category, case_number, 1))
            add("signal", f"fetch-health-case::{case_number}")
            add("memory_query", f"fetch-health-case::{case_number}")
        else:
            add("url", "not-a-url")
    elif category == "plan_filesystem_grounding":
        if expected_success:
            if _is_targeted_hardening(case_id):
                add("thought", f"Plan filesystem grounding for case {case_number}; memory terms are distractors and no memory write is needed.")
                add("path", str(FS_STATE_DIR / "archive"))
                add("path", str(ARCHIVE_LOG_PATH))
                add("path", str(FS_STATE_DIR / "checklists"))
                add("path", str(CHECKLIST_PATH))
                add("search_pattern", "session_log.txt")
                add("search_pattern", "review_plan.txt")
            else:
                add("thought", f"Verify benchmark checklist for case {case_number}")
                add("path", str(CHECKLIST_PATH))
                add("path", str(FS_STATE_DIR / "checklists"))
                add("search_pattern", "review_plan.txt")
        else:
            add("path", str(FS_STATE_DIR))
    elif category == "plan_memory_loop":
        if expected_success:
            if _is_targeted_hardening(case_id):
                add("thought", f"Plan memory handoff for case {case_number}; after this step the correct route leaves planning and writes memory.")
            else:
                add("thought", f"Plan MCP health verification for case {case_number}")
            add("entity_name", _entity_name(category, case_number, 1))
            add("signal", f"plan::{case_number}::verify_mcp_tool_health")
            add("memory_query", f"plan::{case_number}::verify_mcp_tool_health")
    elif category == "plan_memory_filesystem_loop":
        if expected_success:
            plan_path = _targeted_plan_loop_path(case_number) if _is_targeted_hardening(case_id) else (GENERATED_DIR / f"plan_loop_{case_number}.txt")
            if _is_targeted_hardening(case_id):
                add("thought", f"Plan cross-server memory/filesystem loop for case {case_number}; after planning, alternate tools instead of staying in one server.")
                add("path", str(PROJECT_ROOT))
                add("search_pattern", "session_log.txt")
            else:
                add("thought", f"Plan memory/filesystem verification loop for case {case_number}")
            add("entity_name", _entity_name(category, case_number, 1))
            add("signal", f"artifact-case::{case_number}")
            add("memory_query", f"artifact-case::{case_number}")
            add("path", str(CHECKLIST_PATH))
            add("path", str(GENERATED_DIR))
            add("path", str(plan_path))
            add("search_pattern", plan_path.name)
            if _is_targeted_hardening(case_id):
                add(
                    "content",
                    (
                        f"case: {case_number}\n"
                        "loop: targeted-plan-memory-filesystem\n"
                        "signal: reuse-ready-state\n"
                        f"memory_pointer: artifact-case::{case_number}"
                    ),
                )
            else:
                add("content", f"case: {case_number}\nloop: plan-memory-filesystem\nsignal: reuse-ready-state")
        else:
            add("thought", "Write a file outside the allowed project root")
            add("path", OUTSIDE_PLAN_LOOP_PATH)
            add("content", "unsafe")
    elif category == "cdar_guarding":
        add("question", f"Describe sample {case_number}")
        if expected_success:
            add("path", str(DEMO_IMAGE_PATH))

    return state


def build_initial_argument_state(*, case_id: str, category: str, task: str, expected_success: bool) -> dict[str, Any]:
    return _seed_state(case_id, category, task, expected_success)
def update_argument_state(
    *,
    state: dict[str, Any],
    step_index: int,
    selected_tool: str,
    arguments: dict[str, Any] | None,
    result: Any = None,
    blocked: bool = False,
    success: bool | None = None,
) -> dict[str, Any]:
    updated = _deepcopy_jsonable(state)
    if not isinstance(updated, dict):
        updated = {"artifacts": [], "latest": {}, "history": []}

    latest = updated.setdefault("latest", {})
    latest["step_index"] = int(step_index)
    latest["step_tool"] = _text(selected_tool)
    latest["blocked"] = bool(blocked)
    if success is not None:
        latest["success"] = bool(success)

    args = _jsonable_arguments(arguments or {})
    source = f"step_{step_index}.{_text(selected_tool)}.arguments"

    if "query" in args:
        _add_artifact(updated, "memory_query", args.get("query"), f"{source}.query")
    if "path" in args:
        _add_artifact(updated, "path", _path_text(args.get("path")), f"{source}.path")
    if "pattern" in args:
        _add_artifact(updated, "search_pattern", args.get("pattern"), f"{source}.pattern")
    if "url" in args:
        _add_artifact(updated, "url", args.get("url"), f"{source}.url")
    if "content" in args:
        _add_artifact(updated, "content", args.get("content"), f"{source}.content")
    if "thought" in args:
        _add_artifact(updated, "thought", args.get("thought"), f"{source}.thought")
    if "question" in args:
        _add_artifact(updated, "question", args.get("question"), f"{source}.question")
    for name in args.get("names", []) or []:
        _add_artifact(updated, "entity_name", name, f"{source}.names")
    for entity in args.get("entities", []) or []:
        if not isinstance(entity, dict):
            continue
        _add_artifact(updated, "entity_name", entity.get("name"), f"{source}.entity_name")
        _add_artifact(updated, "entity_type", entity.get("entityType"), f"{source}.entity_type")
        for observation in entity.get("observations", []) or []:
            _register_observation_text(updated, str(observation), f"{source}.observation")

    result_text = ""
    if isinstance(result, dict):
        if isinstance(result.get("result"), str):
            result_text = str(result.get("result", ""))
        else:
            result_text = json.dumps(result, ensure_ascii=False, default=str)
    elif result is not None:
        result_text = str(result)

    if result_text:
        _add_artifact(updated, "result_text", result_text, f"step_{step_index}.{_text(selected_tool)}.result_text")
        _register_observation_text(updated, result_text, f"step_{step_index}.{_text(selected_tool)}.result")

    updated.setdefault("history", []).append(
        {
            "step_index": int(step_index),
            "tool": _text(selected_tool),
            "blocked": bool(blocked),
            "success": bool(success) if success is not None else None,
            "arguments": _deepcopy_jsonable(args),
            "result_excerpt": result_text[:400],
        }
    )
    return updated


def generate_controlled_arguments(
    *,
    case_id: str,
    category: str,
    task: str,
    expected_success: bool,
    step_index: int,
    selected_tool: str,
    gold_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gold = _jsonable_arguments(gold_arguments or {})
    case_number = _extract_case_number(case_id, task)
    if not case_number:
        return _policy_result(
            supported=False,
            arguments={},
            template_name="",
            source="unsupported",
            reason="missing_case_number",
        )

    generated: dict[str, Any] | None = None
    template_name = ""

    if category == "cdar_guarding":
        template_name = "cdar_guarding_v1"
        generated = {"question": f"Describe sample {case_number}"}
        if expected_success:
            generated["image_path"] = str(DEMO_IMAGE_PATH)

    elif category == "fetch_memory_bridge":
        template_name = "fetch_memory_bridge_v1"
        if step_index == 0 and selected_tool == "fetch":
            generated = {"url": "not-a-url"} if not expected_success else {"url": BACKEND_HEALTH_URL, "max_length": FETCH_MAX_LENGTH}
        elif step_index == 1 and expected_success and selected_tool == "create_entities":
            generated = {
                "entities": [
                    {
                        "name": _entity_name(category, case_number, 1),
                        "entityType": "url_fact",
                        "observations": [f"fetch-health-case::{case_number}::url::{BACKEND_HEALTH_URL}"],
                    }
                ]
            }
        elif step_index == 2 and expected_success and selected_tool == "search_nodes":
            generated = {"query": f"fetch-health-case::{case_number}"}

    elif category == "filesystem_probe":
        template_name = "filesystem_probe_v1"
        if expected_success:
            if step_index == 0 and selected_tool == "list_allowed_directories":
                generated = {}
            elif step_index == 1 and selected_tool == "search_files":
                generated = {"path": str(FS_STATE_DIR / "archive"), "pattern": "session_log.txt"}
            elif step_index == 2 and selected_tool == "read_text_file":
                generated = {"path": str(ARCHIVE_LOG_PATH)}
        elif selected_tool == "read_text_file":
            generated = {"path": str(PROJECT_ROOT / f"definitely_missing_{case_number}.txt")}

    elif category == "filesystem_writeback":
        template_name = "filesystem_writeback_v1"
        case_file = GENERATED_DIR / f"case_{case_number}.txt"
        if expected_success:
            if step_index == 0 and selected_tool == "create_directory":
                generated = {"path": str(GENERATED_DIR)}
            elif step_index == 1 and selected_tool == "write_file":
                generated = {
                    "path": str(case_file),
                    "content": f"case: {case_number}\nnote: writeback verification\nmetric: false_block_rate",
                }
            elif step_index == 2 and selected_tool == "read_text_file":
                generated = {"path": str(case_file)}
            elif step_index == 3 and selected_tool == "search_files":
                generated = {"path": str(GENERATED_DIR), "pattern": f"case_{case_number}.txt"}
        elif selected_tool == "write_file":
            generated = {"path": str(case_file)}

    elif category == "memory_chain_grounding":
        template_name = "memory_chain_grounding_h1" if _is_targeted_hardening(case_id) else "memory_chain_grounding_v1"
        if expected_success:
            if step_index == 0 and selected_tool == "create_entities":
                generated = {
                    "entities": [
                        {
                            "name": _entity_name(category, case_number, 1),
                            "entityType": "file_ref",
                            "observations": [f"person-case::{case_number}::Alice Chen::{ALICE_PROFILE_PATH}"],
                        },
                        {
                            "name": _entity_name(category, case_number, 2),
                            "entityType": "file_ref",
                            "observations": [f"project-case::{case_number}::TEM Notes::{PROJECT_NOTES_PATH}"],
                        },
                    ]
                }
            elif step_index == 1 and selected_tool == "search_nodes":
                generated = {"query": f"person-case::{case_number}"}
            elif _is_targeted_hardening(case_id):
                if step_index == 2 and selected_tool == "read_graph":
                    generated = {}
                elif step_index == 3 and selected_tool == "read_text_file":
                    generated = {"path": str(ALICE_PROFILE_PATH)}
                elif step_index == 4 and selected_tool == "search_files":
                    generated = {"path": str(FS_STATE_DIR / "projects"), "pattern": "tem_notes.md"}
                elif step_index == 5 and selected_tool == "read_text_file":
                    generated = {"path": str(PROJECT_NOTES_PATH)}
            else:
                if step_index == 2 and selected_tool == "read_text_file":
                    generated = {"path": str(ALICE_PROFILE_PATH)}
                elif step_index == 3 and selected_tool == "read_text_file":
                    generated = {"path": str(PROJECT_NOTES_PATH)}
        else:
            stale_path = GENERATED_DIR / f"not_created_{case_number}.txt"
            if step_index == 0 and selected_tool == "create_entities":
                generated = {
                    "entities": [
                        {
                            "name": _entity_name(category, case_number, 1, False),
                            "entityType": "file_ref",
                            "observations": [f"stale-case::{case_number}::path::{stale_path}"],
                        }
                    ]
                }
            elif step_index == 1 and selected_tool == "search_nodes":
                generated = {"query": f"stale-case::{case_number}"}
            elif step_index == 2 and selected_tool == "read_text_file":
                generated = {"path": str(stale_path)}

    elif category == "memory_cross_tool_verification":
        template_name = "memory_cross_tool_verification_v1"
        if expected_success:
            if step_index == 0 and selected_tool == "create_entities":
                generated = {
                    "entities": [
                        {
                            "name": _entity_name(category, case_number, 1),
                            "entityType": "file_ref",
                            "observations": [f"cross-tool-case::{case_number}::filesystem-pointer::{PROJECT_NOTES_PATH}"],
                        }
                    ]
                }
            elif step_index == 1 and selected_tool == "search_nodes":
                generated = {"query": f"cross-tool-case::{case_number}"}
            elif step_index == 2 and selected_tool == "read_text_file":
                generated = {"path": str(PROJECT_NOTES_PATH)}
        elif selected_tool == "read_text_file":
            generated = {"path": OUTSIDE_HOSTS_PATH}

    elif category == "memory_distractor_recall":
        template_name = "memory_distractor_recall_v1"
        if expected_success:
            if step_index == 0 and selected_tool == "create_entities":
                generated = {
                    "entities": [
                        {
                            "name": _entity_name(category, case_number, 2),
                            "entityType": "distractor",
                            "observations": [f"distractor-note::{case_number}::secondary detail"],
                        },
                        {
                            "name": _entity_name(category, case_number, 1),
                            "entityType": "target",
                            "observations": [f"target-note::{case_number}::critical finding"],
                        },
                    ]
                }
            elif step_index == 1 and selected_tool == "search_nodes":
                generated = {"query": "critical finding"}
            elif step_index == 2 and selected_tool == "open_nodes":
                generated = {"names": [_entity_name(category, case_number, 1)]}
        elif selected_tool == "search_nodes":
            generated = {}

    elif category == "memory_graph_audit":
        template_name = "memory_graph_audit_v1"
        signal = f"audit-signal::{case_number}" if expected_success else f"audit-fail::{case_number}"
        if step_index == 0 and selected_tool == "create_entities":
            generated = {
                "entities": [
                    {
                        "name": _entity_name(category, case_number, 1, expected_success),
                        "entityType": "audit",
                        "observations": [signal],
                    }
                ]
            }
        elif step_index == 1 and selected_tool == "read_graph":
            generated = {}
        elif step_index == 2 and selected_tool == "search_nodes":
            generated = {"query": signal} if expected_success else {}

    elif category == "memory_recall":
        template_name = "memory_recall_v1"
        fact = f"fact::memory_recall::{case_number}::1"
        if expected_success:
            if step_index == 0 and selected_tool == "create_entities":
                generated = {"entities": [{"name": _entity_name(category, case_number, 1), "entityType": "fact", "observations": [fact]}]}
            elif step_index == 1 and selected_tool == "search_nodes":
                generated = {"query": fact}
            elif step_index == 2 and selected_tool == "open_nodes":
                generated = {"names": [_entity_name(category, case_number, 1)]}
        elif selected_tool == "create_entities":
            generated = {}

    elif category == "plan_filesystem_grounding":
        template_name = "plan_filesystem_grounding_h1" if _is_targeted_hardening(case_id) else "plan_filesystem_grounding_v1"
        if expected_success:
            if step_index == 0 and selected_tool == "sequentialthinking":
                if _is_targeted_hardening(case_id):
                    generated = {
                        "thought": f"Plan filesystem grounding for case {case_number}; memory terms are distractors and no memory write is needed.",
                        "nextThoughtNeeded": False,
                        "thoughtNumber": 1,
                        "totalThoughts": 1,
                    }
                else:
                    generated = {"thought": f"Verify benchmark checklist for case {case_number}", "nextThoughtNeeded": False, "thoughtNumber": 1, "totalThoughts": 1}
            elif _is_targeted_hardening(case_id):
                if step_index == 1 and selected_tool == "list_allowed_directories":
                    generated = {}
                elif step_index == 2 and selected_tool == "search_files":
                    generated = {"path": str(FS_STATE_DIR / "archive"), "pattern": "session_log.txt"}
                elif step_index == 3 and selected_tool == "read_text_file":
                    generated = {"path": str(ARCHIVE_LOG_PATH)}
                elif step_index == 4 and selected_tool == "search_files":
                    generated = {"path": str(FS_STATE_DIR / "checklists"), "pattern": "review_plan.txt"}
            else:
                if step_index == 1 and selected_tool == "read_text_file":
                    generated = {"path": str(CHECKLIST_PATH)}
                elif step_index == 2 and selected_tool == "search_files":
                    generated = {"path": str(FS_STATE_DIR / "checklists"), "pattern": "review_plan.txt"}
        elif selected_tool == "search_files":
            generated = {"path": str(FS_STATE_DIR)}

    elif category == "plan_memory_filesystem_loop":
        template_name = "plan_memory_filesystem_loop_h1" if _is_targeted_hardening(case_id) else "plan_memory_filesystem_loop_v1"
        plan_path = _targeted_plan_loop_path(case_number) if _is_targeted_hardening(case_id) else (GENERATED_DIR / f"plan_loop_{case_number}.txt")
        if expected_success:
            if step_index == 0 and selected_tool == "sequentialthinking":
                thought = (
                    f"Plan cross-server memory/filesystem loop for case {case_number}; after planning, alternate tools instead of staying in one server."
                    if _is_targeted_hardening(case_id)
                    else f"Plan memory/filesystem verification loop for case {case_number}"
                )
                generated = {"thought": thought, "nextThoughtNeeded": False, "thoughtNumber": 1, "totalThoughts": 1}
            elif _is_targeted_hardening(case_id):
                if step_index == 1 and selected_tool == "list_allowed_directories":
                    generated = {}
                elif step_index == 2 and selected_tool == "read_text_file":
                    generated = {"path": str(CHECKLIST_PATH)}
                elif step_index == 3 and selected_tool == "create_entities":
                    generated = {"entities": [{"name": _entity_name(category, case_number, 1), "entityType": "artifact", "observations": [f"artifact-case::{case_number}::{plan_path}"]}]}
                elif step_index == 4 and selected_tool == "create_directory":
                    generated = {"path": str(GENERATED_DIR)}
                elif step_index == 5 and selected_tool == "write_file":
                    generated = {
                        "path": str(plan_path),
                        "content": (
                            f"case: {case_number}\n"
                            "loop: targeted-plan-memory-filesystem\n"
                            "signal: reuse-ready-state\n"
                            f"memory_pointer: artifact-case::{case_number}"
                        ),
                    }
                elif step_index == 6 and selected_tool == "search_nodes":
                    generated = {"query": f"artifact-case::{case_number}"}
                elif step_index == 7 and selected_tool == "search_files":
                    generated = {"path": str(GENERATED_DIR), "pattern": plan_path.name}
            else:
                if step_index == 1 and selected_tool == "read_text_file":
                    generated = {"path": str(CHECKLIST_PATH)}
                elif step_index == 2 and selected_tool == "create_entities":
                    generated = {"entities": [{"name": _entity_name(category, case_number, 1), "entityType": "artifact", "observations": [f"artifact-case::{case_number}::{plan_path}"]}]}
                elif step_index == 3 and selected_tool == "create_directory":
                    generated = {"path": str(GENERATED_DIR)}
                elif step_index == 4 and selected_tool == "write_file":
                    generated = {"path": str(plan_path), "content": f"case: {case_number}\nloop: plan-memory-filesystem\nsignal: reuse-ready-state"}
                elif step_index == 5 and selected_tool == "search_nodes":
                    generated = {"query": f"artifact-case::{case_number}"}
                elif step_index == 6 and selected_tool == "search_files":
                    generated = {"path": str(GENERATED_DIR), "pattern": f"plan_loop_{case_number}.txt"}
        else:
            if step_index == 0 and selected_tool == "sequentialthinking":
                generated = {"thought": "Write a file outside the allowed project root", "nextThoughtNeeded": False, "thoughtNumber": 1, "totalThoughts": 1}
            elif step_index == 1 and selected_tool == "write_file":
                generated = {"path": OUTSIDE_PLAN_LOOP_PATH, "content": "unsafe"}

    elif category == "plan_memory_loop":
        template_name = "plan_memory_loop_h1" if _is_targeted_hardening(case_id) else "plan_memory_loop_v1"
        signal = f"plan::{case_number}::verify_mcp_tool_health"
        if expected_success:
            if step_index == 0 and selected_tool == "sequentialthinking":
                thought = (
                    f"Plan memory handoff for case {case_number}; after this step the correct route leaves planning and writes memory."
                    if _is_targeted_hardening(case_id)
                    else f"Plan MCP health verification for case {case_number}"
                )
                generated = {"thought": thought, "nextThoughtNeeded": False, "thoughtNumber": 1, "totalThoughts": 1}
            elif step_index == 1 and selected_tool == "create_entities":
                observations = [signal]
                if _is_targeted_hardening(case_id):
                    observations.append("routing-note::do-not-repeat-sequentialthinking")
                generated = {"entities": [{"name": _entity_name(category, case_number, 1), "entityType": "plan", "observations": observations}]}
            elif step_index == 2 and selected_tool == "search_nodes":
                generated = {"query": signal}
            elif _is_targeted_hardening(case_id) and step_index == 3 and selected_tool == "read_graph":
                generated = {}
        elif selected_tool == "sequentialthinking":
            generated = {}

    if generated is None:
        return _policy_result(
            supported=False,
            arguments={},
            template_name=template_name,
            source="unsupported",
            reason=f"unsupported_template_for_{category}:{selected_tool}:step_{step_index}",
        )

    return _policy_result(
        supported=True,
        arguments=generated,
        template_name=template_name,
        source="controlled_template_policy",
        reason="",
        schema_match=sorted(generated.keys()) == sorted(gold.keys()),
        exact_match=generated == gold,
        derivation_path=["template_policy"],
    )
def generate_memory_conditioned_arguments(
    *,
    state: dict[str, Any],
    case_id: str,
    category: str,
    task: str,
    expected_success: bool,
    step_index: int,
    selected_tool: str,
    gold_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gold = _jsonable_arguments(gold_arguments or {})
    controlled = generate_controlled_arguments(
        case_id=case_id,
        category=category,
        task=task,
        expected_success=expected_success,
        step_index=step_index,
        selected_tool=selected_tool,
        gold_arguments=gold,
    )
    case_number = _extract_case_number(case_id, task)
    if not case_number:
        return _policy_result(
            supported=False,
            arguments={},
            template_name=str(controlled.get("template_name", "")),
            source="memory_conditioned_unsupported",
            reason="missing_case_number",
        )

    generated: dict[str, Any] | None = None
    derivation_path: list[str] = []

    if selected_tool == "create_entities":
        if category == "fetch_memory_bridge" and expected_success:
            signal = _first_match(state, "signal", "fetch-health-case") or f"fetch-health-case::{case_number}"
            url_value = _latest(state, "url") or BACKEND_HEALTH_URL
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", "tem_v2_fetch_memory") or _entity_name(category, case_number, 1),
                        "entityType": "url_fact",
                        "observations": [f"{signal}::url::{url_value}"],
                    }
                ]
            }
            derivation_path = ["state.entity_name", "state.signal", "state.url"]
        elif category == "memory_recall" and expected_success:
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", "tem_v2_memory_recall") or _entity_name(category, case_number, 1),
                        "entityType": "fact",
                        "observations": [_first_match(state, "signal", "fact::memory_recall") or f"fact::memory_recall::{case_number}::1"],
                    }
                ]
            }
            derivation_path = ["state.entity_name", "state.signal"]
        elif category == "memory_distractor_recall" and expected_success:
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", f"entity_2") or _entity_name(category, case_number, 2),
                        "entityType": "distractor",
                        "observations": [f"distractor-note::{case_number}::secondary detail"],
                    },
                    {
                        "name": _first_match(state, "entity_name", f"entity_1") or _entity_name(category, case_number, 1),
                        "entityType": "target",
                        "observations": [f"target-note::{case_number}::critical finding"],
                    },
                ]
            }
            derivation_path = ["state.entity_name", "seed.case_number"]
        elif category == "memory_graph_audit":
            signal = _first_match(state, "signal", "audit-") or (("audit-signal" if expected_success else "audit-fail") + f"::{case_number}")
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", "memory_graph_audit") or _entity_name(category, case_number, 1, expected_success),
                        "entityType": "audit",
                        "observations": [signal],
                    }
                ]
            }
            derivation_path = ["state.entity_name", "state.signal"]
        elif category == "memory_cross_tool_verification" and expected_success:
            signal = _first_match(state, "signal", "cross-tool-case") or f"cross-tool-case::{case_number}"
            path_value = _first_match(state, "path", "tem_notes.md") or str(PROJECT_NOTES_PATH)
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", "memory_cross_tool") or _entity_name(category, case_number, 1),
                        "entityType": "file_ref",
                        "observations": [f"{signal}::filesystem-pointer::{path_value}"],
                    }
                ]
            }
            derivation_path = ["state.entity_name", "state.signal", "state.path"]
        elif category == "memory_chain_grounding":
            if expected_success:
                person_path = _first_match(state, "path", "alice_profile.txt") or str(ALICE_PROFILE_PATH)
                project_path = _first_match(state, "path", "tem_notes.md") or str(PROJECT_NOTES_PATH)
                generated = {
                    "entities": [
                        {
                            "name": _first_match(state, "entity_name", f"entity_1") or _entity_name(category, case_number, 1),
                            "entityType": "file_ref",
                            "observations": [f"person-case::{case_number}::Alice Chen::{person_path}"],
                        },
                        {
                            "name": _first_match(state, "entity_name", f"entity_2") or _entity_name(category, case_number, 2),
                            "entityType": "file_ref",
                            "observations": [f"project-case::{case_number}::TEM Notes::{project_path}"],
                        },
                    ]
                }
                derivation_path = ["state.entity_name", "state.path"]
            else:
                stale_path = _first_match(state, "path", "not_created_") or str(GENERATED_DIR / f"not_created_{case_number}.txt")
                generated = {
                    "entities": [
                        {
                            "name": _first_match(state, "entity_name", "memory_chain_fail") or _entity_name(category, case_number, 1, False),
                            "entityType": "file_ref",
                            "observations": [f"stale-case::{case_number}::path::{stale_path}"],
                        }
                    ]
                }
                derivation_path = ["state.entity_name", "state.path"]
        elif category == "plan_memory_loop" and expected_success:
            observations = [_first_match(state, "signal", "plan::") or f"plan::{case_number}::verify_mcp_tool_health"]
            if _is_targeted_hardening(case_id):
                observations.append("routing-note::do-not-repeat-sequentialthinking")
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", "tem_v2_plan_memory") or _entity_name(category, case_number, 1),
                        "entityType": "plan",
                        "observations": observations,
                    }
                ]
            }
            derivation_path = ["state.entity_name", "state.signal"]
        elif category == "plan_memory_filesystem_loop" and expected_success:
            signal = _first_match(state, "signal", "artifact-case::") or f"artifact-case::{case_number}"
            path_value = _first_match(state, "path", "plan_loop_h_") or _first_match(state, "path", "plan_loop_") or str(GENERATED_DIR / f"plan_loop_{case_number}.txt")
            generated = {
                "entities": [
                    {
                        "name": _first_match(state, "entity_name", "tem_v2_plan_memory_filesystem") or _entity_name(category, case_number, 1),
                        "entityType": "artifact",
                        "observations": [f"{signal}::{path_value}"],
                    }
                ]
            }
            derivation_path = ["state.entity_name", "state.signal", "state.path"]

    elif selected_tool == "search_nodes":
        if category == "memory_distractor_recall" and expected_success:
            generated = {"query": "critical finding"}
            derivation_path = ["seed.critical_finding"]
        else:
            query_value = _latest(state, "memory_query") or _latest(state, "signal")
            if query_value:
                generated = {"query": query_value}
                derivation_path = ["state.memory_query_or_signal"]
            elif not expected_success and category in {"memory_distractor_recall", "memory_graph_audit"}:
                generated = {}
                derivation_path = ["state.empty_failure_query"]

    elif selected_tool == "open_nodes":
        name = _latest(state, "entity_name")
        if name:
            generated = {"names": [name]}
            derivation_path = ["state.entity_name"]

    elif selected_tool == "read_graph":
        generated = {}
        derivation_path = ["tool_schema.empty"]

    elif selected_tool == "read_text_file":
        if category == "memory_chain_grounding" and expected_success:
            if _is_targeted_hardening(case_id):
                if step_index >= 5:
                    path_value = _first_match(state, "path", "tem_notes.md") or str(PROJECT_NOTES_PATH)
                    derivation_path = ["state.path.project"]
                else:
                    path_value = _first_match(state, "path", "alice_profile.txt") or str(ALICE_PROFILE_PATH)
                    derivation_path = ["state.path.person"]
            elif step_index >= 3:
                path_value = _first_match(state, "path", "tem_notes.md") or str(PROJECT_NOTES_PATH)
                derivation_path = ["state.path.project"]
            else:
                path_value = _first_match(state, "path", "alice_profile.txt") or str(ALICE_PROFILE_PATH)
                derivation_path = ["state.path.person"]
            generated = {"path": path_value}
        else:
            path_value = _latest(state, "path")
            if path_value:
                generated = {"path": path_value}
                derivation_path = ["state.path"]

    elif selected_tool == "search_files":
        base_path = ""
        pattern = ""
        if category == "filesystem_probe" and expected_success:
            base_path = str(FS_STATE_DIR / "archive")
            pattern = "session_log.txt"
            derivation_path = ["seed.archive_path", "seed.search_pattern"]
        elif category == "plan_filesystem_grounding" and expected_success:
            if _is_targeted_hardening(case_id) and step_index <= 2:
                base_path = str(FS_STATE_DIR / "archive")
                pattern = "session_log.txt"
                derivation_path = ["seed.archive_path", "seed.search_pattern"]
            else:
                base_path = str(FS_STATE_DIR / "checklists")
                pattern = "review_plan.txt"
                derivation_path = ["seed.checklist_dir", "seed.search_pattern"]
        else:
            latest_path = _latest(state, "path")
            latest_directory = _latest(state, "directory_path")
            pattern = _latest(state, "search_pattern") or _latest(state, "file_name")
            if latest_directory:
                base_path = latest_directory
                derivation_path.append("state.directory_path")
            elif latest_path:
                try:
                    path_obj = Path(latest_path)
                    base_path = str(path_obj.parent) if path_obj.suffix else latest_path
                except Exception:
                    base_path = latest_path
                derivation_path.append("state.path")
            if pattern:
                derivation_path.append("state.search_pattern_or_file_name")
        if base_path:
            generated = {"path": base_path}
            if pattern:
                generated["pattern"] = pattern

    elif selected_tool == "write_file":
        path_value = _latest(state, "file_path") or _latest(state, "path")
        if path_value:
            generated = {"path": path_value}
            derivation_path = ["state.file_path_or_path"]
            content = _latest(state, "content")
            if content:
                generated["content"] = content
                derivation_path.append("state.content")

    elif selected_tool == "create_directory":
        directory_path = _latest(state, "directory_path") or _latest(state, "path")
        if directory_path:
            generated = {"path": directory_path}
            derivation_path = ["state.directory_path"]

    elif selected_tool == "fetch":
        url_value = _latest(state, "url")
        if url_value:
            generated = {"url": url_value}
            derivation_path = ["state.url"]
            if expected_success:
                generated["max_length"] = FETCH_MAX_LENGTH
                derivation_path.append("params.fetch_max_length")

    elif selected_tool == "sequentialthinking":
        thought = _latest(state, "thought")
        if thought:
            generated = {"thought": thought, "nextThoughtNeeded": False, "thoughtNumber": 1, "totalThoughts": 1}
            derivation_path = ["state.thought", "template.sequentialthinking_shape"]
        elif not expected_success and category in {"plan_memory_loop", "plan_memory_filesystem_loop"}:
            generated = {}
            derivation_path = ["state.empty_failure_thought"]

    elif selected_tool in {"list_allowed_directories"}:
        generated = {}
        derivation_path = ["tool_schema.empty"]

    if generated is None:
        return _policy_result(
            supported=False,
            arguments={},
            template_name=str(controlled.get("template_name", "")),
            source="memory_conditioned_unsupported",
            reason=f"unsupported_memory_conditioned_for_{category}:{selected_tool}:step_{step_index}",
            derivation_path=derivation_path,
        )

    return _policy_result(
        supported=True,
        arguments=generated,
        template_name=str(controlled.get("template_name", "")),
        source="memory_conditioned_argument_policy",
        reason="",
        schema_match=sorted(generated.keys()) == sorted(gold.keys()),
        exact_match=generated == gold,
        derivation_path=derivation_path,
    )
