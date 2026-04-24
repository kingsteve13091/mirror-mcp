# -*- coding: utf-8 -*-

"""Lightweight planner for MCP Mirror Agent Mode.

This planner is intentionally deterministic and scaffold-first.  It gives the
runtime a safe task decomposition without replacing the existing Memory Plane
research path.
"""

from __future__ import annotations

from typing import Any, Dict, List


SYSTEM_OPERATION_HINTS = {
    "terminal": "terminal_command",
    "cmd": "terminal_command",
    "command": "terminal_command",
    "restart": "process_control",
    "log": "log_read",
    "smoke": "browser_smoke",
    "test": "test_runner",
    "browser": "browser_smoke",
}


def build_agent_plan(
    *,
    user_goal: str,
    attachments: List[Dict[str, Any]] | None = None,
    workspace_root: str = "",
    skill_runtime: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    query = str(user_goal or "").strip()
    lowered = query.lower()
    plan_steps: List[Dict[str, Any]] = []

    plan_steps.append(
        {
            "step_id": "step-1",
            "title": "Interpret request and collect evidence",
            "kind": "analysis",
            "action": "summarize_goal",
            "requires_confirmation": False,
        }
    )

    for keyword, action in SYSTEM_OPERATION_HINTS.items():
        if keyword in lowered:
            plan_steps.append(
                {
                    "step_id": f"step-{len(plan_steps) + 1}",
                    "title": f"Run system operation: {action}",
                    "kind": "system_op",
                    "action": action,
                    "requires_confirmation": action in {"terminal_command", "process_control", "workspace_file_op"},
                }
            )
            break

    if any(token in lowered for token in {"http://", "https://", "url", "网页", "网页内容"}):
        plan_steps.append(
            {
                "step_id": f"step-{len(plan_steps) + 1}",
                "title": "Inspect external web content via MCP fetch",
                "kind": "mcp_tool",
                "action": "fetch",
                "requires_confirmation": False,
            }
        )

    if attachments:
        plan_steps.append(
            {
                "step_id": f"step-{len(plan_steps) + 1}",
                "title": "Ground the answer on uploaded attachments",
                "kind": "attachment_grounding",
                "action": "attachment_transparency",
                "requires_confirmation": False,
            }
        )

    runtime_payload = skill_runtime if isinstance(skill_runtime, dict) else {}
    action_templates = runtime_payload.get("action_templates", [])
    if isinstance(action_templates, list):
        for template_index, template in enumerate(action_templates[:6], start=1):
            if not isinstance(template, dict):
                continue
            template_kind = str(template.get("kind") or f"skill_template_{template_index}").strip()
            title = str(template.get("title") or template_kind or "Skill-guided action template").strip()
            plan_steps.append(
                {
                    "step_id": f"step-{len(plan_steps) + 1}",
                    "title": title,
                    "kind": "skill_template",
                    "action": template_kind,
                    "requires_confirmation": bool(template.get("requires_confirmation", False)),
                    "skill_template": template,
                    "source_plane": "skill",
                }
            )

    plan_steps.append(
        {
            "step_id": f"step-{len(plan_steps) + 1}",
            "title": "Verify result and draft user-facing answer",
            "kind": "verification",
            "action": "verify_and_answer",
            "requires_confirmation": False,
        }
    )

    return {
        "goal": query,
        "workspace_root": workspace_root,
        "plan_version": "agent_plan_v1",
        "skill_runtime": runtime_payload,
        "steps": plan_steps,
        "estimated_step_count": len(plan_steps),
    }
