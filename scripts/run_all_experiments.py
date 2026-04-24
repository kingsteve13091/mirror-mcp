"""
One-stop runner for TEM experiments.

Stages:
1) Dataset integrity check
2) Optional dataset download (if missing and --auto-download)
3) Optional TEM simulation benchmark (explicit opt-in only)
4) Strict live MCP benchmark (requires backend running)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], required: bool = True) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if required and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{out}")
    return proc.returncode, out


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full TEM experiment pipeline")
    parser.add_argument("--auto-download", action="store_true", help="Try downloading missing datasets automatically")
    parser.add_argument(
        "--with-simulation",
        action="store_true",
        help="Also run simulation benchmark (not for real online claims).",
    )
    # Backward-compatibility switch. The pipeline is strict real by default now.
    parser.add_argument(
        "--real-only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip live MCP benchmark",
    )
    parser.add_argument(
        "--live-config",
        type=str,
        default="experiments/configs/tem_live_mcp_eval_strict.yaml",
        help="Live MCP runner config path",
    )
    args = parser.parse_args()

    summary: dict[str, Any] = {
        "dataset_check": {},
        "simulation": {},
        "live_mcp": {},
    }

    # 1) dataset check
    _run([sys.executable, "scripts/check_datasets.py"], required=True)
    check_report = _load_json(ROOT / "datasets" / "external" / "dataset_check_report.json")
    summary["dataset_check"] = check_report

    all_ok = bool(check_report.get("all_ok", False))

    # 2) optional download if missing
    if not all_ok and args.auto_download:
        _run([sys.executable, "scripts/download_datasets.py"], required=False)
        _run([sys.executable, "scripts/check_datasets.py"], required=True)
        check_report = _load_json(ROOT / "datasets" / "external" / "dataset_check_report.json")
        summary["dataset_check"] = check_report
        all_ok = bool(check_report.get("all_ok", False))

    # 3) simulation benchmark (explicit opt-in only)
    if not args.with_simulation:
        summary["simulation"] = {"skipped": True, "reason": "strict real-only default"}
    else:
        sim_rc, sim_out = _run(
            [
                sys.executable,
                "experiments/runners/run_tem_experiments.py",
                "--config",
                "experiments/configs/tem_toolbench_baseline_vs_tem.yaml",
                "--out-prefix",
                "tem_toolbench_baseline_vs_tem",
                "--allow-simulation",
            ],
            required=False,
        )
        summary["simulation"] = {"return_code": sim_rc, "ok": sim_rc == 0, "log_tail": sim_out[-1200:]}

    # 4) live benchmark
    if args.skip_live:
        summary["live_mcp"] = {"skipped": True, "reason": "skip-live enabled"}
    else:
        live_rc, live_out = _run(
            [
                sys.executable,
                "experiments/runners/run_live_mcp_experiments.py",
                "--config",
                args.live_config,
                "--out-prefix",
                "tem_live_mcp_eval",
            ],
            required=False,
        )
        summary["live_mcp"] = {"return_code": live_rc, "ok": live_rc == 0, "log_tail": live_out[-1200:]}

    out = ROOT / "experiments" / "results" / "pipeline_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
