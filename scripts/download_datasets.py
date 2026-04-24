"""
Download external datasets for TEM experiments into datasets/external.

Datasets:
- LongMemEval (cleaned S/M splits)
- BFCL v3 selected subsets
- tau-bench repository snapshot
- LoCoMo official repository
- HaluMem official repository
- GoodAI LTM Benchmark official repository

Notes:
- Uses direct HTTP downloads for Hugging Face files to avoid local move/rename
  permission issues seen with cached-download flows on some Windows setups.
- Uses shallow git clone for full official repositories when available.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "datasets" / "external"
LONGMEM = EXTERNAL / "longmemeval"
BFCL = EXTERNAL / "bfcl"
TAU = EXTERNAL / "tau_bench"
LOCOMO = EXTERNAL / "locomo"
HALUMEM = EXTERNAL / "halumem"
GOODAI = EXTERNAL / "goodai_ltm_benchmark"


def _prepare_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HTTP_PROXY"] = ""
    env["HTTPS_PROXY"] = ""
    env["ALL_PROXY"] = ""
    env["NO_PROXY"] = "127.0.0.1,localhost"
    return env


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    return s


def _ensure_dirs() -> None:
    for p in [EXTERNAL, LONGMEM, BFCL]:
        p.mkdir(parents=True, exist_ok=True)


def _download_hf_files(repo_id: str, files: Iterable[str], out_dir: Path) -> list[str]:
    downloaded: list[str] = []
    session = _session()
    for file_name in files:
        target = out_dir / file_name
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{file_name}"
        if target.exists() and target.stat().st_size > 0:
            downloaded.append(str(target.resolve()))
            continue

        for attempt in range(1, 4):
            tmp_target = target.with_name(f"{target.name}.part.{os.getpid()}.{int(time.time() * 1000)}.{attempt}")
            try:
                with session.get(url, timeout=180, stream=True) as r:
                    r.raise_for_status()
                    with tmp_target.open("wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                shutil.copyfile(tmp_target, target)
                try:
                    tmp_target.unlink(missing_ok=True)
                except Exception:
                    pass
                break
            except Exception:
                if tmp_target.exists():
                    try:
                        tmp_target.unlink(missing_ok=True)
                    except Exception:
                        pass
                if attempt < 3:
                    time.sleep(2 * attempt)
                else:
                    raise

        downloaded.append(str(target.resolve()))
    return downloaded


def _clone_or_pull(url: str, target: Path) -> dict[str, object]:
    env = _prepare_env()
    clone_ok = False
    action = "none"

    if (target / ".git").exists():
        pull = subprocess.run(
            ["git", "-C", str(target), "pull", "--ff-only"],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        clone_ok = pull.returncode == 0
        action = "pull"
    else:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(target)],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        clone_ok = clone.returncode == 0
        action = "clone"

    head = ""
    if clone_ok and (target / ".git").exists():
        rev = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        if rev.returncode == 0:
            head = rev.stdout.strip()

    marker = target / ".download_source.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "source": url,
                "git_clone_ok": clone_ok,
                "action": action,
                "git_head": head,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"path": str(target.resolve()), "git_clone_ok": clone_ok, "git_head": head, "action": action}


def download_longmemeval() -> list[str]:
    files = [
        "longmemeval_s_cleaned.json",
        "longmemeval_m_cleaned.json",
        "README.md",
    ]
    return _download_hf_files("xiaowu0162/longmemeval-cleaned", files, LONGMEM)


def download_bfcl() -> list[str]:
    files = [
        "README.md",
        "BFCL_v3_simple.json",
        "BFCL_v3_parallel.json",
        "BFCL_v3_multi_turn_base.json",
        "BFCL_v3_multi_turn_composite.json",
        "BFCL_v3_exec_simple.json",
        "BFCL_v3_exec_parallel.json",
    ]
    return _download_hf_files("gorilla-llm/Berkeley-Function-Calling-Leaderboard", files, BFCL)


def download_tau_bench() -> dict[str, object]:
    return _clone_or_pull("https://github.com/sierra-research/tau-bench", TAU)


def download_locomo() -> dict[str, object]:
    return _clone_or_pull("https://github.com/snap-research/LoCoMo", LOCOMO)


def download_halumem() -> dict[str, object]:
    return _clone_or_pull("https://github.com/MemTensor/HaluMem", HALUMEM)


def download_goodai_ltm() -> dict[str, object]:
    return _clone_or_pull("https://github.com/GoodAI/goodai-ltm-benchmark", GOODAI)


def _quick_health_checks() -> dict[str, int]:
    checks = {
        "longmem_http": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/README.md",
        "bfcl_http": "https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main/README.md",
        "tau_http": "https://raw.githubusercontent.com/sierra-research/tau-bench/main/README.md",
        "locomo_http": "https://raw.githubusercontent.com/snap-research/LoCoMo/main/README.MD",
        "halumem_http": "https://raw.githubusercontent.com/MemTensor/HaluMem/main/README.md",
        "goodai_http": "https://raw.githubusercontent.com/GoodAI/goodai-ltm-benchmark/main/README.md",
    }
    status: dict[str, int] = {}
    session = _session()
    for key, url in checks.items():
        r = session.get(url, timeout=20)
        status[key] = r.status_code
    return status


def main() -> None:
    _ensure_dirs()

    status = _quick_health_checks()
    longmem_files = download_longmemeval()
    bfcl_files = download_bfcl()
    tau_info = download_tau_bench()
    locomo_info = download_locomo()
    halumem_info = download_halumem()
    goodai_info = download_goodai_ltm()

    manifest = {
        "health": status,
        "longmemeval": longmem_files,
        "bfcl": bfcl_files,
        "tau_bench": tau_info,
        "locomo": locomo_info,
        "halumem": halumem_info,
        "goodai_ltm_benchmark": goodai_info,
    }

    out = EXTERNAL / "download_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
