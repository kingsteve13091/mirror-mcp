# -*- coding: utf-8 -*-

"""Policy evaluation for agent system-operation actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


ALLOWED_SYSTEM_ACTIONS = {
    "terminal_command",
    "process_control",
    "test_runner",
    "log_read",
    "browser_smoke",
    "workspace_file_op",
}


HIGH_RISK_COMMAND_HINTS = {
    "rm ",
    "rmdir ",
    "del ",
    "erase ",
    "format ",
    "shutdown ",
    "reboot ",
    "reg delete",
    "sc delete",
    "takeown ",
    "icacls ",
}


def normalize_system_action(value: Any) -> str:
    action = str(value or "").strip().lower()
    if action not in ALLOWED_SYSTEM_ACTIONS:
        return ""
    return action


def normalize_policy_action(value: Any) -> str:
    action = str(value or "confirm").strip().lower()
    if action not in {"allow", "confirm", "deny"}:
        return "confirm"
    return action


def normalize_path(value: Any) -> str:
    return str(value or "").strip().replace("/", "\\")


def path_within_workspace(path_text: str, workspace_root: str) -> bool:
    try:
        root = Path(workspace_root).resolve()
        target = Path(path_text).resolve()
        return str(target).lower().startswith(str(root).lower())
    except Exception:
        return False


@dataclass
class SystemOperationDecision:
    allowed: bool
    requires_confirmation: bool
    policy_action: str
    reason: str
    suggestion: str
    risk_level: str

    def to_payload(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "policy_action": self.policy_action,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "risk_level": self.risk_level,
        }


def evaluate_system_operation_policy(
    *,
    action_type: str,
    payload: Dict[str, Any],
    policy_state: Dict[str, Any],
    workspace_root: str = "",
    policy_confirmed: bool = False,
) -> SystemOperationDecision:
    normalized_action = normalize_system_action(action_type)
    if not normalized_action:
        return SystemOperationDecision(
            allowed=False,
            requires_confirmation=False,
            policy_action="deny",
            reason=f"Unsupported system operation action: {action_type}",
            suggestion="Choose a supported system operation action.",
            risk_level="high",
        )

    default_actions = {
        "terminal_command": "confirm",
        "process_control": "confirm",
        "test_runner": "allow",
        "log_read": "allow",
        "browser_smoke": "allow",
        "workspace_file_op": "confirm",
    }
    configured_actions = policy_state.get("system_actions", {}) if isinstance(policy_state, dict) else {}
    action = normalize_policy_action(configured_actions.get(normalized_action, default_actions.get(normalized_action, "confirm")))
    risk_level = "high" if normalized_action in {"terminal_command", "process_control", "workspace_file_op"} else "medium"
    reason = f"System operation policy marked {normalized_action} as {action}."
    suggestion = "Review the action and retry after explicit confirmation."

    if normalized_action == "terminal_command":
        command = str(payload.get("command", "") or "").strip().lower()
        working_directory = normalize_path(payload.get("working_directory") or workspace_root)
        if not command:
            return SystemOperationDecision(False, False, "deny", "Terminal command cannot be empty.", "Provide a command to run.", "high")
        if any(hint in command for hint in HIGH_RISK_COMMAND_HINTS):
            return SystemOperationDecision(
                allowed=False,
                requires_confirmation=False,
                policy_action="deny",
                reason="Command contains a destructive or privileged pattern and is denied by system policy.",
                suggestion="Use a safer diagnostic command or run the command manually outside the agent runtime.",
                risk_level="high",
            )
        if workspace_root and working_directory and not path_within_workspace(working_directory, workspace_root):
            return SystemOperationDecision(
                allowed=False,
                requires_confirmation=False,
                policy_action="deny",
                reason="Terminal working directory is outside the active workspace root.",
                suggestion="Switch to a workspace-safe directory before retrying.",
                risk_level="high",
            )
        if action == "allow":
            action = "confirm"
            reason = "Terminal command execution always requires confirmation in the current safety profile."

    if normalized_action == "workspace_file_op":
        path_text = normalize_path(payload.get("path") or payload.get("target_path") or "")
        if workspace_root and path_text and not path_within_workspace(path_text, workspace_root):
            return SystemOperationDecision(
                allowed=False,
                requires_confirmation=False,
                policy_action="deny",
                reason="Workspace file operation points outside the active workspace root.",
                suggestion="Restrict the file operation to the current workspace.",
                risk_level="high",
            )

    if action == "deny":
        return SystemOperationDecision(
            allowed=False,
            requires_confirmation=False,
            policy_action="deny",
            reason=reason,
            suggestion="Update the system-operation policy if this action should be allowed.",
            risk_level=risk_level,
        )

    if action == "confirm" and not policy_confirmed:
        return SystemOperationDecision(
            allowed=False,
            requires_confirmation=True,
            policy_action="confirm",
            reason=reason,
            suggestion=suggestion,
            risk_level=risk_level,
        )

    return SystemOperationDecision(
        allowed=True,
        requires_confirmation=False,
        policy_action=action,
        reason=reason,
        suggestion="",
        risk_level=risk_level,
    )
