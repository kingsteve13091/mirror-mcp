"""
Agent skills registry for MCP Mirror.

Design goals:
- support SKILL.md-style authored capability packages
- stay compatible with Anthropic-style and AgentSkills-style frontmatter where feasible
- remain explicitly separate from learned recipe memory

This module intentionally does not merge skills with recipe/guard memory:
- recipe: learned procedural runtime memory
- guard: learned counterfactual failure memory
- skill: human-authored capability package
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import logging
import os
import re
import sys
import json

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_FILE_NAME = "SKILL.md"
SKILL_BODY_PREVIEW_MAX_CHARS = 240
SKILL_RESOURCE_FILE_LIMIT = 24
OPENAI_METADATA_RELATIVE_PATH = Path("agents") / "openai.yaml"
CLAUDE_SKILL_ROOT = Path(".claude") / "skills"
OPENAI_SKILL_ROOT = Path(".agents") / "skills"
PROJECT_SKILL_ROOT = Path("skills")
PROJECT_SKILL_CONFIG_PATH = Path(".mcp-mirror") / "skills.json"
ENV_EXTERNAL_SKILL_DIRS = "MCP_MIRROR_SKILL_DIRS"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_safe_text(item) for item in value if _safe_text(item)]
    text = _safe_text(value)
    return [text] if text else []


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = _safe_text(value).lower().replace("-", "_")
    return normalized if normalized in allowed else default


def _current_platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _expand_external_skill_path(raw_value: str) -> Path | None:
    value = _safe_text(raw_value)
    if not value:
        return None
    try:
        expanded = os.path.expandvars(os.path.expanduser(value))
        path = Path(expanded)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path
    except Exception:
        return None


@dataclass
class AgentSkill:
    id: str
    name: str
    description: str
    trigger: str
    source_path: str
    body: str
    root_path: str
    loader: str = "mcp_mirror"
    compatibility: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    openai_config: dict[str, Any] = field(default_factory=dict)
    license: str = ""
    resources: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    activation_mode: str = "manual"
    scopes: list[str] = field(default_factory=lambda: ["chat"])
    platform_targets: list[str] = field(default_factory=list)
    allowed_mcp_servers: list[str] = field(default_factory=list)
    allowed_toolsets: list[str] = field(default_factory=list)
    preferred_models: list[str] = field(default_factory=list)
    workspace_patterns: list[str] = field(default_factory=list)
    input_patterns: list[str] = field(default_factory=list)
    action_templates: list[dict[str, Any]] = field(default_factory=list)
    recovery_policies: list[str] = field(default_factory=list)
    visibility: str = "normal"
    requires_confirmation: bool = False
    runtime_hints: dict[str, Any] = field(default_factory=dict)
    external_root: bool = False

    def to_summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["body_preview"] = self.body[:SKILL_BODY_PREVIEW_MAX_CHARS]
        payload["body_length"] = len(self.body)
        payload.pop("body", None)
        return payload


def _parse_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(raw_text.strip())
    if not match:
        return {}, raw_text.strip()

    header_text = match.group(1)
    body = match.group(2).strip()
    parsed = yaml.safe_load(header_text) or {}
    if not isinstance(parsed, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML object")
    return parsed, body


class AgentSkillsRegistry:
    def __init__(self) -> None:
        self.skills: dict[str, AgentSkill] = {}
        self.failed: list[dict[str, str]] = []
        self.reload()

    def _configured_external_roots(self) -> list[Path]:
        roots: list[Path] = []

        env_value = os.environ.get(ENV_EXTERNAL_SKILL_DIRS, "")
        for raw_item in re.split(r"[;\n]", env_value):
            path = _expand_external_skill_path(raw_item)
            if path is not None:
                roots.append(path)

        config_path = PROJECT_ROOT / PROJECT_SKILL_CONFIG_PATH
        if config_path.exists() and config_path.is_file():
            try:
                parsed = json.loads(config_path.read_text(encoding="utf-8"))
                configured = parsed.get("external_skill_dirs", []) if isinstance(parsed, dict) else []
                for item in configured if isinstance(configured, list) else []:
                    path = _expand_external_skill_path(str(item))
                    if path is not None:
                        roots.append(path)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", config_path, exc)

        return roots

    def get_external_skill_config(self) -> dict[str, Any]:
        config_path = PROJECT_ROOT / PROJECT_SKILL_CONFIG_PATH
        external_dirs: list[str] = []
        if config_path.exists() and config_path.is_file():
            try:
                parsed = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    external_dirs = [
                        _safe_text(item)
                        for item in parsed.get("external_skill_dirs", [])
                        if _safe_text(item)
                    ]
            except Exception as exc:
                return {
                    "path": str(config_path),
                    "external_skill_dirs": [],
                    "exists": True,
                    "error": str(exc),
                }
        return {
            "path": str(config_path),
            "external_skill_dirs": external_dirs,
            "exists": config_path.exists(),
            "env_value": os.environ.get(ENV_EXTERNAL_SKILL_DIRS, ""),
        }

    def save_external_skill_config(self, external_skill_dirs: list[str]) -> dict[str, Any]:
        config_path = PROJECT_ROOT / PROJECT_SKILL_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "external_skill_dirs": [
                _safe_text(item)
                for item in external_skill_dirs
                if _safe_text(item)
            ]
        }
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_external_skill_config()

    def _candidate_skill_roots(self) -> list[Path]:
        roots: list[Path] = []

        # OpenAI Codex reads repo-level `.agents/skills` from the current working
        # directory up to the repository root. Mirror that behavior for local
        # authored skills so nested working directories still inherit parent
        # repo skills.
        current_dir = Path.cwd().resolve()
        try:
            relative_parts = current_dir.relative_to(PROJECT_ROOT).parts
            repo_search_roots = [PROJECT_ROOT / Path(*relative_parts[:index]) for index in range(len(relative_parts) + 1)]
        except Exception:
            repo_search_roots = [PROJECT_ROOT]

        for base in repo_search_roots:
            roots.append(base / OPENAI_SKILL_ROOT)

        roots.extend(
            [
                PROJECT_ROOT / CLAUDE_SKILL_ROOT,
                PROJECT_ROOT / PROJECT_SKILL_ROOT,
            ]
        )
        roots.extend(self._configured_external_roots())

        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(root)
        return deduped

    def _discover_skill_files(self) -> list[Path]:
        files: list[Path] = []
        for root in self._candidate_skill_roots():
            if not root.exists():
                continue
            files.extend(root.rglob(SKILL_FILE_NAME))
        return sorted(set(files))

    def _relative_root_for(self, skill_file: Path) -> Path | None:
        for candidate in self._candidate_skill_roots():
            try:
                if candidate.exists() and skill_file.is_relative_to(candidate):
                    return candidate
            except Exception:
                continue
        return None

    def _skill_id_for(self, skill_file: Path, root: Path | None) -> str:
        relative_path = skill_file.relative_to(root) if root else skill_file.name
        skill_id = str(relative_path.parent).replace("\\", "/").strip("./")
        if not skill_id:
            skill_id = skill_file.parent.name
        return skill_id

    def _collect_resources(self, skill_dir: Path) -> list[str]:
        resources: list[str] = []
        for path in sorted(skill_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name == SKILL_FILE_NAME:
                continue
            try:
                resources.append(str(path.relative_to(skill_dir)).replace("\\", "/"))
            except Exception:
                resources.append(path.name)
            if len(resources) >= SKILL_RESOURCE_FILE_LIMIT:
                break
        return resources

    def _load_openai_config(self, skill_dir: Path) -> dict[str, Any]:
        config_path = skill_dir / OPENAI_METADATA_RELATIVE_PATH
        if not config_path.exists():
            return {}
        try:
            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            return parsed if isinstance(parsed, dict) else {}
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", config_path, exc)
            return {"_loader_error": str(exc)}

    def _validate_skill(
        self,
        *,
        skill_id: str,
        skill_file: Path,
        meta: dict[str, Any],
        body: str,
    ) -> AgentSkill:
        diagnostics: list[str] = []
        skill_dir = skill_file.parent
        declared_name = _safe_text(meta.get("name"))
        expected_name = skill_dir.name

        if not declared_name:
            declared_name = expected_name
            diagnostics.append("missing_frontmatter_name_fell_back_to_directory_name")

        if declared_name != expected_name:
            diagnostics.append("frontmatter_name_differs_from_directory_name")

        description = _safe_text(meta.get("description"))
        if not description:
            description = "No skill description provided."
            diagnostics.append("missing_frontmatter_description")

        trigger = _safe_text(meta.get("trigger")) or "manual"
        compatibility = _safe_string_list(meta.get("compatibility"))
        allowed_tools = _safe_string_list(
            meta.get("allowed-tools", meta.get("allowed_tools")),
        )
        metadata = _safe_dict(meta.get("metadata"))
        license_name = _safe_text(meta.get("license"))
        activation_mode = _normalize_choice(
            meta.get("activation_mode", meta.get("activation-mode", trigger)),
            {"manual", "implicit", "workspace_auto", "always"},
            "manual",
        )
        scopes = _safe_string_list(meta.get("scope", meta.get("scopes")))
        if not scopes:
            scopes = ["chat"]
        platform_targets = _safe_string_list(
            meta.get("platform_targets", meta.get("platform-targets", meta.get("platforms")))
        )
        allowed_mcp_servers = _safe_string_list(
            meta.get("allowed_mcp_servers", meta.get("allowed-mcp-servers", meta.get("allowMCPs")))
        )
        allowed_toolsets = _safe_string_list(
            meta.get("allowed_toolsets", meta.get("allowed-toolsets"))
        )
        preferred_models = _safe_string_list(
            meta.get("preferred_models", meta.get("preferred-models"))
        )
        workspace_patterns = _safe_string_list(
            meta.get("workspace_patterns", meta.get("workspace-patterns"))
        )
        input_patterns = _safe_string_list(
            meta.get("input_patterns", meta.get("input-patterns", meta.get("triggers")))
        )
        action_templates = _safe_list_of_dicts(
            meta.get("action_templates", meta.get("action-templates"))
        )
        recovery_policies = _safe_string_list(
            meta.get("recovery_policies", meta.get("recovery-policies"))
        )
        visibility = _normalize_choice(
            meta.get("visibility"),
            {"normal", "compact", "debug", "hidden"},
            "normal",
        )
        requires_confirmation = _safe_bool(
            meta.get("requires_confirmation", meta.get("requires-confirmation")),
            False,
        )
        runtime_hints = _safe_dict(meta.get("runtime_hints", meta.get("runtime-hints")))

        if "tool_routing" in scopes and not (allowed_mcp_servers or allowed_toolsets or allowed_tools):
            diagnostics.append("tool_routing_scope_without_capability_filters")
        current_platform = _current_platform_name()
        normalized_platforms = {item.lower() for item in platform_targets}
        if normalized_platforms and current_platform not in normalized_platforms and "all" not in normalized_platforms:
            diagnostics.append(f"platform_target_mismatch:{current_platform}")

        openai_config = self._load_openai_config(skill_dir)
        openai_dependencies = openai_config.get("dependencies", {}) if isinstance(openai_config, dict) else {}
        if isinstance(openai_dependencies, dict):
            dependency_tools = openai_dependencies.get("tools", [])
            if isinstance(dependency_tools, list):
                for item in dependency_tools:
                    if isinstance(item, dict):
                        value = _safe_text(item.get("value"))
                        if value and value not in allowed_tools:
                            allowed_tools.append(value)
        interface_config = openai_config.get("interface", {}) if isinstance(openai_config, dict) else {}
        if isinstance(interface_config, dict):
            display_name = _safe_text(interface_config.get("display_name"))
            short_description = _safe_text(interface_config.get("short_description"))
            if display_name:
                metadata.setdefault("display_name", display_name)
            if short_description:
                metadata.setdefault("short_description", short_description)
        policy_config = openai_config.get("policy", {}) if isinstance(openai_config, dict) else {}
        if isinstance(policy_config, dict) and "allow_implicit_invocation" in policy_config:
            metadata.setdefault(
                "allow_implicit_invocation",
                bool(policy_config.get("allow_implicit_invocation")),
            )
            compatibility = list(dict.fromkeys([*compatibility, "openai-codex-skills"]))
            if policy_config.get("allow_implicit_invocation") and activation_mode == "manual":
                activation_mode = "implicit"

        if not body.strip():
            diagnostics.append("empty_skill_body")

        return AgentSkill(
            id=skill_id,
            name=declared_name,
            description=description,
            trigger=trigger,
            source_path=str(skill_file),
            body=body.strip(),
            root_path=str(skill_dir),
            compatibility=compatibility,
            allowed_tools=allowed_tools,
            metadata=metadata,
            openai_config=openai_config,
            license=license_name,
            resources=self._collect_resources(skill_dir),
            diagnostics=diagnostics,
            activation_mode=activation_mode,
            scopes=list(dict.fromkeys(scopes)),
            platform_targets=list(dict.fromkeys(platform_targets)),
            allowed_mcp_servers=list(dict.fromkeys(allowed_mcp_servers)),
            allowed_toolsets=list(dict.fromkeys(allowed_toolsets)),
            preferred_models=list(dict.fromkeys(preferred_models)),
            workspace_patterns=list(dict.fromkeys(workspace_patterns)),
            input_patterns=list(dict.fromkeys(input_patterns)),
            action_templates=action_templates,
            recovery_policies=list(dict.fromkeys(recovery_policies)),
            visibility=visibility,
            requires_confirmation=requires_confirmation,
            runtime_hints=runtime_hints,
            external_root=not str(skill_file.resolve()).lower().startswith(str(PROJECT_ROOT.resolve()).lower()),
        )

    def reload(self) -> dict[str, Any]:
        loaded: dict[str, AgentSkill] = {}
        failed: list[dict[str, str]] = []
        for skill_file in self._discover_skill_files():
            try:
                raw_text = skill_file.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(raw_text)
                root = self._relative_root_for(skill_file)
                skill_id = self._skill_id_for(skill_file, root)
                loaded[skill_id] = self._validate_skill(
                    skill_id=skill_id,
                    skill_file=skill_file,
                    meta=meta,
                    body=body,
                )
            except Exception as exc:
                logger.warning("Failed to load skill from %s: %s", skill_file, exc)
                failed.append({"source_path": str(skill_file), "error": str(exc)})

        self.skills = loaded
        self.failed = failed
        logger.info("AgentSkillsRegistry loaded %s skills", len(self.skills))
        return {
            "count": len(self.skills),
            "ids": sorted(self.skills.keys()),
            "failed": failed,
        }

    def list_summaries(self) -> list[dict[str, Any]]:
        return [
            skill.to_summary()
            for skill in sorted(self.skills.values(), key=lambda item: item.name.lower())
        ]

    def get_skill_roots_summary(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for root in self._candidate_skill_roots():
            try:
                exists = root.exists()
                skill_count = len(list(root.rglob(SKILL_FILE_NAME))) if exists else 0
                items.append(
                    {
                        "path": str(root),
                        "exists": exists,
                        "skill_count": skill_count,
                        "external": not str(root.resolve()).lower().startswith(str(PROJECT_ROOT.resolve()).lower()) if exists else False,
                    }
                )
            except Exception as exc:
                items.append({"path": str(root), "exists": False, "skill_count": 0, "error": str(exc), "external": False})
        return items

    def get_selected(self, skill_ids: list[str] | None) -> list[AgentSkill]:
        selected: list[AgentSkill] = []
        for skill_id in skill_ids or []:
            skill = self.skills.get(str(skill_id).strip())
            if skill is not None:
                selected.append(skill)
        return selected

    def render_selected_context(self, skill_ids: list[str] | None) -> str:
        selected = self.get_selected(skill_ids)
        if not selected:
            return ""

        lines = [
            "Enabled agent skills for this conversation:",
            "These are explicit human-authored capability packages, not learned recipe memory.",
            "Treat them as authored operating guidance layered on top of the base system prompt.",
        ]
        for skill in selected:
            lines.extend(
                [
                    "",
                    f"## Skill: {skill.name}",
                    f"Skill ID: {skill.id}",
                    f"Description: {skill.description}",
                    f"Trigger: {skill.trigger}",
                ]
            )
            if skill.compatibility:
                lines.append(
                    "Compatibility: " + ", ".join(skill.compatibility)
                )
            if skill.allowed_tools:
                lines.append(
                    "Allowed tools: " + ", ".join(skill.allowed_tools)
                )
            if skill.license:
                lines.append(f"License: {skill.license}")
            if skill.resources:
                lines.append(
                    "Skill resources: " + ", ".join(skill.resources[:SKILL_RESOURCE_FILE_LIMIT])
                )
            if skill.diagnostics:
                lines.append("Loader diagnostics: " + ", ".join(skill.diagnostics))
            lines.extend(
                [
                    "Instructions:",
                    skill.body,
                ]
            )
        return "\n".join(lines).strip()


agent_skills_registry = AgentSkillsRegistry()
