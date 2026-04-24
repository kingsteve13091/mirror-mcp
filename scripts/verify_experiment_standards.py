"""
Verify experiment standards for reproducibility and reporting quality.

Checks:
1) Dataset integrity report exists and all_ok.
2) Required experiment files exist.
3) Live summary contains strict real-call evidence.
4) Reproducibility check:
   - run strict live evaluation twice
   - compare key metrics across two runs
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "results"


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        # Best effort cleanup; verification will fail later if stale files persist.
        pass


def _key_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    s = summary.get("summary", {})
    if isinstance(s, dict) and any(isinstance(v, dict) and "totals" in v for v in s.values()):
        s = s.get("full_tem") or next((v for v in s.values() if isinstance(v, dict)), {})
    return {
        "episodes": s.get("episodes"),
        "actual_episode_success_rate": s.get("actual_episode_success_rate"),
        "tool_success_rate": s.get("tool_success_rate"),
        "protocol_success_rate": s.get("protocol_success_rate"),
        "unknown_tool_rate": s.get("unknown_tool_rate"),
        "real_mcp_call_rate": s.get("real_mcp_call_rate"),
        "resolved_step_rate": s.get("resolved_step_rate"),
        "real_mcp_calls": s.get("totals", {}).get("real_mcp_calls"),
        "blocked_calls": s.get("totals", {}).get("blocked_calls"),
    }


def main() -> None:
    report: dict[str, Any] = {
        "standards_passed": False,
        "checks": {},
        "notes": [],
    }

    # 1) dataset integrity
    ds_path = ROOT / "datasets" / "external" / "dataset_check_report.json"
    ds = _load_json(ds_path)
    ds_ok = bool(ds.get("all_ok", False))
    report["checks"]["dataset_integrity"] = {
        "ok": ds_ok,
        "path": str(ds_path),
    }
    if not ds_ok:
        report["notes"].append("Dataset integrity is not fully satisfied.")

    # 2) required files
    required = [
        ROOT / "experiments" / "configs" / "tem_live_mcp_eval_strict.yaml",
        ROOT / "experiments" / "runners" / "run_live_mcp_experiments.py",
        ROOT / "scripts" / "run_all_experiments.py",
        ROOT / "scripts" / "check_datasets.py",
        ROOT / "scripts" / "audit_internal_benchmark.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    report["checks"]["required_files"] = {"ok": len(missing) == 0, "missing": missing}

    # 3) remove stale summaries before strict run to avoid false pass from old files
    _safe_unlink(RESULTS / "pipeline_summary.json")
    _safe_unlink(RESULTS / "tem_live_mcp_eval_summary.json")
    _safe_unlink(RESULTS / "tem_live_mcp_eval_raw.jsonl")

    # 4) run strict live once
    rc1, out1 = _run([sys.executable, "scripts/run_all_experiments.py", "--real-only"])
    pipe = _load_json(RESULTS / "pipeline_summary.json")
    live_ok = bool(pipe.get("live_mcp", {}).get("ok", False))
    report["checks"]["strict_live_run"] = {
        "ok": rc1 == 0 and live_ok,
        "return_code": rc1,
        "pipeline_live_ok": live_ok,
        "log_tail": out1[-800:],
    }

    live_summary_path = RESULTS / "tem_live_mcp_eval_summary.json"
    live_summary1 = _load_json(live_summary_path) if (rc1 == 0 and live_ok) else {}
    m1 = _key_metrics(live_summary1)
    strict_evidence_ok = (
        rc1 == 0
        and live_ok
        and not bool(live_summary1.get("probe_only_mode", False))
        and m1.get("real_mcp_calls", 0) is not None
        and float(m1.get("resolved_step_rate") or 0.0) >= 1.0
    )
    report["checks"]["strict_evidence"] = {
        "ok": strict_evidence_ok,
        "summary_path": str(live_summary_path),
        "metrics": m1,
        "probe_only_mode": live_summary1.get("probe_only_mode"),
    }

    rc_audit, audit_out = _run([sys.executable, "scripts/audit_internal_benchmark.py"])
    audit_report = _load_json(RESULTS / "internal_benchmark_audit.json")
    report["checks"]["internal_benchmark_audit"] = {
        "ok": rc_audit == 0 and bool(audit_report.get("ok", False)),
        "return_code": rc_audit,
        "audit_ok": bool(audit_report.get("ok", False)),
        "log_tail": audit_out[-800:],
    }

    # 5) reproducibility: second strict run and compare
    rc2, out2 = _run([sys.executable, "scripts/run_all_experiments.py", "--real-only"])
    live_summary2 = _load_json(live_summary_path) if rc2 == 0 else {}
    m2 = _key_metrics(live_summary2)

    # For live online tools, exact equality is too strict; use bounded drift checks.
    # We require same episode count and real-call guarantee; quality metrics may drift.
    repro_ok = (
        rc1 == 0
        and live_ok
        and rc2 == 0
        and m1.get("episodes") == m2.get("episodes")
        and (m1.get("real_mcp_calls") or 0) > 0
        and (m2.get("real_mcp_calls") or 0) > 0
        and not bool(live_summary1.get("probe_only_mode", False))
        and not bool(live_summary2.get("probe_only_mode", False))
        and float(m1.get("resolved_step_rate") or 0.0) >= 1.0
        and float(m2.get("resolved_step_rate") or 0.0) >= 1.0
    )
    report["checks"]["reproducibility_live"] = {
        "ok": repro_ok,
        "run1": m1,
        "run2": m2,
        "run2_log_tail": out2[-800:],
    }

    all_checks = [v.get("ok", False) for v in report["checks"].values()]
    report["standards_passed"] = all(all_checks)

    out = RESULTS / "standards_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
