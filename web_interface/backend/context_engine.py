"""
Context engine for MCP Mirror.

Responsibilities:
- maintain per-client conversation memory
- build compact API messages under a token budget
- compress old messages locally or with a remote summarizer
- extract lightweight long-term facts for future retrieval

Design constraints:
- no hidden keyword-routing rules
- no algorithm defaults outside artifacts/algorithm_params.json
- memory behavior should remain inspectable and reproducible
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import zipfile
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

from probabilistic_params import load_required_params

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
MEMORY_DIR = ARTIFACTS_DIR / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"

_CONTEXT_PARAM_KEYS = [
    "MAX_CONTEXT_TOKENS",
    "MAX_RECENT_MESSAGES",
    "TOOL_RESULT_MAX_CHARS",
    "NGRAM_SIZE",
    "SUMMARY_TARGET_RATIO",
    "RECENT_CONTEXT_RATIO",
    "FACT_ACCEPT_SIMILARITY",
    "FACT_MIN_INFORMATION",
    "SUMMARY_MAX_INPUT_CHARS",
    "SUMMARY_MAX_OUTPUT_TOKENS",
    "SUMMARY_API_TEMPERATURE",
    "SUMMARY_API_TIMEOUT_SECONDS",
    "SUMMARY_MAX_CHARS",
    "SUMMARY_LINE_MAX_CHARS",
    "RETAIN_RECENT_RATIO",
    "RETAIN_RECENT_MIN",
    "FACT_MAX_ITEMS",
    "FACT_DISPLAY_MAX",
    "FACT_PREVIEW_MAX_ITEMS",
    "SUMMARY_PREVIEW_CHARS",
    "MEMORY_RECENT_SAVE_MAX_MESSAGES",
    "MEMORY_MESSAGE_WINDOW_MULTIPLIER",
    "ASCII_CHARS_PER_TOKEN",
    "CJK_CHARS_PER_TOKEN",
    "OTHER_CHARS_PER_TOKEN",
    "NGRAM_NORM_EPSILON",
    "ENTROPY_MIN_TEXT_LEN",
    "ENTROPY_COUNT_FLOOR",
    "ENTROPY_PROB_EPSILON",
    "ENTROPY_DENOM_EPSILON",
    "TRUNCATE_MIN_KEEP_CHARS",
    "DICT_BASE_OVERHEAD_CHARS",
    "DICT_MIN_FIELD_COST",
    "DICT_SEP_COST",
    "LIST_PICK_MIN_ITEMS",
    "LIST_PICK_MAX_ITEMS",
    "SUMMARY_RECENCY_MIN_DENOM",
    "COMPRESS_TRIGGER_MIN_MESSAGES",
    "SUMMARY_TRIM_MIN_MESSAGES",
    "TOKENS_MIN_ESTIMATE",
    "FACT_MIN_TOKENS",
    "FACT_MAX_TOKENS",
    "CUSTOM_SYSTEM_PROMPT_MAX_CHARS",
    "SKILLS_CONTEXT_MAX_CHARS",
    "ATTACHMENT_TEXT_MAX_CHARS",
    "ATTACHMENT_MAX_COUNT",
]


def _apply_context_params(params: dict[str, Any]) -> None:
    global MAX_CONTEXT_TOKENS
    global MAX_RECENT_MESSAGES
    global TOOL_RESULT_MAX_CHARS
    global NGRAM_SIZE
    global SUMMARY_TARGET_RATIO
    global RECENT_CONTEXT_RATIO
    global FACT_ACCEPT_SIMILARITY
    global FACT_MIN_INFORMATION
    global SUMMARY_MAX_INPUT_CHARS
    global SUMMARY_MAX_OUTPUT_TOKENS
    global SUMMARY_API_TEMPERATURE
    global SUMMARY_API_TIMEOUT_SECONDS
    global SUMMARY_MAX_CHARS
    global SUMMARY_LINE_MAX_CHARS
    global RETAIN_RECENT_RATIO
    global RETAIN_RECENT_MIN
    global FACT_MAX_ITEMS
    global FACT_DISPLAY_MAX
    global FACT_PREVIEW_MAX_ITEMS
    global SUMMARY_PREVIEW_CHARS
    global MEMORY_RECENT_SAVE_MAX_MESSAGES
    global MEMORY_MESSAGE_WINDOW_MULTIPLIER
    global ASCII_CHARS_PER_TOKEN
    global CJK_CHARS_PER_TOKEN
    global OTHER_CHARS_PER_TOKEN
    global NGRAM_NORM_EPSILON
    global ENTROPY_MIN_TEXT_LEN
    global ENTROPY_COUNT_FLOOR
    global ENTROPY_PROB_EPSILON
    global ENTROPY_DENOM_EPSILON
    global TRUNCATE_MIN_KEEP_CHARS
    global DICT_BASE_OVERHEAD_CHARS
    global DICT_MIN_FIELD_COST
    global DICT_SEP_COST
    global LIST_PICK_MIN_ITEMS
    global LIST_PICK_MAX_ITEMS
    global SUMMARY_RECENCY_MIN_DENOM
    global COMPRESS_TRIGGER_MIN_MESSAGES
    global SUMMARY_TRIM_MIN_MESSAGES
    global TOKENS_MIN_ESTIMATE
    global FACT_MIN_TOKENS
    global FACT_MAX_TOKENS
    global CUSTOM_SYSTEM_PROMPT_MAX_CHARS
    global SKILLS_CONTEXT_MAX_CHARS
    global ATTACHMENT_TEXT_MAX_CHARS
    global ATTACHMENT_MAX_COUNT

    MAX_CONTEXT_TOKENS = int(params["MAX_CONTEXT_TOKENS"])
    MAX_RECENT_MESSAGES = int(params["MAX_RECENT_MESSAGES"])
    TOOL_RESULT_MAX_CHARS = int(params["TOOL_RESULT_MAX_CHARS"])
    NGRAM_SIZE = int(params["NGRAM_SIZE"])
    SUMMARY_TARGET_RATIO = float(params["SUMMARY_TARGET_RATIO"])
    RECENT_CONTEXT_RATIO = float(params["RECENT_CONTEXT_RATIO"])
    FACT_ACCEPT_SIMILARITY = float(params["FACT_ACCEPT_SIMILARITY"])
    FACT_MIN_INFORMATION = float(params["FACT_MIN_INFORMATION"])
    SUMMARY_MAX_INPUT_CHARS = int(params["SUMMARY_MAX_INPUT_CHARS"])
    SUMMARY_MAX_OUTPUT_TOKENS = int(params["SUMMARY_MAX_OUTPUT_TOKENS"])
    SUMMARY_API_TEMPERATURE = float(params["SUMMARY_API_TEMPERATURE"])
    SUMMARY_API_TIMEOUT_SECONDS = float(params["SUMMARY_API_TIMEOUT_SECONDS"])
    SUMMARY_MAX_CHARS = int(params["SUMMARY_MAX_CHARS"])
    SUMMARY_LINE_MAX_CHARS = int(params["SUMMARY_LINE_MAX_CHARS"])
    RETAIN_RECENT_RATIO = float(params["RETAIN_RECENT_RATIO"])
    RETAIN_RECENT_MIN = int(params["RETAIN_RECENT_MIN"])
    FACT_MAX_ITEMS = int(params["FACT_MAX_ITEMS"])
    FACT_DISPLAY_MAX = int(params["FACT_DISPLAY_MAX"])
    FACT_PREVIEW_MAX_ITEMS = int(params["FACT_PREVIEW_MAX_ITEMS"])
    SUMMARY_PREVIEW_CHARS = int(params["SUMMARY_PREVIEW_CHARS"])
    MEMORY_RECENT_SAVE_MAX_MESSAGES = int(params["MEMORY_RECENT_SAVE_MAX_MESSAGES"])
    MEMORY_MESSAGE_WINDOW_MULTIPLIER = int(params["MEMORY_MESSAGE_WINDOW_MULTIPLIER"])
    ASCII_CHARS_PER_TOKEN = float(params["ASCII_CHARS_PER_TOKEN"])
    CJK_CHARS_PER_TOKEN = float(params["CJK_CHARS_PER_TOKEN"])
    OTHER_CHARS_PER_TOKEN = float(params["OTHER_CHARS_PER_TOKEN"])
    NGRAM_NORM_EPSILON = float(params["NGRAM_NORM_EPSILON"])
    ENTROPY_MIN_TEXT_LEN = int(params["ENTROPY_MIN_TEXT_LEN"])
    ENTROPY_COUNT_FLOOR = int(params["ENTROPY_COUNT_FLOOR"])
    ENTROPY_PROB_EPSILON = float(params["ENTROPY_PROB_EPSILON"])
    ENTROPY_DENOM_EPSILON = float(params["ENTROPY_DENOM_EPSILON"])
    TRUNCATE_MIN_KEEP_CHARS = int(params["TRUNCATE_MIN_KEEP_CHARS"])
    DICT_BASE_OVERHEAD_CHARS = int(params["DICT_BASE_OVERHEAD_CHARS"])
    DICT_MIN_FIELD_COST = int(params["DICT_MIN_FIELD_COST"])
    DICT_SEP_COST = int(params["DICT_SEP_COST"])
    LIST_PICK_MIN_ITEMS = int(params["LIST_PICK_MIN_ITEMS"])
    LIST_PICK_MAX_ITEMS = int(params["LIST_PICK_MAX_ITEMS"])
    SUMMARY_RECENCY_MIN_DENOM = int(params["SUMMARY_RECENCY_MIN_DENOM"])
    COMPRESS_TRIGGER_MIN_MESSAGES = int(params["COMPRESS_TRIGGER_MIN_MESSAGES"])
    SUMMARY_TRIM_MIN_MESSAGES = int(params["SUMMARY_TRIM_MIN_MESSAGES"])
    TOKENS_MIN_ESTIMATE = int(params["TOKENS_MIN_ESTIMATE"])
    FACT_MIN_TOKENS = int(params["FACT_MIN_TOKENS"])
    FACT_MAX_TOKENS = int(params["FACT_MAX_TOKENS"])
    CUSTOM_SYSTEM_PROMPT_MAX_CHARS = int(params["CUSTOM_SYSTEM_PROMPT_MAX_CHARS"])
    SKILLS_CONTEXT_MAX_CHARS = int(params["SKILLS_CONTEXT_MAX_CHARS"])
    ATTACHMENT_TEXT_MAX_CHARS = int(params["ATTACHMENT_TEXT_MAX_CHARS"])
    ATTACHMENT_MAX_COUNT = int(params["ATTACHMENT_MAX_COUNT"])


_apply_context_params(load_required_params("context_engine", _CONTEXT_PARAM_KEYS))

SYSTEM_PROMPT = (
    "You are MCP Mirror, a memory-centered assistant that can use real MCP tools. "
    "Be accurate, honest, executable, and use tools when they are needed. "
    "Never fabricate tool calls, tool result blocks, code-like tool invocations, or pretend a tool ran unless the conversation already includes explicit grounded tool evidence. "
    "If no grounded tool result is present in this turn, answer normally and do not simulate tool execution."
)

FACT_TYPE_SEEDS = {
    "configuration": "system configuration settings ports models paths connections variables",
    "preference": "user preference style constraint selection requirement habit",
    "decision": "decision chosen plan route conclusion selected approach",
    "environment": "environment operating system version dependency workspace runtime",
    "task_state": "completed in progress pending issue fix status milestone",
}

TEXT_ATTACHMENT_EXTENSIONS = {
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".py",
    ".rst",
    ".text",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

DOCX_TEXT_NODE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
INVISIBLE_TEXT_CHARS = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)
WORKSPACE_CONTEXT_MAX_CHARS = 12000
WORKSPACE_CONTEXT_CHATLOG_LIMIT = 3
WORKSPACE_CONTEXT_CHATLOG_PREVIEW_CHARS = 1200
WORKSPACE_COMMAND_MAX_CHARS = 4200
WORKSPACE_COMMAND_LIST_LIMIT = 48


def normalize_text(content: Any) -> str:
    if isinstance(content, str):
        return content.translate(INVISIBLE_TEXT_CHARS)
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        ).translate(INVISIBLE_TEXT_CHARS)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False).translate(INVISIBLE_TEXT_CHARS)
    return str(content).translate(INVISIBLE_TEXT_CHARS)


def estimate_tokens(text: str) -> int:
    ascii_count = 0
    cjk_count = 0
    other_count = 0
    for ch in text:
        code = ord(ch)
        if code < 128:
            ascii_count += 1
        elif 0x4E00 <= code <= 0x9FFF:
            cjk_count += 1
        else:
            other_count += 1
    estimate = (
        ascii_count / ASCII_CHARS_PER_TOKEN
        + cjk_count / CJK_CHARS_PER_TOKEN
        + other_count / OTHER_CHARS_PER_TOKEN
    )
    return max(TOKENS_MIN_ESTIMATE, int(math.ceil(estimate)))

def ngram_vector(text: str, n: Optional[int] = None) -> dict[str, float]:
    gram_size = NGRAM_SIZE if n is None else n
    normalized = normalize_text(text).lower().strip()
    if len(normalized) < gram_size:
        return {}
    freq: dict[str, float] = {}
    for idx in range(len(normalized) - gram_size + 1):
        gram = normalized[idx : idx + gram_size]
        freq[gram] = freq.get(gram, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in freq.values()))
    if norm <= NGRAM_NORM_EPSILON:
        return {}
    return {key: value / norm for key, value in freq.items()}


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return sum(value * longer.get(key, 0.0) for key, value in shorter.items())


def text_information_density(text: str) -> float:
    normalized = normalize_text(text).strip()
    if len(normalized) < ENTROPY_MIN_TEXT_LEN:
        return 0.0
    counts: dict[str, int] = {}
    for ch in normalized:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(normalized)
    entropy = 0.0
    for count in counts.values():
        prob = count / total
        entropy -= prob * math.log(max(prob, ENTROPY_PROB_EPSILON), 2)
    max_entropy = math.log(max(len(counts), ENTROPY_COUNT_FLOOR), 2)
    return min(1.0, entropy / max(max_entropy, ENTROPY_DENOM_EPSILON))


def _truncate_with_notice(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    suffix = f"\n...[semantic truncation, original {len(text)} chars]"
    keep = max(max_chars - len(suffix), TRUNCATE_MIN_KEEP_CHARS)
    return text[:keep] + suffix


def _safe_workspace_root(path_text: str) -> Optional[Path]:
    if not isinstance(path_text, str) or not path_text.strip():
        return None
    try:
        path = Path(path_text).expanduser().resolve()
    except Exception:
        return None
    if not path.exists() or not path.is_dir():
        return None
    return path


def _read_text_if_exists(path: Path, max_chars: int) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    normalized = normalize_text(text).strip()
    if not normalized:
        return ""
    return _truncate_with_notice(normalized, max_chars)


def _load_agent_yaml_summary(agent_yaml_path: Path, max_chars: int = 2600) -> str:
    try:
        if not agent_yaml_path.exists() or not agent_yaml_path.is_file():
            return ""
        parsed = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return ""
    if not isinstance(parsed, dict):
        return ""
    summary_fields = {
        "name": parsed.get("name"),
        "description": parsed.get("description"),
        "modelKey": parsed.get("modelKey"),
        "allowMCPs": parsed.get("allowMCPs"),
        "isConfirmCallTool": parsed.get("isConfirmCallTool"),
        "tags": parsed.get("tags"),
        "prompt": parsed.get("prompt"),
    }
    compact = json.dumps(summary_fields, ensure_ascii=False, indent=2)
    return _truncate_with_notice(normalize_text(compact), max_chars)


def _resolve_workspace_agent_dir(workspace_root: str = "", agent_name: str = "") -> Optional[Path]:
    root = _safe_workspace_root(workspace_root)
    if root is None:
        return None

    workspace_agents_root = root / ".mcp-mirror" / "agents"
    if not workspace_agents_root.exists() or not workspace_agents_root.is_dir():
        return None

    selected_agent = str(agent_name or "").strip()
    if selected_agent:
        candidate = workspace_agents_root / selected_agent
        if candidate.exists() and candidate.is_dir():
            return candidate
        return None

    candidate_dirs = sorted(
        [item for item in workspace_agents_root.iterdir() if item.is_dir()],
        key=lambda item: item.name.lower(),
    )
    return candidate_dirs[0] if candidate_dirs else None


def load_workspace_agent_commands(
    workspace_root: str = "",
    agent_name: str = "",
) -> list[dict[str, Any]]:
    agent_dir = _resolve_workspace_agent_dir(workspace_root, agent_name)
    if agent_dir is None:
        return []

    commands_dir = agent_dir / "commands"
    if not commands_dir.exists() or not commands_dir.is_dir():
        return []

    commands: list[dict[str, Any]] = []
    for command_file in sorted(commands_dir.glob("*.md"), key=lambda item: item.name.lower())[:WORKSPACE_COMMAND_LIST_LIMIT]:
        command_name = command_file.stem.strip()
        if not command_name:
            continue
        body = _read_text_if_exists(command_file, WORKSPACE_COMMAND_MAX_CHARS)
        first_line = next((line.strip("# ").strip() for line in body.splitlines() if line.strip()), "")
        commands.append(
            {
                "name": command_name,
                "path": str(command_file),
                "description": first_line[:220],
                "body_preview": body[:600],
                "body_chars": len(body),
            }
        )
    return commands


def load_workspace_agent_command(
    workspace_root: str = "",
    agent_name: str = "",
    command_name: str = "",
) -> dict[str, Any]:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "", str(command_name or "").strip())
    if not normalized:
        return {}

    agent_dir = _resolve_workspace_agent_dir(workspace_root, agent_name)
    if agent_dir is None:
        return {}

    command_file = agent_dir / "commands" / f"{normalized}.md"
    try:
        command_file = command_file.resolve()
        command_file.relative_to((agent_dir / "commands").resolve())
    except Exception:
        return {}

    body = _read_text_if_exists(command_file, WORKSPACE_COMMAND_MAX_CHARS)
    if not body:
        return {}

    return {
        "name": normalized,
        "path": str(command_file),
        "body": body,
        "body_chars": len(body),
    }


def render_workspace_agent_command_context(command: dict[str, Any], user_input: str = "") -> str:
    if not command:
        return ""
    name = str(command.get("name", "") or "").strip()
    body = str(command.get("body", "") or "").strip()
    if not name or not body:
        return ""
    return _truncate_with_notice(
        "\n".join(
            [
                "[Workspace Agent Command]",
                f"name: /{name}",
                "instructions:",
                body,
                "",
                "Use this command as a human-authored workspace instruction layer. "
                "Do not confuse it with Recipe Memory or Guard Memory.",
                f"Original user input: {normalize_text(user_input).strip()}",
            ]
        ),
        WORKSPACE_COMMAND_MAX_CHARS,
    )


def build_workspace_context_block(
    workspace_root: str = "",
    agent_name: str = "",
    include_agent_profile: bool = True,
    include_memory_file: bool = True,
    include_chatlogs: bool = False,
) -> tuple[str, dict[str, Any]]:
    root = _safe_workspace_root(workspace_root)
    metadata: dict[str, Any] = {
        "enabled": bool(root),
        "workspace_root": str(root) if root else "",
        "agent_name": agent_name.strip(),
        "sources": [],
        "missing": [],
    }
    if root is None:
        metadata["missing"].append("workspace_root")
        return "", metadata

    workspace_meta_root = root / ".mcp-mirror"
    if not workspace_meta_root.exists() or not workspace_meta_root.is_dir():
        metadata["missing"].append(".mcp-mirror")
        return "", metadata

    selected_agent = agent_name.strip()
    agent_dir: Optional[Path] = None
    if selected_agent:
        candidate = workspace_meta_root / "agents" / selected_agent
        if candidate.exists() and candidate.is_dir():
            agent_dir = candidate
        else:
            metadata["missing"].append(f"agent:{selected_agent}")
    elif (workspace_meta_root / "agents").exists():
        available_agents = sorted(
            [item for item in (workspace_meta_root / "agents").iterdir() if item.is_dir()],
            key=lambda item: item.name.lower(),
        )
        if available_agents:
            agent_dir = available_agents[0]
            metadata["agent_name"] = agent_dir.name

    if agent_dir is None:
        return "", metadata

    sections: list[str] = []
    metadata["agent_dir"] = str(agent_dir)

    if include_agent_profile:
        agent_yaml = agent_dir / "agent.yaml"
        if not agent_yaml.exists():
            agent_yaml = agent_dir / "agent.md"
        agent_profile = _load_agent_yaml_summary(agent_yaml)
        if agent_profile:
            sections.append(f"[Workspace Agent Profile]\n{agent_profile}")
            metadata["sources"].append({"type": "agent_profile", "path": str(agent_yaml)})

    if include_memory_file:
        memory_md = agent_dir / "memory.md"
        memory_text = _read_text_if_exists(memory_md, 4200)
        if memory_text:
            sections.append(f"[Workspace Memory File]\n{memory_text}")
            metadata["sources"].append({"type": "memory_md", "path": str(memory_md)})

    if include_chatlogs:
        chatlogs_dir = agent_dir / "chatlogs"
        if chatlogs_dir.exists() and chatlogs_dir.is_dir():
            chatlog_files = sorted(
                [item for item in chatlogs_dir.iterdir() if item.is_file()],
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )[:WORKSPACE_CONTEXT_CHATLOG_LIMIT]
            rendered_logs: list[str] = []
            for chatlog in chatlog_files:
                preview = _read_text_if_exists(chatlog, WORKSPACE_CONTEXT_CHATLOG_PREVIEW_CHARS)
                if preview:
                    rendered_logs.append(f"- {chatlog.name}\n{preview}")
                    metadata["sources"].append({"type": "chatlog", "path": str(chatlog)})
            if rendered_logs:
                sections.append("[Workspace Recent Chatlogs]\n" + "\n\n".join(rendered_logs))

    if not sections:
        return "", metadata

    merged = "\n\n".join(sections)
    return _truncate_with_notice(merged, WORKSPACE_CONTEXT_MAX_CHARS), metadata


def load_workspace_agent_runtime_profile(
    workspace_root: str = "",
    agent_name: str = "",
) -> dict[str, Any]:
    agent_dir = _resolve_workspace_agent_dir(workspace_root, agent_name)
    if agent_dir is None:
        return {}
    agent_yaml = agent_dir / "agent.yaml"
    if not agent_yaml.exists():
        return {}
    try:
        parsed = yaml.safe_load(agent_yaml.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}

    allow_mcps = [
        str(item).strip()
        for item in parsed.get("allowMCPs", []) or []
        if str(item).strip()
    ]
    return {
        "agent_name": agent_dir.name,
        "agent_dir": str(agent_dir),
        "allowMCPs": allow_mcps,
        "isConfirmCallTool": bool(parsed.get("isConfirmCallTool", False)),
        "modelKey": str(parsed.get("modelKey", "") or "").strip(),
    }


def _select_dict_fields_by_utility(data: dict[str, Any], budget_chars: int) -> dict[str, Any]:
    items: list[tuple[int, str, Any, float, int, float]] = []
    for idx, (key, value) in enumerate(data.items()):
        value_text = normalize_text(value)
        tokens = estimate_tokens(value_text)
        density = text_information_density(value_text)
        utility = density * math.log1p(tokens)
        pair_repr = json.dumps({key: value}, ensure_ascii=False)
        cost = max(len(pair_repr), DICT_MIN_FIELD_COST)
        items.append((idx, key, value, utility, cost, utility / cost))

    if not items:
        return {}

    items.sort(key=lambda item: (item[5], item[3]), reverse=True)
    selected: list[tuple[int, str, Any]] = []
    used = DICT_BASE_OVERHEAD_CHARS
    for idx, key, value, _, cost, _ in items:
        separator = DICT_SEP_COST if selected else 0
        if used + cost + separator > budget_chars:
            continue
        selected.append((idx, key, value))
        used += cost + separator

    if not selected:
        idx, key, value, *_ = items[0]
        selected = [(idx, key, value)]

    selected.sort(key=lambda item: item[0])
    return {key: value for _, key, value in selected}


def truncate_tool_result(result: Any, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    if isinstance(result, dict):
        filtered = _select_dict_fields_by_utility(result, max_chars)
        text = json.dumps(filtered, ensure_ascii=False)
    elif isinstance(result, list):
        scored: list[tuple[float, int, Any]] = []
        for idx, item in enumerate(result):
            item_text = normalize_text(item)
            utility = text_information_density(item_text) * math.log1p(estimate_tokens(item_text))
            scored.append((utility, idx, item))
        scored.sort(reverse=True)
        picked = [
            item
            for _, _, item in scored[
                : max(LIST_PICK_MIN_ITEMS, min(LIST_PICK_MAX_ITEMS, len(scored)))
            ]
        ]
        text = json.dumps(picked, ensure_ascii=False)
    else:
        text = normalize_text(result)
    return _truncate_with_notice(text, max_chars)


def truncate_system_context_block(text: str, max_chars: int) -> str:
    normalized = normalize_text(text).strip()
    if not normalized:
        return ""
    return _truncate_with_notice(normalized, max_chars)


def _safe_attachment_path(file_path: str) -> Optional[Path]:
    if not file_path:
        return None
    try:
        path = Path(file_path).resolve()
    except Exception:
        return None
    if not path.exists() or not path.is_file():
        return None
    try:
        path.relative_to(UPLOADS_DIR.resolve())
    except ValueError:
        return None
    return path


def _is_text_attachment(path: Path, mime_type: str) -> bool:
    if path.suffix.lower() in TEXT_ATTACHMENT_EXTENSIONS:
        return True
    return mime_type.startswith("text/")


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    parts = [
        node.text.strip()
        for node in root.iter(DOCX_TEXT_NODE)
        if isinstance(node.text, str) and node.text.strip()
    ]
    return "\n".join(parts)


def extract_attachment_content(
    attachment: dict[str, Any],
    *,
    max_chars: Optional[int] = None,
) -> dict[str, Any]:
    original_filename = str(
        attachment.get("original_filename")
        or attachment.get("filename")
        or "unnamed"
    )
    file_path = str(attachment.get("file_path") or "")
    mime_type = str(
        attachment.get("mime_type")
        or attachment.get("content_type")
        or "application/octet-stream"
    )
    size = attachment.get("size")
    path = _safe_attachment_path(file_path)
    limit = ATTACHMENT_TEXT_MAX_CHARS if max_chars is None else max_chars

    result: dict[str, Any] = {
        "filename": str(attachment.get("filename") or path.name if path else original_filename),
        "original_filename": original_filename,
        "file_path": file_path,
        "mime_type": mime_type,
        "size": int(size) if isinstance(size, (int, float)) else None,
        "parse_status": "unavailable",
        "parse_mode": "metadata_only",
        "preview_text": "",
        "path_available": path is not None,
        "parser": None,
        "full_text_chars": None,
        "visible_text_chars": None,
        "preview_truncated": False,
        "error": None,
    }

    if path is None:
        result["error"] = "file_not_found_on_backend"
        return result

    suffix = path.suffix.lower()
    text: Optional[str] = None
    parser_name: Optional[str] = None

    try:
        if _is_text_attachment(path, mime_type):
            text = path.read_text(encoding="utf-8", errors="replace")
            parser_name = "utf8_text"
        elif suffix == ".docx":
            text = _extract_docx_text(path)
            parser_name = "docx_xml"
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except Exception:
                result["parse_status"] = "parser_missing"
                result["parse_mode"] = "metadata_only"
                result["parser"] = "pypdf"
                result["error"] = "pypdf_not_installed"
                return result
            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "").strip() for page in reader.pages)
            parser_name = "pypdf"
        else:
            result["parse_status"] = "metadata_only"
            result["parse_mode"] = "metadata_only"
            result["error"] = "binary_or_complex_attachment"
            return result
    except KeyError as exc:
        result["parse_status"] = "unreadable"
        result["parse_mode"] = "metadata_only"
        result["parser"] = parser_name
        result["error"] = f"missing_archive_member:{exc}"
        return result
    except Exception as exc:
        result["parse_status"] = "unreadable"
        result["parse_mode"] = "metadata_only"
        result["parser"] = parser_name
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    normalized = normalize_text(text).strip()
    result["parser"] = parser_name
    result["full_text_chars"] = len(normalized)
    if normalized:
        preview_text = _truncate_with_notice(normalized, limit)
        result["parse_status"] = "parsed"
        result["parse_mode"] = "full_text"
        result["preview_text"] = preview_text
        result["visible_text_chars"] = len(preview_text)
        result["preview_truncated"] = len(preview_text) < len(normalized)
    else:
        result["parse_status"] = "empty"
        result["parse_mode"] = "metadata_only"
        result["error"] = "no_extractable_text"
    return result


def _build_attachment_context(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""

    rendered_items: list[str] = []
    for attachment in attachments[:ATTACHMENT_MAX_COUNT]:
        if not isinstance(attachment, dict):
            continue
        parsed = extract_attachment_content(attachment)
        original_filename = str(parsed.get("original_filename") or "unnamed")
        file_path = str(parsed.get("file_path") or "")
        mime_type = str(parsed.get("mime_type") or "application/octet-stream")
        size = parsed.get("size")
        path = _safe_attachment_path(file_path)

        header = f"- {original_filename} | mime={mime_type}"
        if isinstance(size, (int, float)):
            header += f" | size={int(size)} bytes"
        if path is not None:
            header += f" | path={path}"
            header += " | tool_usable=yes"
        if parsed.get("parse_status"):
            header += f" | parse={parsed['parse_status']}"
        if parsed.get("parser"):
            header += f" | parser={parsed['parser']}"
        if bool(parsed.get("is_image")) or mime_type.startswith("image/"):
            header += " | kind=image"
        else:
            header += " | kind=file"

        if path is None:
            rendered_items.append(f"{header}\n  content: unavailable (file not found on backend)")
            continue

        if parsed.get("parse_status") == "parsed":
            preview = str(parsed.get("preview_text") or "")
            rendered_items.append(f"{header}\n  content:\n{preview}")
            continue

        if parsed.get("parse_status") == "empty":
            rendered_items.append(f"{header}\n  content: parsed but no extractable text was found")
            continue

        if parsed.get("parse_status") == "parser_missing":
            rendered_items.append(
                f"{header}\n"
                "  content: parser missing on backend; metadata preserved only until the parser dependency is installed."
            )
            continue

        if parsed.get("parse_status") == "unreadable":
            rendered_items.append(f"{header}\n  content: unreadable ({parsed.get('error')})")
            continue

        rendered_items.append(
            f"{header}\n"
            "  content: binary-or-complex attachment preserved as metadata only; "
            "the model can reference filename, mime type, and stored path but not parsed body text."
        )

    if not rendered_items:
        return ""
    return "User attachments:\n" + "\n".join(rendered_items)


@dataclass
class CompressionStats:
    total_messages: int = 0
    messages_sent_to_api: int = 0
    messages_summarized: int = 0
    original_tokens: int = 0
    compressed_tokens: int = 0
    long_term_facts: int = 0
    compression_ratio: float = 1.0
    summary_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_messages": self.total_messages,
            "messages_sent": self.messages_sent_to_api,
            "messages_summarized": self.messages_summarized,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "compression_ratio": round(self.compression_ratio, 2),
            "long_term_facts": self.long_term_facts,
            "has_summary": bool(self.summary_text),
        }


@dataclass
class ConversationMemory:
    client_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    long_term_facts: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    total_user_messages: int = 0
    total_compressions: int = 0

    def add_message(self, role: str, content: str, **meta: Any) -> None:
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        message = {"role": role, "content": content, "ts": now_iso}
        message.update(meta)
        self.messages.append(message)
        self.updated_at = now_iso
        if role == "user":
            self.total_user_messages += 1
        max_window = MAX_RECENT_MESSAGES * MEMORY_MESSAGE_WINDOW_MULTIPLIER
        if len(self.messages) > max_window:
            self.messages = self.messages[-max_window:]

    def add_fact(self, fact: str, fact_type: str = "general", confidence: float = 0.0) -> None:
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        fact_hash = hashlib.md5(fact.encode("utf-8")).hexdigest()[:8]
        for existing in self.long_term_facts:
            if existing.get("hash") == fact_hash:
                return
        self.long_term_facts.append(
            {
                "fact": fact,
                "type": fact_type,
                "confidence": round(confidence, 3),
                "hash": fact_hash,
                "added_at": now_iso,
            }
        )
        self.updated_at = now_iso
        if len(self.long_term_facts) > FACT_MAX_ITEMS:
            self.long_term_facts = self.long_term_facts[-FACT_MAX_ITEMS:]

    def get_total_tokens(self) -> int:
        total = estimate_tokens(self.summary)
        for message in self.messages:
            total += estimate_tokens(normalize_text(message.get("content", "")))
        for fact in self.long_term_facts:
            total += estimate_tokens(str(fact.get("fact", "")))
        return total

    def save(self) -> None:
        path = MEMORY_DIR / f"{self.client_id}.json"
        data = {
            "client_id": self.client_id,
            "summary": self.summary,
            "long_term_facts": self.long_term_facts,
            "message_count": len(self.messages),
            "total_user_messages": self.total_user_messages,
            "total_compressions": self.total_compressions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_active": datetime.now(tz=timezone.utc).isoformat(),
            "recent_messages": self.messages[-MEMORY_RECENT_SAVE_MAX_MESSAGES:],
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Failed to save memory: %s", exc)

    @classmethod
    def load(cls, client_id: str) -> "ConversationMemory":
        path = MEMORY_DIR / f"{client_id}.json"
        memory = cls(client_id=client_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                memory.summary = data.get("summary", "")
                memory.long_term_facts = data.get("long_term_facts", [])
                memory.total_user_messages = data.get("total_user_messages", 0)
                memory.total_compressions = data.get("total_compressions", 0)
                memory.created_at = data.get("created_at", memory.created_at)
                memory.updated_at = data.get("updated_at", data.get("last_active", memory.updated_at))
                memory.messages.extend(data.get("recent_messages", []))
                logger.info("Restored memory %s (summary_chars=%s, facts=%s)", client_id, len(memory.summary), len(memory.long_term_facts))
            except Exception as exc:
                logger.error("Failed to load memory %s: %s", client_id, exc)
        return memory


class SemanticPrototypeMatcher:
    def __init__(self) -> None:
        self.prototypes: dict[str, dict[str, float]] = {
            fact_type: ngram_vector(seed)
            for fact_type, seed in FACT_TYPE_SEEDS.items()
        }

    def classify(self, sentence: str) -> tuple[str, float]:
        vec = ngram_vector(sentence)
        best_type = "general"
        best_score = 0.0
        for fact_type, prototype in self.prototypes.items():
            similarity = cosine_similarity(vec, prototype)
            if similarity > best_score:
                best_type = fact_type
                best_score = similarity
        return best_type, best_score

class ContextEngine:
    def __init__(self) -> None:
        self.memories: dict[str, ConversationMemory] = {}
        self.fact_matcher = SemanticPrototypeMatcher()

    def reload_parameters(self) -> dict[str, Any]:
        _apply_context_params(load_required_params("context_engine", _CONTEXT_PARAM_KEYS))
        self.fact_matcher = SemanticPrototypeMatcher()
        return {
            "MAX_CONTEXT_TOKENS": MAX_CONTEXT_TOKENS,
            "MAX_RECENT_MESSAGES": MAX_RECENT_MESSAGES,
            "NGRAM_SIZE": NGRAM_SIZE,
            "FACT_ACCEPT_SIMILARITY": FACT_ACCEPT_SIMILARITY,
        }

    def get_memory(self, client_id: str) -> ConversationMemory:
        if client_id not in self.memories:
            self.memories[client_id] = ConversationMemory.load(client_id)
        return self.memories[client_id]

    def remove_memory(self, client_id: str) -> None:
        if client_id in self.memories:
            self.memories[client_id].save()
            del self.memories[client_id]

    def _rank_messages_for_summary(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return []
        vectors = [ngram_vector(normalize_text(message.get("content", ""))) for message in messages]
        centroid: dict[str, float] = {}
        for vec in vectors:
            for key, value in vec.items():
                centroid[key] = centroid.get(key, 0.0) + value
        norm = math.sqrt(sum(value * value for value in centroid.values()))
        if norm > NGRAM_NORM_EPSILON:
            centroid = {key: value / norm for key, value in centroid.items()}

        ranked: list[dict[str, Any]] = []
        total_messages = len(messages)
        for idx, message in enumerate(messages):
            text = normalize_text(message.get("content", ""))
            token_count = estimate_tokens(text)
            density = text_information_density(text)
            similarity = cosine_similarity(vectors[idx], centroid)
            recency = math.exp(-(total_messages - idx - 1) / max(total_messages, SUMMARY_RECENCY_MIN_DENOM))
            score = similarity * density * math.log1p(token_count) * recency
            ranked.append({"idx": idx, "msg": message, "text": text, "tokens": token_count, "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked

    def _select_summary_messages(self, messages: list[dict[str, Any]], budget_tokens: int) -> list[dict[str, Any]]:
        ranked = self._rank_messages_for_summary(messages)
        selected: list[dict[str, Any]] = []
        used = 0
        for item in ranked:
            if used + item["tokens"] > budget_tokens:
                continue
            selected.append(item)
            used += item["tokens"]
        selected.sort(key=lambda item: item["idx"])
        return selected

    def _compose_local_summary(self, selected_items: list[dict[str, Any]]) -> str:
        if not selected_items:
            return ""
        lines: list[str] = []
        for item in selected_items:
            role = item["msg"].get("role", "user")
            role_label = "user" if role == "user" else "assistant"
            text = _truncate_with_notice(item["text"], SUMMARY_LINE_MAX_CHARS).replace("\n", " ")
            lines.append(f"{role_label}: {text}")
        return "[semantic summary]\n" + "\n".join(lines)

    def _merge_summary(self, memory: ConversationMemory, new_summary: str) -> None:
        if not new_summary:
            return
        merged = f"{memory.summary}\n{new_summary}".strip() if memory.summary else new_summary
        memory.summary = _truncate_with_notice(merged, SUMMARY_MAX_CHARS)

    def _compute_recent_budget(self) -> int:
        return int(MAX_CONTEXT_TOKENS * RECENT_CONTEXT_RATIO)

    async def build_api_messages(
        self,
        client_id: str,
        new_content: str,
        image_data: Optional[str] = None,
        image_data_list: Optional[list[str]] = None,
        attachments: Optional[list[dict[str, Any]]] = None,
        api_key: Optional[str] = None,
        api_base_url: Optional[str] = None,
        model_id: str = "Qwen/Qwen3-8B",
        tem_context: str = "",
        memory_policy: Optional[dict[str, Any]] = None,
        custom_system_prompt: str = "",
        skills_context: str = "",
        workspace_context: str = "",
    ) -> tuple[list[dict[str, Any]], CompressionStats]:
        memory = self.get_memory(client_id)
        stats = CompressionStats()
        retention_policy = (memory_policy or {}).get("retention", {})
        forgetting_policy = (memory_policy or {}).get("forgetting", {})
        summary_action = (
            forgetting_policy.get("summary", {}).get("action", "retain")
            if isinstance(forgetting_policy.get("summary", {}), dict)
            else "retain"
        )
        retained_fact_labels = {
            str(item.get("fact", ""))
            for item in retention_policy.get("retained_facts", [])
            if isinstance(item, dict)
        }

        attachment_list = [
            attachment
            for attachment in (attachments or [])
            if isinstance(attachment, dict)
        ]

        memory.add_message("user", new_content, attachments=attachment_list)
        stats.total_messages = len(memory.messages)

        if stats.original_tokens > MAX_CONTEXT_TOKENS and len(memory.messages) >= COMPRESS_TRIGGER_MIN_MESSAGES:
            before = memory.total_compressions
            await self._compress_memory(memory, api_key, model_id)
            stats.messages_summarized = memory.total_compressions - before
            stats.summary_text = memory.summary

        api_messages: list[dict[str, Any]] = []
        system_parts = [SYSTEM_PROMPT]
        custom_prompt_block = truncate_system_context_block(
            custom_system_prompt,
            CUSTOM_SYSTEM_PROMPT_MAX_CHARS,
        )
        if custom_prompt_block:
            system_parts.append(f"\nUser-defined system prompt:\n{custom_prompt_block}")
        skills_block = truncate_system_context_block(
            skills_context,
            SKILLS_CONTEXT_MAX_CHARS,
        )
        if skills_block:
            system_parts.append(f"\nAgent skills context:\n{skills_block}")
        workspace_block = truncate_system_context_block(
            workspace_context,
            WORKSPACE_CONTEXT_MAX_CHARS,
        )
        if workspace_block:
            system_parts.append(f"\nWorkspace file context:\n{workspace_block}")
        if tem_context:
            system_parts.append(f"\n{tem_context}")
        if memory.long_term_facts:
            fact_candidates = memory.long_term_facts
            if retained_fact_labels:
                fact_candidates = [
                    fact
                    for fact in memory.long_term_facts
                    if str(fact.get("fact", ""))[:120] in retained_fact_labels
                ]
            if fact_candidates:
                facts_text = "\n".join(f"- {fact['fact']}" for fact in fact_candidates[-FACT_DISPLAY_MAX:])
                system_parts.append(f"\nKnown long-term facts:\n{facts_text}")
        if memory.summary and summary_action != "suppress_from_context":
            system_parts.append(f"\nConversation summary:\n{memory.summary}")

        attachment_context = _build_attachment_context(attachment_list)
        stats.original_tokens = memory.get_total_tokens() + (
            estimate_tokens(attachment_context) if attachment_context else 0
        )
        if attachment_context:
            system_parts.append(f"\n{attachment_context}")

        api_messages.append({"role": "system", "content": "\n".join(system_parts)})

        recent_budget = self._compute_recent_budget()
        recent_candidates = memory.messages[-MAX_RECENT_MESSAGES:]
        kept_recent: list[dict[str, Any]] = []
        used = 0
        for message in reversed(recent_candidates):
            token_count = estimate_tokens(normalize_text(message.get("content", "")))
            if used + token_count > recent_budget and kept_recent:
                continue
            kept_recent.append(message)
            used += token_count
        kept_recent.reverse()

        latest_message = memory.messages[-1] if memory.messages else None
        for message in kept_recent:
            role = message.get("role", "user")
            content = message.get("content", "")
            message_attachments = message.get("attachments")
            if (
                role == "user"
                and isinstance(message_attachments, list)
                and message_attachments
                and message is not latest_message
            ):
                prior_attachment_context = _build_attachment_context(message_attachments)
                if prior_attachment_context:
                    content = f"{content}\n\n{prior_attachment_context}"
            if role in ("user", "assistant"):
                api_messages.append({"role": role, "content": content})
            elif role == "tool_result":
                tool_name = str(message.get("tool_name", "?") or "?")
                api_messages.append({
                    "role": "system",
                    "content": (
                        "Grounded prior tool evidence from conversation history.\n"
                        f"Tool: {tool_name}\n"
                        f"Evidence summary: {truncate_tool_result(content)}"
                    ),
                })

        total_tokens = sum(estimate_tokens(normalize_text(message.get("content", ""))) for message in api_messages)
        while total_tokens > MAX_CONTEXT_TOKENS and len(api_messages) > 2:
            removed = api_messages.pop(1)
            total_tokens -= estimate_tokens(normalize_text(removed.get("content", "")))

        image_payloads = [
            str(item)
            for item in (image_data_list or [])
            if isinstance(item, str) and item.strip()
        ]
        if not image_payloads and image_data:
            image_payloads = [image_data]

        if image_payloads and api_messages:
            last_msg = api_messages[-1]
            if last_msg.get("role") == "user":
                image_mime_types: list[str] = []
                for attachment in attachment_list:
                    attachment_mime = str(attachment.get("mime_type") or attachment.get("content_type") or "")
                    if attachment_mime.startswith("image/"):
                        image_mime_types.append(attachment_mime)
                content_parts: list[dict[str, Any]] = [
                    {"type": "text", "text": normalize_text(last_msg["content"])}
                ]
                for index, image_payload in enumerate(image_payloads):
                    image_mime_type = image_mime_types[index] if index < len(image_mime_types) else "image/jpeg"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{image_mime_type};base64,{image_payload}"},
                    })
                api_messages[-1] = {
                    "role": "user",
                    "content": content_parts,
                }

        stats.messages_sent_to_api = len(api_messages)
        stats.compressed_tokens = total_tokens
        stats.long_term_facts = len(memory.long_term_facts)
        stats.compression_ratio = (
            stats.original_tokens / max(stats.compressed_tokens, 1)
            if stats.original_tokens > 0
            else 1.0
        )
        return api_messages, stats

    def record_assistant_response(self, client_id: str, content: str) -> None:
        memory = self.get_memory(client_id)
        memory.add_message("assistant", content)
        self._extract_facts(memory, content, source="assistant")
        memory.save()

    def record_tool_result(self, client_id: str, tool_name: str, result: Any) -> None:
        memory = self.get_memory(client_id)
        truncated = truncate_tool_result(result)
        memory.add_message("tool_result", truncated, tool_name=tool_name)
        self._extract_facts(memory, truncated, source="tool_result")
        memory.save()

    def get_memory_status(self, client_id: str) -> dict[str, Any]:
        memory = self.get_memory(client_id)
        return {
            "client_id": client_id,
            "message_count": len(memory.messages),
            "total_user_messages": memory.total_user_messages,
            "total_compressions": memory.total_compressions,
            "has_summary": bool(memory.summary),
            "summary_preview": memory.summary[:SUMMARY_PREVIEW_CHARS] if memory.summary else "",
            "long_term_facts": [fact["fact"] for fact in memory.long_term_facts[-FACT_PREVIEW_MAX_ITEMS:]],
            "estimated_tokens": memory.get_total_tokens(),
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
        }

    async def _compress_memory(
        self,
        memory: ConversationMemory,
        api_key: Optional[str],
        model_id: str,
    ) -> None:
        retain_recent = max(RETAIN_RECENT_MIN, int(MAX_RECENT_MESSAGES * RETAIN_RECENT_RATIO))
        old_messages = memory.messages[:-retain_recent]
        if len(old_messages) < SUMMARY_TRIM_MIN_MESSAGES:
            return

        summary_budget_tokens = int(MAX_CONTEXT_TOKENS * SUMMARY_TARGET_RATIO)
        selected = self._select_summary_messages(old_messages, summary_budget_tokens)
        if not selected:
            return

        conversation_text = "\n".join(
            f"{'user' if item['msg'].get('role') == 'user' else 'assistant'}: "
            f"{_truncate_with_notice(item['text'], SUMMARY_LINE_MAX_CHARS)}"
            for item in selected
        )
        conversation_text = _truncate_with_notice(conversation_text, SUMMARY_MAX_INPUT_CHARS)

        if not api_key:
            self._local_semantic_compress(memory, old_messages, retain_recent, selected)
            return

        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "You are a semantic conversation compressor. Produce a compact summary "
                    "that preserves decisions, constraints, configuration, and task state. "
                    "Return only the summary body."
                ),
            },
            {"role": "user", "content": f"Compress the following conversation context:\n\n{conversation_text}"},
        ]

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{(api_base_url or 'https://api.siliconflow.cn/v1').rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_id or "Qwen/Qwen3-8B",
                        "messages": summary_prompt,
                        "temperature": SUMMARY_API_TEMPERATURE,
                        "max_tokens": SUMMARY_MAX_OUTPUT_TOKENS,
                    },
                    timeout=SUMMARY_API_TIMEOUT_SECONDS,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_summary = data["choices"][0]["message"]["content"].strip()
                    self._merge_summary(memory, new_summary)
                    memory.messages = memory.messages[-retain_recent:]
                    memory.total_compressions += 1
                    memory.save()
                    logger.info(
                        "Remote semantic compression succeeded for %s (trimmed %s messages)",
                        memory.client_id,
                        len(old_messages),
                    )
                else:
                    logger.warning("Summary API call failed: %s", resp.status_code)
                    self._local_semantic_compress(memory, old_messages, retain_recent, selected)
        except Exception as exc:
            logger.error("Summary compression failed: %s", exc)
            self._local_semantic_compress(memory, old_messages, retain_recent, selected)

    def _local_semantic_compress(
        self,
        memory: ConversationMemory,
        old_messages: list[dict[str, Any]],
        retain_recent: int,
        selected: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        selected_items = selected or self._select_summary_messages(
            old_messages,
            int(MAX_CONTEXT_TOKENS * SUMMARY_TARGET_RATIO),
        )
        summary = self._compose_local_summary(selected_items)
        if not summary:
            return
        self._merge_summary(memory, summary)
        memory.messages = memory.messages[-retain_recent:]
        memory.total_compressions += 1
        memory.save()
        logger.info("Local semantic compression applied for %s", memory.client_id)

    def _extract_facts(self, memory: ConversationMemory, text: str, source: str = "assistant") -> None:
        normalized = normalize_text(text)
        candidates = [sentence.strip() for sentence in re.split(r"[。\.\n!?；;]", normalized) if sentence.strip()]
        for sentence in candidates:
            token_count = estimate_tokens(sentence)
            if token_count < FACT_MIN_TOKENS or token_count > FACT_MAX_TOKENS:
                continue
            info = text_information_density(sentence)
            if info < FACT_MIN_INFORMATION:
                continue
            fact_type, similarity = self.fact_matcher.classify(sentence)
            if similarity >= FACT_ACCEPT_SIMILARITY:
                combined_type = fact_type if source == "assistant" else f"{source}:{fact_type}"
                memory.add_fact(sentence, fact_type=combined_type, confidence=similarity)


context_engine = ContextEngine()


def reload_context_engine_parameters() -> dict[str, Any]:
    return context_engine.reload_parameters()
