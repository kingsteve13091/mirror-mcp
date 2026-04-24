---
name: system-executor
description: Adds cautious system execution guidance for terminal-backed agent work, workspace inspection, and approval-aware recovery.
trigger: manual
activation_mode: implicit
scope:
  - chat
  - agent_task
  - system_op
allowed_mcp_servers:
  - filesystem
allowed_toolsets:
  - workspace-inspection
  - terminal-ops
preferred_models:
  - Qwen/Qwen3-VL-8B-Instruct
input_patterns:
  - "(?i)terminal|cmd|command|shell|workspace|project"
recovery_policies:
  - prefer_read_only_first
  - require_confirmation_before_mutation
action_templates:
  - kind: inspect_workspace
    title: Inspect workspace before execution
    steps:
      - list files
      - identify target path
      - explain intended mutation
  - kind: guarded_terminal_run
    title: Use approval-aware terminal execution
    steps:
      - classify risk
      - request approval when needed
      - capture result and summarize
requires_confirmation: true
visibility: normal
compatibility:
  - mcp-mirror-skills
license: project-local
metadata:
  display_name: System Executor
  domain: runtime-operations
  authoring_plane: authored-skill
runtime_hints:
  prefer_workspace_context: true
  prefer_agent_task_mode: true
---
Use this skill when the conversation is moving from ordinary tool chat into real system execution.

Operating rules:

1. Keep terminal-backed work approval-aware and auditable.
2. Prefer inspecting the workspace before proposing mutations.
3. Summarize what will run, what could change, and what evidence was observed.
4. Keep this skill separate from Recipe / Guard / Memory Plane research objects.
