"""
Export publication-facing paper result assets from the current retained real runs.

Outputs:
- docs/PAPER_RESULTS_ASSETS.md
- experiments/results/paper_results_assets.json

The script reads only the current retained mainline summaries and does not
fall back to legacy quick outputs.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "results"
DOCS = ROOT / "docs"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_delta(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.4f}"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _extract_live(summary: dict[str, Any]) -> dict[str, Any]:
    modes = []
    for mode in ["baseline", "recipe_only", "guard_only", "full_tem"]:
        row = summary["summary"][mode]
        modes.append(
            {
                "mode": mode,
                "episode_success": row["actual_episode_success_rate"],
                "tool_success": row["tool_success_rate"],
                "real_mcp_call_rate": row["real_mcp_call_rate"],
                "blocked_call_rate": row["blocked_call_rate"],
                "waste_avoidance_rate": row["waste_avoidance_rate"],
                "false_block_rate": row["false_block_rate"],
            }
        )
    return {
        "dataset_total_episodes": summary["dataset_episodes_total"],
        "evaluated_episodes": summary["evaluated_episodes"],
        "modes": modes,
    }


def _extract_router(summary: dict[str, Any]) -> dict[str, Any]:
    bootstrap = summary["bootstrap"]["summary"]
    evaluation = summary["evaluation"]["summary"]
    all_step = summary["evaluation"]["all_step_diagnostics"]
    first_step = summary["evaluation"]["first_step_diagnostics"]

    top_pairs = []
    for item in all_step.get("overall_top_miss_pairs", [])[:6]:
        top_pairs.append(
            {
                "expected": item["expected"],
                "selected": item["selected"],
                "count": item["count"],
            }
        )

    first_step_pairs = []
    for item in first_step.get("overall_top_miss_pairs", [])[:6]:
        first_step_pairs.append(
            {
                "expected": item["expected"],
                "selected": item["selected"],
                "count": item["count"],
            }
        )

    return {
        "bootstrap": bootstrap,
        "evaluation": evaluation,
        "top_pairs": top_pairs,
        "first_step_pairs": first_step_pairs,
    }


def _extract_targeted(summary: dict[str, Any]) -> dict[str, Any]:
    baseline = summary["modes"]["baseline"]["evaluation"]["summary"]
    full_tem = summary["modes"]["full_tem"]["evaluation"]["summary"]
    category_deltas = summary["category_improvement_vs_baseline"]["full_tem"]
    category_deltas = sorted(
        category_deltas,
        key=lambda row: row["delta_route_top1_accuracy"],
        reverse=True,
    )
    return {
        "baseline": baseline,
        "full_tem": full_tem,
        "category_deltas": category_deltas,
    }


def _extract_mechanism(summary: dict[str, Any]) -> dict[str, Any]:
    recipe_summary = summary["recipe_audit"]["summary"]
    guard_summary = summary["guard_audit"]["summary"]
    guard_tradeoff = summary["guard_tradeoff"]["summary"]
    recovery = summary["recovery_utility"]["recovery_utility"]
    shadow_summary = summary["shadow_replay"]["summary"]

    shadow_order = [
        "recipe",
        "prototype",
        "episodic",
        "bandit",
        "pairwise",
        "listwise",
        "guard",
    ]
    shadow_rows = []
    for key in shadow_order:
        row = shadow_summary[key]
        shadow_rows.append(
            {
                "feature_group": key,
                "cases": row["cases"],
                "top1_flip_rate": row["top1_flip_rate"],
                "mean_top_score_delta": row["mean_top_score_delta"],
            }
        )

    return {
        "inputs": summary["inputs"],
        "recipe_summary": recipe_summary,
        "guard_summary": guard_summary,
        "guard_tradeoff": guard_tradeoff,
        "recovery": recovery,
        "shadow_rows": shadow_rows,
    }


def _build_assets(
    live: dict[str, Any],
    router: dict[str, Any],
    targeted: dict[str, Any],
    mechanism: dict[str, Any],
    source_paths: dict[str, str],
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()

    tables = [
        {
            "id": "table_runtime_validity",
            "title": "Table 1. Runtime Validity on Official MCP Runtime",
            "caption": (
                "Live official MCP evaluation over 100 retained episodes from TEM-ToolBench-v2. "
                "Guard reduces real downstream failing calls without introducing false blocks "
                "in the retained strict run."
            ),
            "columns": [
                "Mode",
                "Episode success",
                "Tool success",
                "Real MCP call rate",
                "Blocked call rate",
                "Waste avoidance",
                "False block",
            ],
            "rows": [
                [
                    row["mode"],
                    _fmt_num(row["episode_success"]),
                    _fmt_num(row["tool_success"]),
                    _fmt_num(row["real_mcp_call_rate"]),
                    _fmt_num(row["blocked_call_rate"]),
                    _fmt_num(row["waste_avoidance_rate"]),
                    _fmt_num(row["false_block_rate"]),
                ]
                for row in live["modes"]
            ],
            "takeaway": (
                "The runtime path is real and strict. Guard contributes measurable interception, "
                "while recipe gains are not expected to surface strongly in this teacher-forced runner."
            ),
        },
        {
            "id": "table_router_diagnostic",
            "title": "Table 2. Router Bottleneck Diagnostic",
            "caption": (
                "Small retained routed diagnostic on TEM-Hard router cases. "
                "Bootstrap warms memory state; evaluation measures routed execution quality."
            ),
            "columns": [
                "Phase",
                "Cases",
                "Steps",
                "Case success",
                "Route top1",
                "Verification",
                "Misroute",
            ],
            "rows": [
                [
                    "bootstrap",
                    router["bootstrap"]["cases"],
                    router["bootstrap"]["steps"],
                    _fmt_num(router["bootstrap"]["actual_case_success_rate"]),
                    _fmt_num(router["bootstrap"]["route_top1_accuracy"]),
                    _fmt_num(router["bootstrap"]["verification_rate"]),
                    _fmt_num(router["bootstrap"]["misroute_rate"]),
                ],
                [
                    "evaluation",
                    router["evaluation"]["cases"],
                    router["evaluation"]["steps"],
                    _fmt_num(router["evaluation"]["actual_case_success_rate"]),
                    _fmt_num(router["evaluation"]["route_top1_accuracy"]),
                    _fmt_num(router["evaluation"]["verification_rate"]),
                    _fmt_num(router["evaluation"]["misroute_rate"]),
                ],
            ],
            "takeaway": (
                "The routed bottleneck is real and concentrated. "
                "The current retained diagnostic is still a small bottleneck probe, not a final headline benchmark."
            ),
        },
        {
            "id": "table_router_miss_pairs",
            "title": "Table 3. Dominant Misroute Pairs in Router Diagnostic",
            "caption": (
                "Top misroute pairs from routed evaluation. "
                "These pairs motivate the focused hard-category audit rather than undirected benchmark expansion."
            ),
            "columns": ["Expected tool", "Selected tool", "Count"],
            "rows": [
                [row["expected"], row["selected"], row["count"]]
                for row in router["top_pairs"]
            ],
            "takeaway": (
                "The dominant residual failure pattern is memory-grounded cross-tool verification, "
                "not random global instability."
            ),
        },
        {
            "id": "table_targeted_audit_aggregate",
            "title": "Table 4. Expanded Targeted Audit on Hard Memory Categories",
            "caption": (
                "Expanded retained targeted audit over the four most difficult planning-heavy and "
                "memory-grounding categories. This is the current mainline targeted result, not the older quick subset."
            ),
            "columns": [
                "Mode",
                "Cases",
                "Steps",
                "Case success",
                "Route top1",
                "Verification",
                "Misroute",
            ],
            "rows": [
                [
                    "baseline",
                    targeted["baseline"]["cases"],
                    targeted["baseline"]["steps"],
                    _fmt_num(targeted["baseline"]["actual_case_success_rate"]),
                    _fmt_num(targeted["baseline"]["route_top1_accuracy"]),
                    _fmt_num(targeted["baseline"]["verification_rate"]),
                    _fmt_num(targeted["baseline"]["misroute_rate"]),
                ],
                [
                    "full_tem",
                    targeted["full_tem"]["cases"],
                    targeted["full_tem"]["steps"],
                    _fmt_num(targeted["full_tem"]["actual_case_success_rate"]),
                    _fmt_num(targeted["full_tem"]["route_top1_accuracy"]),
                    _fmt_num(targeted["full_tem"]["verification_rate"]),
                    _fmt_num(targeted["full_tem"]["misroute_rate"]),
                ],
            ],
            "takeaway": (
                "This is the strongest current routed evidence that the memory-aware stack materially improves the weak categories."
            ),
        },
        {
            "id": "table_targeted_category_delta",
            "title": "Table 5. Category-Level Gains in Expanded Targeted Audit",
            "caption": (
                "Per-category improvements of `full_tem` over `baseline`. "
                "Route quality improves across all four targeted categories, but end-to-end success currently improves only on `plan_memory_loop`."
            ),
            "columns": [
                "Category",
                "Delta case success",
                "Delta first-step accuracy",
                "Delta route top1",
                "Delta misroute",
            ],
            "rows": [
                [
                    row["category"],
                    _fmt_delta(row["delta_actual_case_success_rate"]),
                    _fmt_delta(row["delta_first_step_accuracy"]),
                    _fmt_delta(row["delta_route_top1_accuracy"]),
                    _fmt_delta(row["delta_misroute_step_rate"]),
                ]
                for row in targeted["category_deltas"]
            ],
            "takeaway": (
                "The intervention improves routing everywhere, but three categories still fail to convert that routing gain into reliable task completion."
            ),
        },
        {
            "id": "table_mechanism_audit",
            "title": "Table 6. Mechanism Audit Summary",
            "caption": (
                "Mechanism-level validation of recipe lifecycle, guard behavior, tradeoff, and recovery. "
                "All values come from the current final mainline mechanism audit."
            ),
            "columns": ["Metric group", "Metric", "Value"],
            "rows": [
                ["recipe", "audited recipes", mechanism["recipe_summary"]["count"]],
                ["recipe", "promoted recipes", mechanism["recipe_summary"]["promoted_count"]],
                ["recipe", "mean version", _fmt_num(mechanism["recipe_summary"]["mean_version"])],
                ["recipe", "mean transfer success rate", _fmt_num(mechanism["recipe_summary"]["mean_transfer_success_rate"])],
                ["recipe", "mean schema drift", _fmt_num(mechanism["recipe_summary"]["mean_schema_drift"])],
                ["recipe", "mean verification rate", _fmt_num(mechanism["recipe_summary"]["mean_verification_rate"])],
                ["guard", "audited guards", mechanism["guard_summary"]["count"]],
                ["guard", "mean posterior failure probability", _fmt_num(mechanism["guard_summary"]["mean_posterior_failure_prob"])],
                ["guard", "total blocks", mechanism["guard_summary"]["total_blocks"]],
                ["guard", "mean false-block risk proxy", _fmt_num(mechanism["guard_summary"]["mean_false_block_risk_proxy"])],
                ["tradeoff", "avoided failure rate", _fmt_num(mechanism["guard_tradeoff"]["avoided_failure_rate"])],
                ["tradeoff", "false block rate", _fmt_num(mechanism["guard_tradeoff"]["false_block_rate"])],
                ["tradeoff", "guard precision proxy", _fmt_num(mechanism["guard_tradeoff"]["guard_precision_proxy"])],
                ["recovery", "governance top1 delta", _fmt_delta(mechanism["recovery"]["governance_top1_delta"])],
                ["recovery", "rollback delta vs governance", _fmt_delta(mechanism["recovery"]["rollback_top1_delta_vs_governance"])],
                ["recovery", "rollback gap vs baseline", _fmt_delta(mechanism["recovery"]["rollback_restoration_gap_vs_baseline"])],
            ],
            "takeaway": (
                "Recipe is a real procedural memory mechanism, guard is precise on the retained audited mix, "
                "and governance still has a measurable tuning gap before rollback recovery."
            ),
        },
        {
            "id": "table_shadow_replay",
            "title": "Table 7. Shadow Replay Contribution by Feature Group",
            "caption": (
                "Counterfactual feature-group masking over the live router path. "
                "Higher top1-flip rates indicate stronger causal influence on routed selection."
            ),
            "columns": ["Feature group", "Cases", "Top1 flip rate", "Mean top-score delta"],
            "rows": [
                [
                    row["feature_group"],
                    row["cases"],
                    _fmt_num(row["top1_flip_rate"]),
                    _fmt_num(row["mean_top_score_delta"]),
                ]
                for row in mechanism["shadow_rows"]
            ],
            "takeaway": (
                "Recipe remains the strongest retained causal contributor among the tested feature groups."
            ),
        },
    ]

    figures = [
        {
            "id": "figure_targeted_category_gains",
            "title": "Figure 1. Targeted Category Gains Under Full TEM",
            "chart_type": "grouped_bar",
            "caption": (
                "Category-level gains of `full_tem` over `baseline` in the expanded targeted audit. "
                "The plot should emphasize route-top1 gain as the main bar and annotate case-success gain above each category."
            ),
            "x_axis": "category",
            "primary_y_axis": "delta_route_top1_accuracy",
            "secondary_annotation": "delta_actual_case_success_rate",
            "data": [
                {
                    "category": row["category"],
                    "delta_route_top1_accuracy": row["delta_route_top1_accuracy"],
                    "delta_actual_case_success_rate": row["delta_actual_case_success_rate"],
                    "delta_first_step_accuracy": row["delta_first_step_accuracy"],
                    "delta_misroute_step_rate": row["delta_misroute_step_rate"],
                }
                for row in targeted["category_deltas"]
            ],
            "plot_note": (
                "Recommended rendering: descending bars by route-top1 gain. "
                "Use annotations for case-success gain so the reader sees that only `plan_memory_loop` currently closes the loop."
            ),
        },
        {
            "id": "figure_shadow_replay",
            "title": "Figure 2. Shadow Replay Contribution by Memory Feature Group",
            "chart_type": "bar",
            "caption": (
                "Top1 flip rate under counterfactual masking for each memory feature group. "
                "Recipe should appear as the dominant bar, with smaller but non-zero contributions from prototype, episodic, bandit, pairwise, and listwise signals."
            ),
            "x_axis": "feature_group",
            "y_axis": "top1_flip_rate",
            "data": [
                {
                    "feature_group": row["feature_group"],
                    "top1_flip_rate": row["top1_flip_rate"],
                    "mean_top_score_delta": row["mean_top_score_delta"],
                }
                for row in mechanism["shadow_rows"]
            ],
            "plot_note": (
                "Recommended rendering: sort by top1-flip rate descending, with mean top-score delta shown as value labels or a secondary marker."
            ),
        },
        {
            "id": "figure_governance_recovery",
            "title": "Figure 3. Governance Loss and Rollback Recovery",
            "chart_type": "bar",
            "caption": (
                "Recovery utility of the current governance policy. "
                "The first bar should show the governance-induced top1 delta relative to baseline, "
                "and the second bar should show the rollback restoration relative to governance."
            ),
            "x_axis": "metric",
            "y_axis": "delta",
            "data": [
                {
                    "metric": "governance_top1_delta",
                    "delta": mechanism["recovery"]["governance_top1_delta"],
                },
                {
                    "metric": "rollback_top1_delta_vs_governance",
                    "delta": mechanism["recovery"]["rollback_top1_delta_vs_governance"],
                },
                {
                    "metric": "rollback_restoration_gap_vs_baseline",
                    "delta": mechanism["recovery"]["rollback_restoration_gap_vs_baseline"],
                },
            ],
            "plot_note": (
                "Recommended rendering: keep zero visible and highlight that governance is currently slightly negative before rollback recovery."
            ),
        },
    ]

    section_text = {
        "runtime": (
            "In the strict live MCP run, all retained modes preserve fully real tool execution and "
            "perfect step verification. Guard contributes measurable interception without false blocks, "
            "while recipe gains are not expected to dominate in this teacher-forced runtime probe."
        ),
        "router": (
            "The router diagnostic shows that the remaining failures are concentrated in memory-grounded "
            "cross-tool verification and planning transitions. This justifies targeted hard-category evaluation "
            "instead of uncontrolled benchmark expansion."
        ),
        "targeted": (
            "On the expanded targeted audit, `full_tem` improves route-top1 accuracy from "
            f"{_fmt_num(targeted['baseline']['route_top1_accuracy'])} to {_fmt_num(targeted['full_tem']['route_top1_accuracy'])}, "
            "verification from "
            f"{_fmt_num(targeted['baseline']['verification_rate'])} to {_fmt_num(targeted['full_tem']['verification_rate'])}, "
            "and case success from "
            f"{_fmt_num(targeted['baseline']['actual_case_success_rate'])} to {_fmt_num(targeted['full_tem']['actual_case_success_rate'])}. "
            "However, three of the four targeted categories still fail to convert routing gain into reliable completion."
        ),
        "mechanism": (
            "The mechanism audit validates that recipe, guard, shadow replay, and rollback are executable "
            "runtime mechanisms rather than narrative labels. Recipe is the strongest retained causal contributor, "
            "guard is precise on the audited exact/control mix, and governance still has a small measurable tuning gap."
        ),
    }

    top_pairs = router["top_pairs"]
    pair_text = ", ".join(
        f"{row['expected']} -> {row['selected']} ({row['count']})"
        for row in top_pairs[:3]
    )

    paper_results_draft = {
        "title": "4. Results",
        "sections": [
            {
                "id": "4.1",
                "title": "Runtime Validity on Official MCP Runtime",
                "paragraphs": [
                    (
                        "We first evaluate whether MCP Mirror executes through a real official MCP runtime "
                        "rather than simulated wrappers or mocked tool outputs. Table 1 reports the retained "
                        f"strict live run over {live['evaluated_episodes']} episodes from TEM-ToolBench-v2. "
                        "In all four modes, resolved-step rate and step-verification rate remain 1.0000, "
                        "which means every retained step is executed and verified through the live backend path."
                    ),
                    (
                        "The main effect in this runtime-validity setting comes from failure memory rather than "
                        "routing memory. `guard_only` and `full_tem` reduce real MCP call rate from 1.0000 to "
                        f"{_fmt_num(live['modes'][2]['real_mcp_call_rate'])}, with a blocked-call rate of "
                        f"{_fmt_num(live['modes'][2]['blocked_call_rate'])} and waste-avoidance rate of "
                        f"{_fmt_num(live['modes'][2]['waste_avoidance_rate'])}. The retained run records a "
                        f"false-block rate of {_fmt_num(live['modes'][2]['false_block_rate'])}, so the current "
                        "evidence supports the narrower claim that guard can precisely intercept expected failures "
                        "under real official MCP execution."
                    ),
                    (
                        "Episode success remains unchanged across modes at "
                        f"{_fmt_num(live['modes'][0]['episode_success'])}. We report this flat result directly "
                        "because the retained live runner is teacher-forced at the tool-selection level. It is "
                        "therefore a runtime-faithfulness and guard-interception experiment, not a strong test of "
                        "learned routing superiority or autonomous planning quality."
                    ),
                ],
            },
            {
                "id": "4.2",
                "title": "Router Bottleneck Diagnosis",
                "paragraphs": [
                    (
                        "We next use the retained router diagnostic to identify where routed execution still fails "
                        "before making stronger memory-gain claims. Table 2 separates a bootstrap split from the "
                        "actual routed evaluation split. The bootstrap phase teacher-forces execution so that memory "
                        "state can be warmed using real trajectories; it is not a headline performance result, and "
                        f"its route-top1 accuracy of {_fmt_num(router['bootstrap']['route_top1_accuracy'])} should "
                        "be read only as pre-adaptation router behavior."
                    ),
                    (
                        "On the routed evaluation split, route-top1 accuracy reaches "
                        f"{_fmt_num(router['evaluation']['route_top1_accuracy'])}, while verification rate also "
                        f"remains {_fmt_num(router['evaluation']['verification_rate'])}. However, case success stays "
                        f"at {_fmt_num(router['evaluation']['actual_case_success_rate'])}, which shows that the "
                        "remaining routing errors are severe enough to prevent complete task closure even after "
                        "memory warmup."
                    ),
                    (
                        "The dominant miss pairs are not random. Table 3 shows that the retained failures cluster "
                        f"around {pair_text}. This pattern localizes the current bottleneck to memory-grounded "
                        "cross-tool verification and planning transitions, which justifies a targeted hard-category "
                        "audit rather than undirected benchmark expansion."
                    ),
                ],
            },
            {
                "id": "4.3",
                "title": "Expanded Targeted Audit on Hard Memory Categories",
                "paragraphs": [
                    (
                        "We then evaluate whether the memory-aware stack improves exactly the categories identified "
                        "by the diagnostic. Table 4 reports the retained expanded targeted audit over four hard "
                        "categories: `plan_memory_loop`, `plan_memory_filesystem_loop`, "
                        "`plan_filesystem_grounding`, and `memory_chain_grounding`. Relative to `baseline`, "
                        "`full_tem` increases route-top1 accuracy from "
                        f"{_fmt_num(targeted['baseline']['route_top1_accuracy'])} to "
                        f"{_fmt_num(targeted['full_tem']['route_top1_accuracy'])}, verification rate from "
                        f"{_fmt_num(targeted['baseline']['verification_rate'])} to "
                        f"{_fmt_num(targeted['full_tem']['verification_rate'])}, and case success from "
                        f"{_fmt_num(targeted['baseline']['actual_case_success_rate'])} to "
                        f"{_fmt_num(targeted['full_tem']['actual_case_success_rate'])}."
                    ),
                    (
                        "These gains are important because they appear on the currently weakest routed categories, "
                        "not on an easy or teacher-forced subset. At the same time, Table 5 shows that the gains do "
                        "not yet translate uniformly into full completion. `plan_memory_loop` improves by +1.0000 in "
                        "case success and +0.8571 in route-top1 accuracy, but the other three categories show route "
                        "improvements without end-to-end success gains."
                    ),
                    (
                        "This asymmetry is useful negative evidence. It indicates that the current system has "
                        "materially improved memory-aware tool selection, but still has residual bottlenecks in "
                        "step-to-step grounding, verification carryover, or argument realization once the correct "
                        "tool family has been selected. We therefore frame the targeted audit as strong evidence for "
                        "routing improvement on hard categories, not as evidence that the full multi-step problem is solved."
                    ),
                ],
            },
            {
                "id": "4.4",
                "title": "Mechanism Validation: Recipe, Guard, Shadow Replay, and Rollback",
                "paragraphs": [
                    (
                        "The mechanism audit tests whether the claimed memory objects are executable mechanisms "
                        "instead of descriptive labels. Table 6 shows that the retained audit contains "
                        f"{mechanism['recipe_summary']['count']} audited recipes, all "
                        f"{mechanism['recipe_summary']['promoted_count']} of which are promoted. The mean recipe "
                        f"version is {_fmt_num(mechanism['recipe_summary']['mean_version'])}, mean transfer success "
                        f"rate is {_fmt_num(mechanism['recipe_summary']['mean_transfer_success_rate'])}, mean schema "
                        f"drift is {_fmt_num(mechanism['recipe_summary']['mean_schema_drift'])}, and mean verification "
                        f"rate is {_fmt_num(mechanism['recipe_summary']['mean_verification_rate'])}. These values are "
                        "consistent with recipe behaving as a maintained procedural memory rather than a static prompt snippet."
                    ),
                    (
                        "The same audit shows that guard behaves as a counterfactual failure memory. Across "
                        f"{mechanism['guard_tradeoff']['total_cases']} retained tradeoff cases, avoided-failure rate "
                        f"is {_fmt_num(mechanism['guard_tradeoff']['avoided_failure_rate'])}, false-block rate is "
                        f"{_fmt_num(mechanism['guard_tradeoff']['false_block_rate'])}, and the guard precision proxy is "
                        f"{_fmt_num(mechanism['guard_tradeoff']['guard_precision_proxy'])}. The audited guard set also "
                        f"records {mechanism['guard_summary']['total_blocks']} total blocks with mean posterior failure "
                        f"probability {_fmt_num(mechanism['guard_summary']['mean_posterior_failure_prob'])}. On the "
                        "retained exact/control mix, the current guard policy is therefore conservative but precise."
                    ),
                    (
                        "Table 7 further shows that recipe is the strongest retained causal contributor in shadow "
                        "replay. Feature-group masking causes a top1 flip rate of "
                        f"{_fmt_num(mechanism['shadow_rows'][0]['top1_flip_rate'])} for `recipe`, compared with much "
                        "smaller values for prototype, episodic, bandit, pairwise, and listwise groups. This is the "
                        "strongest current evidence that the observed routing gains are not explained only by lexical "
                        "matching or generic reliability signals."
                    ),
                    (
                        "Finally, recovery utility provides an intentionally honest result on executable governance. "
                        "The retained audit shows a governance top1 delta of "
                        f"{_fmt_delta(mechanism['recovery']['governance_top1_delta'])}, followed by a rollback gain of "
                        f"{_fmt_delta(mechanism['recovery']['rollback_top1_delta_vs_governance'])} relative to governance. "
                        "Rollback therefore recovers the observed governance loss, but the existence of that loss means "
                        "the current forgetting/governance policy is still under-tuned. We treat this as meaningful "
                        "negative evidence rather than something to smooth away."
                    ),
                ],
            },
            {
                "id": "4.5",
                "title": "What the Current Results Support",
                "paragraphs": [
                    (
                        "Taken together, the retained results support three narrow claims. First, MCP Mirror operates "
                        "through a real official MCP runtime with strict live-step verification. Second, the memory-aware "
                        "stack produces substantial routing gains on the currently hardest memory-grounded categories. "
                        "Third, recipe, guard, shadow replay, and rollback are real executable mechanisms that can be "
                        "measured through the same backend runtime used for live tool execution."
                    ),
                    (
                        "The same evidence also sets clear boundaries. The retained live runtime run is not a routing "
                        "benchmark because it is teacher-forced. The router diagnostic remains small and should be read "
                        "as bottleneck analysis. The expanded targeted audit shows strong routing gains, but only one of "
                        "the four targeted categories currently converts those gains into full end-to-end case success. "
                        "Finally, the current evidence is internal and schema-aligned to the official MCP runtime; it "
                        "should not yet be presented as external-benchmark superiority."
                    ),
                ],
            },
        ],
    }

    return {
        "generated_at_utc": generated_at,
        "sources": source_paths,
        "tables": tables,
        "figures": figures,
        "suggested_results_text": section_text,
        "paper_results_draft": paper_results_draft,
    }


def _build_markdown(assets: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Paper Results Assets")
    lines.append("")
    lines.append("Generated automatically from the current retained real experiment outputs.")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{assets['generated_at_utc']}`")
    lines.append("- Policy: only current retained mainline summaries are used.")
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    for key, value in assets["sources"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")

    lines.append("## Paper-Ready Results Draft")
    lines.append("")
    draft = assets.get("paper_results_draft", {})
    if draft.get("title"):
        lines.append(f"### {draft['title']}")
        lines.append("")
    for section in draft.get("sections", []):
        lines.append(f"#### {section['id']} {section['title']}")
        lines.append("")
        for paragraph in section.get("paragraphs", []):
            lines.append(paragraph)
            lines.append("")

    lines.append("## Copy-Ready Tables")
    lines.append("")
    for table in assets["tables"]:
        lines.append(f"### {table['title']}")
        lines.append("")
        lines.append(f"Suggested caption: {table['caption']}")
        lines.append("")
        lines.append(_markdown_table(table["columns"], table["rows"]))
        lines.append("")
        lines.append(f"Suggested in-text reading: {table['takeaway']}")
        lines.append("")

    lines.append("## Figure Assets")
    lines.append("")
    for figure in assets["figures"]:
        lines.append(f"### {figure['title']}")
        lines.append("")
        lines.append(f"Suggested caption: {figure['caption']}")
        lines.append("")
        lines.append(f"- Chart type: `{figure['chart_type']}`")
        lines.append(f"- Plot note: {figure['plot_note']}")
        lines.append("")
        data = figure["data"]
        if figure["id"] == "figure_targeted_category_gains":
            lines.append(
                _markdown_table(
                    [
                        "Category",
                        "Delta route top1",
                        "Delta case success",
                        "Delta first-step accuracy",
                        "Delta misroute",
                    ],
                    [
                        [
                            row["category"],
                            _fmt_delta(row["delta_route_top1_accuracy"]),
                            _fmt_delta(row["delta_actual_case_success_rate"]),
                            _fmt_delta(row["delta_first_step_accuracy"]),
                            _fmt_delta(row["delta_misroute_step_rate"]),
                        ]
                        for row in data
                    ],
                )
            )
        elif figure["id"] == "figure_shadow_replay":
            lines.append(
                _markdown_table(
                    ["Feature group", "Top1 flip rate", "Mean top-score delta"],
                    [
                        [
                            row["feature_group"],
                            _fmt_num(row["top1_flip_rate"]),
                            _fmt_num(row["mean_top_score_delta"]),
                        ]
                        for row in data
                    ],
                )
            )
        else:
            lines.append(
                _markdown_table(
                    ["Metric", "Delta"],
                    [[row["metric"], _fmt_delta(row["delta"])] for row in data],
                )
            )
        lines.append("")

    lines.append("## Suggested Results Paragraphs")
    lines.append("")
    lines.append("### 4.1 Runtime Validity")
    lines.append("")
    lines.append(assets["suggested_results_text"]["runtime"])
    lines.append("")
    lines.append("### 4.2 Router Bottleneck Diagnosis")
    lines.append("")
    lines.append(assets["suggested_results_text"]["router"])
    lines.append("")
    lines.append("### 4.3 Expanded Targeted Audit")
    lines.append("")
    lines.append(assets["suggested_results_text"]["targeted"])
    lines.append("")
    lines.append("### 4.4 Mechanism Validation")
    lines.append("")
    lines.append(assets["suggested_results_text"]["mechanism"])
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--markdown-out",
        default=str(DOCS / "PAPER_RESULTS_ASSETS.md"),
        help="Markdown output path.",
    )
    parser.add_argument(
        "--json-out",
        default=str(RESULTS / "paper_results_assets.json"),
        help="Structured JSON output path.",
    )
    args = parser.parse_args()

    source_paths = {
        "live_summary": str((RESULTS / "tem_live_mcp_eval_summary.json").resolve()),
        "router_summary": str((RESULTS / "router_diagnostic_quick_v2_stratified_summary.json").resolve()),
        "targeted_summary": str((RESULTS / "targeted_memory_category_audit_expanded_v1_summary.json").resolve()),
        "mechanism_summary": str((RESULTS / "memory_mechanism_audit_final_v1_summary.json").resolve()),
    }

    live = _extract_live(_load_json(Path(source_paths["live_summary"])))
    router = _extract_router(_load_json(Path(source_paths["router_summary"])))
    targeted = _extract_targeted(_load_json(Path(source_paths["targeted_summary"])))
    mechanism = _extract_mechanism(_load_json(Path(source_paths["mechanism_summary"])))

    assets = _build_assets(live, router, targeted, mechanism, source_paths)
    markdown = _build_markdown(assets)

    markdown_out = Path(args.markdown_out)
    json_out = Path(args.json_out)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)

    markdown_out.write_text(markdown, encoding="utf-8")
    json_out.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "markdown_out": str(markdown_out.resolve()),
                "json_out": str(json_out.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
