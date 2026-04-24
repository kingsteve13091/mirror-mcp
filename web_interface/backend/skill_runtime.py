"""System-wide authored skill runtime for MCP Mirror.

This module keeps human-authored skills separate from learned Memory Plane
objects while allowing skills to influence runtime behavior beyond prompt text:

- request-time activation and matching
- capability overlays (MCP server / toolset preference)
- chat / agent / system-op scope hints
- lightweight action templates for planners and harness layers
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from fnmatch import fnmatch
from typing import Any, Iterable, Optional
import re

try:
    from agent_skills import AgentSkill, AgentSkillsRegistry
except ImportError:  # pragma: no cover - supports package-style imports in tests/tools
    from .agent_skills import AgentSkill, AgentSkillsRegistry


SKILL_RUNTIME_VERSION = "v1"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _safe_text(value)
    return [text] if text else []


def _normalize_scope_list(scopes: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for scope in scopes:
        value = _safe_text(scope).lower().replace("-", "_")
        if value and value not in normalized:
            normalized.append(value)
    return normalized or ["chat"]


def _normalize_tool_name_set(tools: Iterable[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        server = _safe_text(tool.get("server")).lower()
        name = _safe_text(tool.get("name")).lower()
        if server and name:
            names.add(f"{server}.{name}")
        if name:
            names.add(name)
    return names


def _matches_workspace_patterns(workspace_root: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    normalized_root = _safe_text(workspace_root).replace("/", "\\").lower()
    if not normalized_root:
        return False
    for pattern in patterns:
        candidate = _safe_text(pattern).replace("/", "\\").lower()
        if not candidate:
            continue
        if fnmatch(normalized_root, candidate) or candidate in normalized_root:
            return True
    return False


def _matches_input_patterns(query: str, patterns: list[str]) -> bool:
    text = _safe_text(query)
    if not text or not patterns:
        return False
    for pattern in patterns:
        candidate = _safe_text(pattern)
        if not candidate:
            continue
        try:
            if re.search(candidate, text, re.IGNORECASE):
                return True
        except re.error:
            if candidate.lower() in text.lower():
                return True
    return False


@dataclass
class SkillRuntimeResolution:
    version: str
    requested_skill_ids: list[str]
    active_skill_ids: list[str]
    implicit_skill_ids: list[str]
    skipped_skill_ids: list[str]
    prompt_context: str
    allowed_mcp_servers: list[str]
    preferred_models: list[str]
    action_templates: list[dict[str, Any]]
    recovery_policies: list[str]
    capability_overlay: dict[str, Any]
    skill_cards: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class SkillRuntimeResolver:
    def __init__(self, registry: AgentSkillsRegistry) -> None:
        self.registry = registry

    def _select_implicit_skills(
        self,
        *,
        query: str,
        workspace_root: str,
        scopes: list[str],
        model_id: str,
    ) -> list[AgentSkill]:
        selected: list[AgentSkill] = []
        normalized_scopes = set(_normalize_scope_list(scopes))
        current_model = _safe_text(model_id)
        for skill in self.registry.skills.values():
            if skill.activation_mode not in {"implicit", "workspace_auto", "always"}:
                continue
            skill_scopes = set(_normalize_scope_list(skill.scopes))
            if normalized_scopes and skill_scopes and normalized_scopes.isdisjoint(skill_scopes):
                continue
            if skill.preferred_models and current_model and current_model not in skill.preferred_models:
                continue
            if skill.activation_mode == "always":
                selected.append(skill)
                continue
            if skill.activation_mode == "workspace_auto" and _matches_workspace_patterns(workspace_root, skill.workspace_patterns):
                selected.append(skill)
                continue
            if skill.activation_mode == "implicit" and _matches_input_patterns(query, skill.input_patterns):
                selected.append(skill)
                continue
        return selected

    def resolve(
        self,
        *,
        requested_skill_ids: Optional[list[str]] = None,
        query: str = "",
        workspace_root: str = "",
        scopes: Optional[list[str]] = None,
        model_id: str = "",
        available_tools: Optional[list[dict[str, Any]]] = None,
        current_allowed_mcp_servers: Optional[list[str]] = None,
    ) -> SkillRuntimeResolution:
        requested = [
            _safe_text(skill_id)
            for skill_id in (requested_skill_ids or [])
            if _safe_text(skill_id)
        ]
        explicit_skills = self.registry.get_selected(requested)
        implicit_skills = self._select_implicit_skills(
            query=query,
            workspace_root=workspace_root,
            scopes=scopes or ["chat"],
            model_id=model_id,
        )

        selected_by_id: dict[str, AgentSkill] = {}
        for skill in [*explicit_skills, *implicit_skills]:
            selected_by_id[skill.id] = skill
        active_skills = list(selected_by_id.values())
        available_tool_names = _normalize_tool_name_set(available_tools or [])
        base_allowed_servers = [item for item in _safe_list(current_allowed_mcp_servers) if item]

        prompt_context = self.registry.render_selected_context([skill.id for skill in active_skills])

        allowed_servers_set = {item.lower() for item in base_allowed_servers}
        preferred_models: list[str] = []
        recovery_policies: list[str] = []
        action_templates: list[dict[str, Any]] = []
        toolsets: list[str] = []
        tool_hints: list[str] = []
        confirmation_required = False
        skill_cards: list[dict[str, Any]] = []

        for skill in active_skills:
            for server_name in skill.allowed_mcp_servers:
                value = _safe_text(server_name).lower()
                if value:
                    allowed_servers_set.add(value)
            for model_name in skill.preferred_models:
                value = _safe_text(model_name)
                if value and value not in preferred_models:
                    preferred_models.append(value)
            for policy in skill.recovery_policies:
                value = _safe_text(policy)
                if value and value not in recovery_policies:
                    recovery_policies.append(value)
            for toolset in skill.allowed_toolsets:
                value = _safe_text(toolset)
                if value and value not in toolsets:
                    toolsets.append(value)
            for template in skill.action_templates:
                if template not in action_templates:
                    action_templates.append(template)
            for allowed_tool in skill.allowed_tools:
                value = _safe_text(allowed_tool).lower()
                if value and (not available_tool_names or value in available_tool_names):
                    if value not in tool_hints:
                        tool_hints.append(value)
            confirmation_required = confirmation_required or bool(skill.requires_confirmation)
            skill_cards.append(
                {
                    "id": skill.id,
                    "name": skill.name,
                    "activation_mode": skill.activation_mode,
                    "scopes": skill.scopes,
                    "allowed_mcp_servers": skill.allowed_mcp_servers,
                    "allowed_toolsets": skill.allowed_toolsets,
                    "preferred_models": skill.preferred_models,
                    "recovery_policies": skill.recovery_policies,
                    "requires_confirmation": skill.requires_confirmation,
                    "visibility": skill.visibility,
                    "metadata": skill.metadata,
                }
            )

        skipped = [skill_id for skill_id in requested if skill_id not in selected_by_id]
        capability_overlay = {
            "allowed_mcp_servers": sorted(allowed_servers_set),
            "allowed_toolsets": toolsets,
            "tool_hints": tool_hints,
            "requires_confirmation": confirmation_required,
            "visibility": sorted({skill.visibility for skill in active_skills if _safe_text(skill.visibility)}),
            "scopes": sorted({scope for skill in active_skills for scope in _normalize_scope_list(skill.scopes)}),
        }

        return SkillRuntimeResolution(
            version=SKILL_RUNTIME_VERSION,
            requested_skill_ids=requested,
            active_skill_ids=[skill.id for skill in active_skills],
            implicit_skill_ids=[skill.id for skill in implicit_skills if skill.id in selected_by_id and skill.id not in requested],
            skipped_skill_ids=skipped,
            prompt_context=prompt_context,
            allowed_mcp_servers=sorted(allowed_servers_set),
            preferred_models=preferred_models,
            action_templates=action_templates,
            recovery_policies=recovery_policies,
            capability_overlay=capability_overlay,
            skill_cards=skill_cards,
        )


__all__ = [
    "SKILL_RUNTIME_VERSION",
    "SkillRuntimeResolution",
    "SkillRuntimeResolver",
]
