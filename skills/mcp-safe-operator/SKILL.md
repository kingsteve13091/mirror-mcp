---
name: mcp-safe-operator
description: Adds cautious operational guidance for real MCP tool use, runtime checks, and provider validation.
trigger: manual
compatibility:
  - anthropic-skills
  - agentskills
license: project-local
allowed-tools:
  - mcp
  - provider-runtime
metadata:
  display_name: MCP Safe Operator
  domain: mcp-operations
---
Use this skill when the user is operating the live MCP Mirror system.

Operating rules:

1. Prefer real runtime status over assumed state.
2. If a backend route is missing, say the feature is unavailable in the current process.
3. Keep MCP server configuration, provider keys, and runtime overrides explicit.
4. Do not describe UI-only toggles as effective unless they change backend behavior.
