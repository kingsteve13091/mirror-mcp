"""
Strict parameter loader.

Rule:
- No decision parameter defaults in code.
- All algorithm parameters must come from artifacts/algorithm_params.json.
- Missing section/key -> fail fast (RuntimeError).
"""

import json
from pathlib import Path
from typing import Any

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
PARAMS_PATH = ARTIFACTS_DIR / "algorithm_params.json"


def load_required_params(section: str, required_keys: list[str]) -> dict[str, Any]:
    if not PARAMS_PATH.exists():
        raise RuntimeError(
            f"Missing required parameter file: {PARAMS_PATH}. "
            "System refuses to start without calibrated parameters."
        )

    try:
        with open(PARAMS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read parameter file {PARAMS_PATH}: {e}") from e

    if section not in data or not isinstance(data[section], dict):
        raise RuntimeError(
            f"Missing required section '{section}' in {PARAMS_PATH}."
        )

    sec = data[section]
    missing = [k for k in required_keys if k not in sec]
    if missing:
        raise RuntimeError(
            f"Missing required keys in section '{section}': {missing}. "
            f"File: {PARAMS_PATH}"
        )
    return sec

