# MCP Mirror

MCP Mirror is a visual MCP orchestration system for building and studying memory-governed tool-using LLM agents.

It combines a React + TypeScript frontend, a FastAPI backend, real MCP runtimes, and an explicit memory governance layer designed for long-horizon tool use. Rather than treating tool calls as prompt-only behavior, MCP Mirror separates intent generation from routing, execution control, verification, and experience write-back.

## Why MCP Mirror

Most MCP clients focus on connecting tools and displaying results. MCP Mirror is built around a different question:

How can an agent use tools stably, audibly, and learnably over many turns?

The system introduces three research-facing ideas:

- `Memory Plane`: an explicit governance layer between task intent and tool execution
- `Recipe`: learned procedural memory distilled from successful real tool executions
- `Guard`: learned failure memory distilled from repeated or risky failed executions

Together, these components support memory-aware routing, failure prevention, execution recovery, and auditable replay.

## Core Features

- Real MCP runtime integration with official and external MCP servers
- Dynamic tool discovery from configured MCP servers at runtime
- Explicit `Memory Plane` for routing, retention, forgetting, attribution, and rollback
- `Tool Execution Memory` with dual-channel memory:
  - `recipe` for successful procedural reuse
  - `guard` for repeated failure prevention
- Harness-style execution governance for:
  - parameter compilation
  - schema-aware validation
  - pre-execution checks
  - result verification
  - bounded recovery
- Structured event streaming to the frontend:
  - `action_event`
  - `tool_result`
  - `response_start`
  - `response_delta`
  - `response_done`
- Workspace-level MCP server pools via `.mcp-mirror/mcp.json`
- Lightweight agent runtime with task lifecycle, approvals, replay, and system-operation control
- External multimodal reasoning support via `cdar_mcp`

## Architecture Overview

MCP Mirror is organized around the following layers:

1. Frontend Interaction Layer
- chat workspace
- settings
- task center
- MCP runtime panels
- Tool Execution Memory and Memory Plane visualization panels

2. Backend Orchestration Layer
- session management
- context assembly
- provider dispatch
- stateful orchestration

3. Memory Governance Layer
- routing suggestions
- retention and forgetting
- attribution
- rollback
- governance ledger

4. Tool Execution Memory Layer
- `recipe` abstraction from successful trajectories
- `guard` abstraction from failed or risky trajectories

5. Harness Runtime
- parameter compilation
- schema validation
- path and URL resolution
- prechecks
- approval gates
- bounded recovery

6. Real Runtime Layer
- official MCP servers
- workspace MCP servers
- external `cdar_mcp` FastMCP service

The key design principle is simple:

Do not trust model-declared pseudo-calls. Trust only restricted real runtime events.

## Repository Layout

```text
mirror_mcp/
|- AGENTS.md
|- README.md
|- mcp_config.json
|- cdar_mcp.py
|- artifacts/
|- datasets/
|- docs/
|- experiments/
|- scripts/
`- web_interface/
   |- backend/
   `- frontend/
