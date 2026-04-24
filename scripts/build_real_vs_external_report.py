"""
Build a publication-facing comparison report:
- Our strict real MCP run metrics (local, reproducible)
- External officially reported numbers (snapshot with sources)

Important:
- This script does not claim cross-benchmark SOTA equivalence.
- It explicitly marks comparability limits.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "results"
REPORTS = ROOT / "experiments" / "reports"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)

    ours_path = RESULTS / "tem_live_mcp_eval_summary.json"
    ours = _load_json(ours_path)
    ours_s = ours.get("summary", {}) if isinstance(ours, dict) else {}
    ours_t = ours_s.get("totals", {}) if isinstance(ours_s, dict) else {}

    generated_at = datetime.now(timezone.utc).isoformat()

    # External snapshot is intentionally explicit and source-bound.
    external_rows: list[dict[str, str]] = [
        {
            "system": "Mem0 (arXiv 2504.19413)",
            "benchmark": "LOCOMO",
            "reported": "+26% relative vs OpenAI Memory; 91% lower p95 latency; >90% token savings",
            "date": "2025-04-28",
            "comparable": "Partial",
            "note": "Different benchmark/protocol than live MCP tool execution.",
            "source": "https://arxiv.org/abs/2504.19413",
        },
        {
            "system": "MemTool (arXiv 2507.21428)",
            "benchmark": "ScaleMCP",
            "reported": "Autonomous mode tool-removal efficiency 90-94% (reasoning LLMs), 0-60% (medium models)",
            "date": "2025-07-29",
            "comparable": "Partial",
            "note": "Metric focuses on tool-context pruning efficiency, not identical to our success/waste metrics.",
            "source": "https://arxiv.org/abs/2507.21428",
        },
        {
            "system": "tau2-bench submission (Claude Opus 4.5, Sierra)",
            "benchmark": "tau2 (airline/retail/telecom/banking_knowledge)",
            "reported": "pass@1: airline 84.0, retail 79.61, telecom 92.32, banking_knowledge 24.74",
            "date": "2026-02-24",
            "comparable": "No (direct)",
            "note": "Interactive simulator benchmark with different tasks and scoring protocol.",
            "source": "https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/claude-opus-4-5_sierra_2026-02-26/submission.json",
        },
        {
            "system": "tau2-bench submission (GPT-5.2, Sierra)",
            "benchmark": "tau2 (airline/retail/telecom/banking_knowledge)",
            "reported": "pass@1: airline 83.0, retail 81.58, telecom 89.69, banking_knowledge 25.52",
            "date": "2026-02-24",
            "comparable": "No (direct)",
            "note": "Different environment and metrics; useful as external anchor, not direct replacement.",
            "source": "https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/gpt-5-2_sierra_2026-02-26/submission.json",
        },
        {
            "system": "tau2-bench submission (Qwen3.5-397B-A17B, Sierra)",
            "benchmark": "tau2 (airline/retail/telecom/banking_knowledge)",
            "reported": "pass@1: airline 81.5, retail 84.43, telecom 97.81, banking_knowledge 9.79",
            "date": "2026-02-27",
            "comparable": "No (direct)",
            "note": "Different simulator and task mix; kept for reviewer-side landscape context.",
            "source": "https://github.com/sierra-research/tau2-bench/blob/main/web/leaderboard/public/submissions/qwen3.5-397b-a17b-think_sierra_2026-03-02/submission.json",
        },
        {
            "system": "LongMemEval benchmark paper",
            "benchmark": "LongMemEval (500 questions, 5 abilities)",
            "reported": "Commercial assistants and long-context LLMs show ~30% accuracy drop on sustained interactions",
            "date": "2025-01-22",
            "comparable": "Partial",
            "note": "Benchmark difficulty anchor; not a method-vs-method table for our current MCP probe run.",
            "source": "https://openreview.net/forum?id=pZiyCaVuti",
        },
        {
            "system": "BFCL V4 leaderboard",
            "benchmark": "BFCL V4",
            "reported": "Official leaderboard and reproducibility checkpoint published",
            "date": "2025-12-16",
            "comparable": "Partial",
            "note": "Function-calling benchmark reference; direct comparison requires running BFCL harness with our system.",
            "source": "https://gorilla.cs.berkeley.edu/leaderboard",
        },
    ]

    lines: list[str] = []
    lines.append("# Real vs External Results Comparison (Strict, Source-Bound)")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{generated_at}`")
    lines.append(f"- Our summary file: `{ours_path.as_posix()}`")
    lines.append("- Policy: only strict real MCP calls are used for our reported numbers.")
    lines.append("")
    lines.append("## Our Strict Real Run")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Run name | `{_fmt(ours.get('name'))}` |")
    lines.append(f"| Runner type | `{_fmt(ours.get('runner_type'))}` |")
    lines.append(f"| Backend | `{_fmt(ours.get('backend'))}` |")
    lines.append(f"| Episodes | `{_fmt(ours_s.get('episodes'))}` |")
    lines.append(f"| Tool success rate | `{_fmt(ours_s.get('tool_success_rate'))}` |")
    lines.append(f"| Protocol success rate | `{_fmt(ours_s.get('protocol_success_rate'))}` |")
    lines.append(f"| Real MCP call rate | `{_fmt(ours_s.get('real_mcp_call_rate'))}` |")
    lines.append(f"| Real MCP calls | `{_fmt(ours_t.get('real_mcp_calls'))}` |")
    lines.append(f"| Waste call rate | `{_fmt(ours_s.get('waste_call_rate'))}` |")
    lines.append("")
    lines.append("## External Published Results Snapshot")
    lines.append("")
    lines.append("| System | Benchmark | Reported Result | Date | Directly Comparable to Our Current Run? | Note | Source |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in external_rows:
        lines.append(
            "| {system} | {benchmark} | {reported} | {date} | {comparable} | {note} | {source} |".format(
                **r
            )
        )
    lines.append("")
    lines.append("## Reviewer-Facing Interpretation")
    lines.append("")
    lines.append("- We can claim our run is real and reproducible (strict live MCP evidence).")
    lines.append("- We cannot claim cross-benchmark SOTA from this table alone.")
    lines.append("- For apples-to-apples claims, we must run our system inside the same external harness (tau2/tau3, BFCL, LongMemEval).")

    out_path = REPORTS / "real_vs_external_comparison.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(out_path.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

