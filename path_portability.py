from __future__ import annotations

from pathlib import Path
from typing import Any

MCP_MIRROR_ROOT_TOKEN = "${MCP_MIRROR_ROOT}"
PROJECT_ROOT = Path(__file__).resolve().parent


def _resolved_root(project_root: Path | None = None) -> Path:
    return (project_root or PROJECT_ROOT).resolve()


def encode_portable_string(value: str, *, project_root: Path | None = None) -> str:
    root = _resolved_root(project_root)
    result = str(value)
    candidates = sorted(
        {
            str(root),
            root.as_posix(),
        },
        key=len,
        reverse=True,
    )
    for candidate in candidates:
        if candidate:
            result = result.replace(candidate, MCP_MIRROR_ROOT_TOKEN)
    return result


def decode_portable_string(value: str, *, project_root: Path | None = None) -> str:
    root = str(_resolved_root(project_root))
    return str(value).replace(MCP_MIRROR_ROOT_TOKEN, root)


def encode_portable_paths(value: Any, *, project_root: Path | None = None) -> Any:
    if isinstance(value, str):
        return encode_portable_string(value, project_root=project_root)
    if isinstance(value, list):
        return [encode_portable_paths(item, project_root=project_root) for item in value]
    if isinstance(value, tuple):
        return tuple(encode_portable_paths(item, project_root=project_root) for item in value)
    if isinstance(value, dict):
        return {
            key: encode_portable_paths(item, project_root=project_root)
            for key, item in value.items()
        }
    return value


def decode_portable_paths(value: Any, *, project_root: Path | None = None) -> Any:
    if isinstance(value, str):
        return decode_portable_string(value, project_root=project_root)
    if isinstance(value, list):
        return [decode_portable_paths(item, project_root=project_root) for item in value]
    if isinstance(value, tuple):
        return tuple(decode_portable_paths(item, project_root=project_root) for item in value)
    if isinstance(value, dict):
        return {
            key: decode_portable_paths(item, project_root=project_root)
            for key, item in value.items()
        }
    return value


def uses_portable_root_token(value: Any) -> bool:
    if isinstance(value, str):
        return MCP_MIRROR_ROOT_TOKEN in value
    if isinstance(value, list):
        return any(uses_portable_root_token(item) for item in value)
    if isinstance(value, tuple):
        return any(uses_portable_root_token(item) for item in value)
    if isinstance(value, dict):
        return any(uses_portable_root_token(item) for item in value.values())
    return False
