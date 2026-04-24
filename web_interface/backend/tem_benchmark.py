"""
TEM benchmark for the probabilistic Tool Execution Memory (TEM) module.

Design goals:
- Keep benchmark execution isolated from production artifacts.
- Exercise all algorithmic components with deterministic checks.
- Return a compact JSON report for API and UI consumption.
"""

from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import tool_execution_memory as tem_mod


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    details: str = ""


@dataclass
class BenchmarkReport:
    timestamp: str = ""
    duration_ms: float = 0.0
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _SandboxTEM:
    """Run TEM in a project-local temporary sandbox, never in production artifacts."""

    def __init__(self):
        project_tmp_root = (tem_mod.ARTIFACTS_DIR / "tmp").resolve()
        project_tmp_root.mkdir(parents=True, exist_ok=True)

        unique = f"tem_bench_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        self._tmpdir = project_tmp_root / unique
        self._recipes_dir = self._tmpdir / "recipes"
        self._guards_dir = self._tmpdir / "guards"
        self._centroids_path = self._tmpdir / "error_centroids.json"

        self._orig_recipes_dir = tem_mod.RECIPES_DIR
        self._orig_guards_dir = tem_mod.GUARDS_DIR
        self._orig_centroids_path = tem_mod.CENTROIDS_PATH

    def __enter__(self) -> "tem_mod.ToolExecutionMemory":
        self._recipes_dir.mkdir(parents=True, exist_ok=True)
        self._guards_dir.mkdir(parents=True, exist_ok=True)

        tem_mod.RECIPES_DIR = self._recipes_dir
        tem_mod.GUARDS_DIR = self._guards_dir
        tem_mod.CENTROIDS_PATH = self._centroids_path

        return tem_mod.ToolExecutionMemory()

    def __exit__(self, *exc_info):
        tem_mod.RECIPES_DIR = self._orig_recipes_dir
        tem_mod.GUARDS_DIR = self._orig_guards_dir
        tem_mod.CENTROIDS_PATH = self._orig_centroids_path

        # Retry delete a few times because Windows file handles can release lazily.
        for _ in range(3):
            try:
                shutil.rmtree(self._tmpdir, ignore_errors=True)
                break
            except PermissionError:
                time.sleep(0.05)


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def scenario_recipe_precision() -> ScenarioResult:
    with _SandboxTEM() as tem:
        event_a = tem.after_tool_call(
            client_id="bench",
            tool_name="tool_a",
            arguments={"x": "1", "y": "2"},
            result={"ok": True},
            success=True,
            server_name="srv1",
            task_description="recipe bench",
        )
        tem.clear_pending_steps("bench")

        event_b = tem.after_tool_call(
            client_id="bench",
            tool_name="tool_a",
            arguments={"x": "1", "y": "2"},
            result={"ok": True},
            success=True,
            server_name="srv1",
            task_description="recipe bench repeat",
        )
        tem.clear_pending_steps("bench")

        event_diff = tem.after_tool_call(
            client_id="bench",
            tool_name="tool_a",
            arguments={"x": "1", "z": "new_param"},
            result={"ok": True},
            success=True,
            server_name="srv1",
            task_description="recipe bench diff params",
        )
        tem.clear_pending_steps("bench")

        event_fail = tem.after_tool_call(
            client_id="bench",
            tool_name="tool_a",
            arguments={"x": "1", "y": "2"},
            result={"error": "file not found"},
            success=False,
            error_type="BusinessError",
            error_message="file not found",
            server_name="srv1",
            task_description="recipe bench fail",
        )

    checks = {
        "success_creates_recipe": "recipe_learned" in event_a,
        "repeat_increments_count": event_b.get("recipe_learned", {}).get("success_count", 0) == 2,
        "different_params_new_recipe": (
            event_a.get("recipe_learned", {}).get("id")
            != event_diff.get("recipe_learned", {}).get("id")
        ),
        "failure_no_recipe": "recipe_learned" not in event_fail,
        "failure_creates_guard": "guard_created" in event_fail,
    }

    passed_count = sum(checks.values())
    total = len(checks)
    return ScenarioResult(
        name="scenario_recipe_precision",
        passed=passed_count == total,
        metrics={"accuracy": round(passed_count / total, 3), "correct": passed_count, "total": total},
        details=json.dumps(checks, ensure_ascii=False),
    )


def scenario_guard_bayesian_precision() -> ScenarioResult:
    with _SandboxTEM() as tem:
        for _ in range(2):
            tem.after_tool_call(
                client_id="bench",
                tool_name="tool_x",
                arguments={"path": "/bad"},
                result=None,
                success=False,
                error_type="NotFound",
                error_message="path not found",
                server_name="srv_a",
                task_description="guard bench",
            )

        block_same = tem.before_tool_call("tool_x", {"path": "/bad"}, "srv_a")
        block_diff_val = tem.before_tool_call("tool_x", {"path": "/good"}, "srv_a")
        block_diff_srv = tem.before_tool_call("tool_x", {"path": "/bad"}, "srv_b")

        guard = next(iter(tem.guards.guards.values()))
        prob_before = guard.posterior_failure_prob

        tem.after_tool_call(
            client_id="bench",
            tool_name="tool_x",
            arguments={"path": "/bad"},
            result={"ok": True},
            success=True,
            server_name="srv_a",
            task_description="guard success",
        )
        prob_after = guard.posterior_failure_prob

    checks = {
        "same_params_blocked": block_same is not None,
        "different_value_not_blocked": block_diff_val is None,
        "different_server_not_blocked": block_diff_srv is None,
        "success_weakens_guard": prob_after < prob_before,
    }

    true_positive = 1 if checks["same_params_blocked"] else 0
    false_positive = int(not checks["different_value_not_blocked"]) + int(
        not checks["different_server_not_blocked"]
    )
    precision = true_positive / max(true_positive + false_positive, 1)

    return ScenarioResult(
        name="scenario_guard_bayesian_precision",
        passed=all(checks.values()),
        metrics={
            "precision": round(precision, 3),
            "prob_before": round(prob_before, 3),
            "prob_after": round(prob_after, 3),
        },
        details=json.dumps(checks, ensure_ascii=False),
    )


def scenario_ablation() -> ScenarioResult:
    call_sequence: list[tuple[str, dict[str, Any], str]] = [
        ("flaky_tool", {"q": "test"}, "srv1"),
        ("good_tool", {"data": "hello"}, "srv1"),
        ("flaky_tool", {"q": "test"}, "srv1"),
    ]

    with _SandboxTEM() as tem_on:
        for _ in range(3):
            tem_on.after_tool_call(
                client_id="bench",
                tool_name="flaky_tool",
                arguments={"q": "test"},
                result=None,
                success=False,
                error_type="TimeoutError",
                error_message="timeout after 30s",
                server_name="srv1",
                task_description="ablation fail",
            )

        tem_on.after_tool_call(
            client_id="bench",
            tool_name="good_tool",
            arguments={"data": "hello"},
            result={"success": True},
            success=True,
            server_name="srv1",
            task_description="ablation success",
        )
        tem_on.clear_pending_steps("bench")

        on_blocked = 0
        on_false_blocks = 0
        on_recipe_hints = 0

        for tool, args, srv in call_sequence:
            block = tem_on.before_tool_call(tool, args, srv)
            if block is not None:
                on_blocked += 1
                if tool == "good_tool":
                    on_false_blocks += 1
                continue

            recipe_ctx = tem_on.get_recipes_for_context(f"call {tool}", [tool])
            if recipe_ctx:
                on_recipe_hints += 1

    with _SandboxTEM() as tem_off:
        off_blocked = 0
        for tool, args, srv in call_sequence:
            if tem_off.before_tool_call(tool, args, srv) is not None:
                off_blocked += 1

    avoided = on_blocked - off_blocked
    checks = {
        "avoids_wasteful_calls": avoided > 0,
        "produces_recipe_hints": on_recipe_hints > 0,
        "no_false_block": on_false_blocks == 0,
    }

    return ScenarioResult(
        name="scenario_ablation",
        passed=all(checks.values()),
        metrics={
            "avoided_wasteful_calls": avoided,
            "recipe_hints": on_recipe_hints,
            "false_blocks": on_false_blocks,
        },
        details=json.dumps(checks, ensure_ascii=False),
    )


def scenario_exponential_decay() -> ScenarioResult:
    with _SandboxTEM() as tem:
        for _ in range(2):
            tem.after_tool_call(
                client_id="bench",
                tool_name="decay_tool",
                arguments={"path": "/bad"},
                result=None,
                success=False,
                error_type="NotFound",
                error_message="missing",
                server_name="srv_decay",
                task_description="decay guard",
            )

        guard = next(iter(tem.guards.guards.values()))
        prob_fresh = guard.posterior_failure_prob
        blocks_fresh = guard.should_block()

        guard.last_triggered_at = _iso_days_ago(180)
        prob_decayed = guard.posterior_failure_prob
        blocks_decayed = guard.should_block()

        ev_new = tem.after_tool_call(
            client_id="bench",
            tool_name="fresh_recipe_tool",
            arguments={"x": 1},
            result={"ok": True},
            success=True,
            server_name="srv_decay",
            task_description="fresh recipe",
        )
        tem.clear_pending_steps("bench")

        ev_old = tem.after_tool_call(
            client_id="bench",
            tool_name="stale_recipe_tool",
            arguments={"x": 1, "legacy": True},
            result={"ok": True},
            success=True,
            server_name="srv_decay",
            task_description="old recipe",
        )
        tem.clear_pending_steps("bench")

        fresh_id = ev_new.get("recipe_learned", {}).get("id", "")
        stale_id = ev_old.get("recipe_learned", {}).get("id", "")
        if stale_id in tem.recipes.recipes:
            tem.recipes.recipes[stale_id].last_used_at = _iso_days_ago(180)
        if fresh_id in tem.recipes.recipes:
            tem.recipes.recipes[fresh_id].last_used_at = _iso_days_ago(1)

        stale_freshness = tem.recipes.recipes[stale_id].freshness if stale_id else 0.0
        fresh_freshness = tem.recipes.recipes[fresh_id].freshness if fresh_id else 0.0

    checks = {
        "guard_probability_decays": prob_decayed < prob_fresh,
        "guard_unblocks_after_decay": blocks_fresh and not blocks_decayed,
        "recipe_freshness_order": stale_freshness < fresh_freshness,
    }

    return ScenarioResult(
        name="scenario_exponential_decay",
        passed=all(checks.values()),
        metrics={
            "prob_fresh": round(prob_fresh, 3),
            "prob_decayed": round(prob_decayed, 3),
            "stale_freshness": round(stale_freshness, 3),
            "fresh_freshness": round(fresh_freshness, 3),
        },
        details=json.dumps(checks, ensure_ascii=False),
    )


def scenario_semantic_classifier() -> ScenarioResult:
    with _SandboxTEM():
        classifier = tem_mod.SemanticErrorClassifier()

        samples = [
            ("FileNotFoundError", "No such file: /tmp/a.txt", "resource_not_found"),
            ("NotFound", "path not found: /img/missing.jpg", "resource_not_found"),
            ("PermissionError", "access denied to /etc/shadow", "permission_denied"),
            ("ValueError", "invalid format for date", "invalid_argument"),
            ("TimeoutError", "timeout after 30s", "timeout"),
            ("HTTPError", "429 Too Many Requests", "rate_limit"),
            ("ServerError", "500 internal server error", "server_error"),
            ("ConnectionError", "network unreachable", "network_error"),
            ("ImportError", "module pandas not installed", "dependency_missing"),
            (
                "BusinessError",
                "business logic validation fail",
                "business_logic_error",
            ),
            ("SomeWeirdError", "something unexpected", "unknown"),
        ]

        details: dict[str, dict[str, Any]] = {}
        correct = 0
        for err_type, msg, expected in samples:
            actual_cause, confidence = classifier.classify(err_type, msg)
            actual = actual_cause.value
            ok = actual == expected
            if ok:
                correct += 1
            details[f"{err_type}:{msg}"] = {
                "expected": expected,
                "actual": actual,
                "confidence": round(confidence, 4),
                "ok": ok,
            }

    total = len(samples)
    accuracy = correct / max(total, 1)
    return ScenarioResult(
        name="semantic_error_classifier",
        passed=accuracy >= 0.95,
        metrics={"accuracy": round(accuracy, 3), "correct": correct, "total": total},
        details=json.dumps(details, ensure_ascii=False),
    )


def scenario_betainc_correctness() -> ScenarioResult:
    # Analytic references for integer-shape Beta CDFs.
    refs = [
        (0.5, 1.0, 1.0, 0.5),
        (0.5, 2.0, 1.0, 0.25),
        (0.5, 3.0, 1.0, 0.125),
        (0.5, 1.0, 2.0, 0.75),
        (0.5, 2.0, 2.0, 0.5),
        (0.5, 5.0, 2.0, 0.109375),
        (0.0, 3.0, 2.0, 0.0),
        (1.0, 3.0, 2.0, 1.0),
        (0.3, 2.0, 3.0, 0.3483),
    ]

    details: dict[str, dict[str, Any]] = {}
    max_error = 0.0
    for x, a, b, expected in refs:
        actual = tem_mod.regularized_incomplete_beta(x, a, b)
        error = abs(actual - expected)
        max_error = max(max_error, error)
        details[f"I_{x}({a},{b})"] = {
            "expected": expected,
            "actual": round(actual, 10),
            "error": f"{error:.2e}",
            "ok": error < 1e-6,
        }

    return ScenarioResult(
        name="betainc_correctness",
        passed=max_error < 1e-6,
        metrics={"max_error": f"{max_error:.2e}", "tests": len(refs)},
        details=json.dumps(details, ensure_ascii=False),
    )


def scenario_comparative_experiment() -> ScenarioResult:
    task_sequence = [
        ("resize_image", {"path": "/img/a.jpg", "width": "800"}, "img_srv", True),
        ("resize_image", {"path": "/img/b.jpg", "width": "800"}, "img_srv", True),
        ("resize_image", {"path": "/img/missing.jpg", "width": "800"}, "img_srv", False),
        ("resize_image", {"path": "/img/missing.jpg", "width": "800"}, "img_srv", False),
        ("compress_pdf", {"file": "/doc/report.pdf"}, "doc_srv", True),
        ("resize_image", {"path": "/img/missing.jpg", "width": "800"}, "img_srv", False),
        ("resize_image", {"path": "/img/c.jpg", "width": "800"}, "img_srv", True),
        ("compress_pdf", {"file": "/doc/report.pdf"}, "doc_srv", True),
        ("compress_pdf", {"file": "/doc/broken.pdf"}, "doc_srv", False),
        ("resize_image", {"path": "/img/missing.jpg", "width": "800"}, "img_srv", False),
    ]

    with _SandboxTEM() as tem_on:
        on_blocked = 0
        on_false_blocks = 0
        on_recipe_hints = 0
        on_executed = 0

        for tool, args, srv, should_succeed in task_sequence:
            block = tem_on.before_tool_call(tool, args, srv)
            if block:
                if should_succeed:
                    on_false_blocks += 1
                else:
                    on_blocked += 1
                continue

            on_executed += 1
            recipe_ctx = tem_on.get_recipes_for_context(f"call {tool}", [tool])
            if recipe_ctx:
                on_recipe_hints += 1

            if should_succeed:
                tem_on.after_tool_call(
                    client_id="bench",
                    tool_name=tool,
                    arguments=args,
                    result={"success": True, "data": "ok"},
                    success=True,
                    server_name=srv,
                    task_description=f"comparative {tool}",
                )
                tem_on.clear_pending_steps("bench")
            else:
                tem_on.after_tool_call(
                    client_id="bench",
                    tool_name=tool,
                    arguments=args,
                    result=None,
                    success=False,
                    error_type="ToolError",
                    error_message=f"{tool} failed on args",
                    server_name=srv,
                    task_description=f"comparative {tool} fail",
                )

    with _SandboxTEM() as tem_off:
        off_executed = len(task_sequence)
        off_blocked = 0
        for tool, args, srv, _ in task_sequence:
            if tem_off.before_tool_call(tool, args, srv):
                off_blocked += 1

    avoided = off_executed - on_executed
    total_fail_calls = sum(1 for _, _, _, ok in task_sequence if not ok)
    avoidance_rate = avoided / max(total_fail_calls, 1)

    checks = {
        "avoids_failures": avoided > 0,
        "no_false_blocks": on_false_blocks == 0,
        "gives_recipe_hints": on_recipe_hints > 0,
        "baseline_no_blocks": off_blocked == 0,
    }

    return ScenarioResult(
        name="scenario_comparative_experiment",
        passed=all(checks.values()),
        metrics={
            "total_tasks": len(task_sequence),
            "tem_on_executed": on_executed,
            "tem_off_executed": off_executed,
            "avoided_wasteful_calls": avoided,
            "avoidance_rate": round(avoidance_rate, 3),
            "recipe_hints": on_recipe_hints,
            "false_blocks": on_false_blocks,
        },
        details=json.dumps(checks, ensure_ascii=False),
    )


def scenario_thompson_ranking() -> ScenarioResult:
    random.seed(20260410)

    with _SandboxTEM() as tem:
        proven_id = ""
        risky_id = ""

        for _ in range(12):
            event = tem.after_tool_call(
                client_id="bench",
                tool_name="proven_tool",
                arguments={"q": "test"},
                result={"ok": True},
                success=True,
                server_name="srv_rank",
                task_description="ranking proven",
            )
            proven_id = event.get("recipe_learned", {}).get("id", proven_id)
            tem.clear_pending_steps("bench")

        for _ in range(2):
            event = tem.after_tool_call(
                client_id="bench",
                tool_name="risky_tool",
                arguments={"q": "test"},
                result={"ok": True},
                success=True,
                server_name="srv_rank",
                task_description="ranking risky",
            )
            risky_id = event.get("recipe_learned", {}).get("id", risky_id)
            tem.clear_pending_steps("bench")

        for _ in range(5):
            if risky_id:
                tem.recipes.record_recipe_failure(risky_id)

        n_trials = 120
        observed = 0
        proven_first = 0
        risky_appeared = 0

        for _ in range(n_trials):
            matched = tem.recipes.match_recipes(
                "test ranking proven_tool risky_tool",
                ["proven_tool", "risky_tool"],
            )
            if not matched:
                continue
            observed += 1
            if "proven_tool" in matched[0].tags:
                proven_first += 1
            if any("risky_tool" in r.tags for r in matched):
                risky_appeared += 1

    proven_first_rate = proven_first / max(observed, 1)
    risky_appear_rate = risky_appeared / max(observed, 1)

    checks = {
        "proven_usually_first": proven_first_rate > 0.55,
        "risky_sometimes_appears": risky_appear_rate > 0.1,
        "observed_matches": observed > 0,
    }

    return ScenarioResult(
        name="scenario_thompson_ranking",
        passed=all(checks.values()),
        metrics={
            "proven_first_rate": round(proven_first_rate, 3),
            "risky_appear_rate": round(risky_appear_rate, 3),
            "observed": observed,
            "n_trials": n_trials,
            "proven_recipe_id": proven_id,
            "risky_recipe_id": risky_id,
        },
        details=json.dumps(checks, ensure_ascii=False),
    )


def scenario_a5_ranked_suggestion() -> ScenarioResult:
    with _SandboxTEM() as tem:
        for _ in range(3):
            tem.after_tool_call(
                client_id="bench",
                tool_name="convert_image",
                arguments={"path": "/img/a.jpg", "format": "png"},
                result={"success": True},
                success=True,
                server_name="img_srv",
                task_description="convert format",
            )
            tem.clear_pending_steps("bench")

        tem.after_tool_call(
            client_id="bench",
            tool_name="convert_image",
            arguments={"path": "/img/b.jpg", "preset": "web"},
            result={"success": True},
            success=True,
            server_name="img_srv",
            task_description="convert preset",
        )
        tem.clear_pending_steps("bench")

        event = tem.after_tool_call(
            client_id="bench",
            tool_name="convert_image",
            arguments={"path": "/img/missing.jpg", "format": "png"},
            result=None,
            success=False,
            error_type="ToolError",
            error_message="conversion failed",
            server_name="img_srv",
            task_description="convert failed",
        )

    suggestion = event.get("guard_created", {}).get("suggestion", "")
    idx_format = suggestion.find("format:")
    idx_preset = suggestion.find("preset:")

    checks = {
        "has_ranked_output": "可参考成功配方" in suggestion,
        "format_schema_preferred": idx_format >= 0 and (idx_preset < 0 or idx_format < idx_preset),
    }

    return ScenarioResult(
        name="scenario_a5_ranked_suggestion",
        passed=all(checks.values()),
        metrics={
            "suggestion_length": len(suggestion),
            "format_index": idx_format,
            "preset_index": idx_preset,
        },
        details=json.dumps(checks, ensure_ascii=False),
    )


def run_benchmark() -> dict[str, Any]:
    t0 = time.time()

    scenarios: list[Callable[[], ScenarioResult]] = [
        scenario_recipe_precision,
        scenario_guard_bayesian_precision,
        scenario_ablation,
        scenario_exponential_decay,
        scenario_semantic_classifier,
        scenario_betainc_correctness,
        scenario_comparative_experiment,
        scenario_thompson_ranking,
        scenario_a5_ranked_suggestion,
    ]

    results: list[dict[str, Any]] = []
    for fn in scenarios:
        try:
            result = fn()
        except Exception as exc:
            import traceback

            result = ScenarioResult(
                name=fn.__name__,
                passed=False,
                details=f"Exception: {exc}\n{traceback.format_exc()}",
            )
        results.append(asdict(result))

    duration_ms = round((time.time() - t0) * 1000, 1)
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    report = BenchmarkReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=duration_ms,
        scenarios=results,
        summary={
            "total_scenarios": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total else 0.0,
        },
    )

    return report.to_dict()


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2, ensure_ascii=False))
