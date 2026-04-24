"""
Audit TEM-ToolBench-v2 as a publication-grade internal benchmark.

This script is intentionally strict. It checks dataset structure, split
integrity, category balance, live-tool schema alignment, and result artifacts.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "datasets" / "tem_toolbench_v2"
RESULTS = ROOT / "experiments" / "results"


EXPECTED_TOOLS = {
    ("filesystem", "list_allowed_directories"),
    ("filesystem", "list_directory"),
    ("filesystem", "read_text_file"),
    ("filesystem", "write_file"),
    ("filesystem", "create_directory"),
    ("filesystem", "search_files"),
    ("fetch", "fetch"),
    ("memory", "create_entities"),
    ("memory", "add_observations"),
    ("memory", "search_nodes"),
    ("memory", "open_nodes"),
    ("memory", "read_graph"),
    ("sequential_thinking", "sequentialthinking"),
    ("cdar_mcp", "cdar_compositional_decomposed_adaptive_reasoning"),
}

REQUIRED_EPISODE_FIELDS = {
    "id",
    "task",
    "category",
    "difficulty",
    "tools_available",
    "expected_success",
    "steps",
}

REQUIRED_STEP_FIELDS = {
    "tool",
    "server",
    "arguments",
    "should_succeed",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} invalid json: {exc}") from exc
    return rows


def check_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    ids: set[str] = set()
    category = Counter()
    difficulty = Counter()
    success = Counter()
    failure_causes = Counter()
    tools = Counter()

    for idx, ep in enumerate(rows, start=1):
        missing = REQUIRED_EPISODE_FIELDS - set(ep)
        if missing:
            errors.append(f"episode #{idx} missing fields: {sorted(missing)}")
        eid = str(ep.get("id", ""))
        if not eid:
            errors.append(f"episode #{idx} empty id")
        if eid in ids:
            errors.append(f"duplicate episode id: {eid}")
        ids.add(eid)
        if ep.get("difficulty") not in {"easy", "medium", "hard"}:
            errors.append(f"{eid} invalid difficulty: {ep.get('difficulty')}")
        if not isinstance(ep.get("steps"), list) or not ep.get("steps"):
            errors.append(f"{eid} has no executable steps")
            continue

        category[str(ep.get("category", "unknown"))] += 1
        difficulty[str(ep.get("difficulty", "unknown"))] += 1
        success[str(bool(ep.get("expected_success")))] += 1
        if not bool(ep.get("expected_success")):
            if not ep.get("expected_failure_cause"):
                errors.append(f"{eid} failure episode missing expected_failure_cause")
            failure_causes[str(ep.get("expected_failure_cause", "unknown"))] += 1

        for sidx, st in enumerate(ep["steps"], start=1):
            missing_step = REQUIRED_STEP_FIELDS - set(st)
            if missing_step:
                errors.append(f"{eid} step {sidx} missing fields: {sorted(missing_step)}")
            server = str(st.get("server", ""))
            tool = str(st.get("tool", ""))
            tools[(server, tool)] += 1
            if (server, tool) not in EXPECTED_TOOLS:
                errors.append(f"{eid} step {sidx} uses non-current tool: {server}:{tool}")
            if not isinstance(st.get("arguments", {}), dict):
                errors.append(f"{eid} step {sidx} arguments must be object")
            if not bool(st.get("should_succeed", True)):
                if not st.get("error_type"):
                    errors.append(f"{eid} step {sidx} failing step missing error_type")
                if not st.get("error_message"):
                    errors.append(f"{eid} step {sidx} failing step missing error_message")

    return {
        "ok": not errors,
        "errors": errors[:200],
        "error_count": len(errors),
        "episodes": len(rows),
        "categories": dict(category),
        "difficulty": dict(difficulty),
        "expected_success_distribution": dict(success),
        "failure_causes": dict(failure_causes),
        "tool_step_counts": {f"{server}:{tool}": count for (server, tool), count in tools.items()},
    }


def check_splits(all_rows: list[dict[str, Any]], train: list[dict[str, Any]], dev: list[dict[str, Any]], test: list[dict[str, Any]]) -> dict[str, Any]:
    all_ids = {r["id"] for r in all_rows}
    train_ids = {r["id"] for r in train}
    dev_ids = {r["id"] for r in dev}
    test_ids = {r["id"] for r in test}
    overlaps = {
        "train_dev": sorted(train_ids & dev_ids)[:20],
        "train_test": sorted(train_ids & test_ids)[:20],
        "dev_test": sorted(dev_ids & test_ids)[:20],
    }
    union_ids = train_ids | dev_ids | test_ids
    missing = sorted(all_ids - union_ids)[:20]
    extra = sorted(union_ids - all_ids)[:20]
    return {
        "ok": not any(overlaps.values()) and not missing and not extra and len(union_ids) == len(all_ids),
        "sizes": {"all": len(all_rows), "train": len(train), "dev": len(dev), "test": len(test)},
        "overlaps": overlaps,
        "missing_from_splits": missing,
        "extra_in_splits": extra,
    }


def check_result_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"ok": False, "path": str(path), "reason": "missing"}
    data = json.loads(path.read_text(encoding="utf-8"))
    summary_obj = data.get("summary", {})
    probe_only = bool(data.get("probe_only_mode"))
    if not isinstance(summary_obj, dict) or not summary_obj:
        return {"ok": False, "path": str(path), "reason": "missing_summary"}

    if any(isinstance(v, dict) and "totals" in v for v in summary_obj.values()):
        modes = {k: v for k, v in summary_obj.items() if isinstance(v, dict)}
    else:
        modes = {"single_mode": summary_obj}

    required = ["real_mcp_call_rate", "resolved_step_rate", "step_verification_rate", "totals"]
    per_mode: dict[str, Any] = {}
    strict_ok = True
    for mode_name, summary in modes.items():
        missing = [k for k in required if k not in summary]
        mode_ok = (
            not missing
            and float(summary.get("resolved_step_rate") or 0.0) >= 1.0
            and float(summary.get("step_verification_rate") or 0.0) >= 1.0
        )
        per_mode[mode_name] = {
            "ok": mode_ok,
            "missing_summary_fields": missing,
            "real_mcp_call_rate": summary.get("real_mcp_call_rate"),
            "resolved_step_rate": summary.get("resolved_step_rate"),
            "step_verification_rate": summary.get("step_verification_rate"),
        }
        strict_ok = strict_ok and mode_ok

    strict_ok = strict_ok and (not probe_only) and bool(data.get("dataset_manifest")) and bool(data.get("provenance"))
    policy_signal = {}
    if all(name in modes for name in ("baseline", "recipe_only", "guard_only", "full_tem")):
        baseline = modes["baseline"]
        recipe_only = modes["recipe_only"]
        guard_only = modes["guard_only"]
        full_tem = modes["full_tem"]
        policy_signal = {
            "baseline_vs_recipe_success_delta": round(
                float(recipe_only.get("actual_episode_success_rate") or 0.0)
                - float(baseline.get("actual_episode_success_rate") or 0.0),
                4,
            ),
            "baseline_vs_guard_blocked_delta": round(
                float(guard_only.get("blocked_call_rate") or 0.0)
                - float(baseline.get("blocked_call_rate") or 0.0),
                4,
            ),
            "baseline_vs_full_success_delta": round(
                float(full_tem.get("actual_episode_success_rate") or 0.0)
                - float(baseline.get("actual_episode_success_rate") or 0.0),
                4,
            ),
            "recipe_only_behaviorally_distinct": bool(
                abs(
                    float(recipe_only.get("actual_episode_success_rate") or 0.0)
                    - float(baseline.get("actual_episode_success_rate") or 0.0)
                ) > 0.0
                or abs(
                    float(recipe_only.get("avg_tool_calls") or 0.0)
                    - float(baseline.get("avg_tool_calls") or 0.0)
                ) > 0.0
            ),
            "guard_only_behaviorally_distinct": bool(
                abs(
                    float(guard_only.get("blocked_call_rate") or 0.0)
                    - float(baseline.get("blocked_call_rate") or 0.0)
                ) > 0.0
            ),
        }
    return {
        "ok": strict_ok,
        "path": str(path),
        "modes": per_mode,
        "has_dataset_manifest": bool(data.get("dataset_manifest")),
        "has_provenance": bool(data.get("provenance")),
        "probe_only_mode": probe_only,
        "max_steps": data.get("provenance", {}).get("max_steps"),
        "dataset_max_steps": data.get("dataset_manifest", {}).get("dataset_max_steps"),
        "policy_signal": policy_signal,
    }


def main() -> None:
    report: dict[str, Any] = {"ok": False, "checks": {}}
    paths = {
        "all": DATA_DIR / "tem_toolbench_v2.jsonl",
        "train": DATA_DIR / "tem_toolbench_v2_train.jsonl",
        "dev": DATA_DIR / "tem_toolbench_v2_dev.jsonl",
        "test": DATA_DIR / "tem_toolbench_v2_test.jsonl",
        "meta": DATA_DIR / "tem_toolbench_v2_meta.json",
    }
    missing = [str(p) for p in paths.values() if not p.exists()]
    report["checks"]["files_present"] = {"ok": not missing, "missing": missing}
    if missing:
        out = RESULTS / "internal_benchmark_audit.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(1)

    all_rows = load_jsonl(paths["all"])
    train = load_jsonl(paths["train"])
    dev = load_jsonl(paths["dev"])
    test = load_jsonl(paths["test"])
    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))

    report["checks"]["dataset_schema"] = check_rows(all_rows)
    report["checks"]["split_integrity"] = check_splits(all_rows, train, dev, test)
    report["checks"]["meta_consistency"] = {
        "ok": meta.get("total_episodes") == len(all_rows)
        and meta.get("splits", {}).get("train") == len(train)
        and meta.get("splits", {}).get("dev") == len(dev)
        and meta.get("splits", {}).get("test") == len(test),
        "meta_total": meta.get("total_episodes"),
        "meta_splits": meta.get("splits"),
    }
    dataset_max_steps = max((len(ep.get("steps", [])) for ep in all_rows), default=0)
    report["checks"]["dataset_step_budget"] = {
        "ok": meta.get("max_steps_required") == dataset_max_steps,
        "meta_max_steps_required": meta.get("max_steps_required"),
        "observed_dataset_max_steps": dataset_max_steps,
    }
    report["checks"]["live_summary_artifact"] = check_result_summary(RESULTS / "tem_live_mcp_eval_summary.json")

    report["ok"] = all(v.get("ok", False) for v in report["checks"].values())
    out = RESULTS / "internal_benchmark_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
