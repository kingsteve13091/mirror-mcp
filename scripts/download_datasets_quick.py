"""Quick external dataset fetcher for unstable network environments.

Downloads lightweight but usable files from BFCL and tau-bench docs.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "datasets" / "external"
BFCL = EXT / "bfcl"
TAU = EXT / "tau_bench"
LONGMEM = EXT / "longmemeval"


def fetch(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.trust_env = False
    with s.get(url, timeout=120, stream=True) as r:
        r.raise_for_status()
        with target.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def main() -> None:
    manifest: dict[str, str] = {}

    # BFCL lightweight subset
    bfcl_files = {
        "README.md": "https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main/README.md",
        "BFCL_v3_simple.json": "https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main/BFCL_v3_simple.json",
        "BFCL_v3_parallel.json": "https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main/BFCL_v3_parallel.json",
    }

    for name, url in bfcl_files.items():
        target = BFCL / name
        if not target.exists() or target.stat().st_size == 0:
            fetch(url, target)
        manifest[f"bfcl/{name}"] = str(target.resolve())

    # tau-bench README fallback (repo clone can be done later)
    tau_readme = TAU / "README.md"
    if not tau_readme.exists() or tau_readme.stat().st_size == 0:
        fetch("https://raw.githubusercontent.com/sierra-research/tau-bench/main/README.md", tau_readme)
    manifest["tau_bench/README.md"] = str(tau_readme.resolve())

    # LongMemEval README to complete metadata even if main file already exists
    long_readme = LONGMEM / "README.md"
    if not long_readme.exists() or long_readme.stat().st_size == 0:
        fetch("https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/README.md", long_readme)
    manifest["longmemeval/README.md"] = str(long_readme.resolve())

    out = EXT / "quick_download_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
