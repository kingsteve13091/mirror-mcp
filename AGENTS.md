# AGENTS.md — MCP Mirror System Guide

> Agent and developer entry map. This file is intentionally short and operational.
> Updated: 2026-04-16

## Project Overview

MCP Mirror is a visual MCP orchestration system.

- Frontend: React + TypeScript
- Backend: FastAPI
- MCP runtime: FastMCP client + official / external MCP servers

The research mainline is not a generic chat product. It is a memory-centered MCP tool system with:

- Tool Execution Memory (`recipe`)
- Failure memory (`guard`)
- Memory Plane governance over routing, retention, forgetting, attribution, and rollback

## Quick Start

```powershell
# 1) Start backend
.\scripts\start_backend.ps1

# 2) Start frontend
.\scripts\start_frontend.ps1
```

## CDAR Runtime

`cdar_mcp` must run as an external persistent FastMCP server.
It must not be imported into the backend process.

Default endpoint in `mcp_config.json`:

- `http://127.0.0.1:9001/sse`

Example manual startup:

```powershell
& "C:\Users\cys56\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\fastmcp.exe" run D:\mirror_mcp\cdar_mcp.py:mcp --transport sse --host 127.0.0.1 --port 9001 --path /sse
```

## Directory Layout

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
```

Key backend files:

- `web_interface/backend/app.py`
- `web_interface/backend/enhanced_mcp_manager.py`
- `web_interface/backend/tool_execution_memory.py`
- `web_interface/backend/memory_control_plane.py`
- `web_interface/backend/context_engine.py`
- `web_interface/backend/agent_skills.py`

## Rules

1. Single backend entrypoint: `web_interface/backend/app.py`
2. Single MCP config source: `mcp_config.json`
3. Validate config before startup: `scripts/validate_config.py`
4. CDAR failure must not crash backend startup
5. Secrets must come from environment variables or runtime overrides, not hardcoded files
6. Architecture changes must be reflected in `docs/ARCHITECTURE.md`
7. Official stdio MCP servers should stay official; do not replace them with fake local wrapper servers

## Research Boundary

Keep these objects separate:

- `recipe`: learned procedural tool memory from successful real executions
- `guard`: learned counterfactual failure memory from repeated failures
- `skill`: explicit human-authored capability package
- `system prompt`: session-level instruction layer

Do not describe `recipe` as `skill`.
Do not describe authored `skills` as the research contribution.

## Skills Layer

The repository supports authored skill-package loading from:

- `skills/`
- `.claude/skills/`
- `.agents/skills/`

This is a compatibility layer for human-authored agent capability packages.
It is not the same thing as Recipe Memory.

## Key Docs

- Architecture: `docs/ARCHITECTURE.md`
- Recipe vs Skills boundary: `docs/RECIPE_VS_SKILLS_COMPARISON.md`
- Research plan: `docs/RESEARCH_PLAN.md`
- Experiment matrix: `docs/PAPER_MAINLINE_EXPERIMENT_MATRIX.md`
- Backend API docs at runtime: `http://localhost:8000/docs`
