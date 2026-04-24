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
```

Important files:

- `web_interface/backend/app.py`: single backend entrypoint
- `web_interface/backend/enhanced_mcp_manager.py`: runtime MCP management
- `web_interface/backend/memory_control_plane.py`: Memory Plane
- `web_interface/backend/tool_execution_memory.py`: Recipe and Guard memory
- `web_interface/backend/context_engine.py`: context assembly
- `mcp_config.json`: global MCP config source of truth

## Requirements

Current development is Windows-first.

Recommended environment:

- Python `>= 3.12`
- Node.js `18` to `22` LTS
- PowerShell
- npm
- FastMCP / MCP-compatible runtime dependencies

Notes:

- The provided launch scripts are PowerShell-based
- Linux and macOS support may require adapting the startup scripts
- `cdar_mcp` is expected to run as an external persistent FastMCP SSE service

## Quick Start

### 1. Clone the repository

```powershell
git clone <your-repo-url>
cd mirror_mcp
```

### 2. Create a Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you use `uv`, you can also install from `pyproject.toml` / `uv.lock` with your preferred workflow.

### 3. Install frontend dependencies

```powershell
cd web_interface\frontend
npm install
cd ..\..
```

### 4. Configure environment variables

Create a `.env` file in the project root for any model or provider keys required by your deployment.

Typical examples include:

```env
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
SILICONFLOW_API_KEY=...
```

Do not commit secrets.

### 5. Validate MCP configuration

```powershell
python .\scripts\validate_config.py
```

### 6. Start the backend

```powershell
.\scripts\start_backend.ps1
```

This script will:

- activate `.venv` if present
- validate `mcp_config.json`
- ensure the backend port is free
- ensure the external CDAR FastMCP service is available
- launch FastAPI on `http://localhost:8000`

### 7. Start the frontend

Open a second terminal:

```powershell
.\scripts\start_frontend.ps1
```

The frontend will run at:

- `http://localhost:3000`

Backend API docs will be available at:

- `http://localhost:8000/docs`

## Running the External CDAR Service

`cdar_mcp` must run as an external persistent FastMCP server. It should not be imported directly into the backend process.

The backend launcher will try to ensure it is available automatically, but you can also start it manually:

```powershell
.\scripts\start_external_mcp_servers.ps1
```

Default endpoint:

- `http://127.0.0.1:9001/sse`

## MCP Configuration

Global MCP configuration is defined in:

- `mcp_config.json`

Workspace-level MCP configuration can additionally be provided via:

- `.mcp-mirror/mcp.json`

This allows different projects or workspaces to expose different MCP server pools without modifying the main application code.

Design rules:

- MCP tools are registered at the server level, not one-by-one in backend code
- Tool lists are discovered dynamically from the runtime
- Agent or session visibility is controlled at the server level
- Official stdio MCP servers should remain official and should not be replaced by fake wrapper servers

## Research Boundary

MCP Mirror intentionally separates the following concepts:

- `recipe`: learned procedural tool memory from successful real executions
- `guard`: learned counterfactual failure memory from repeated failures
- `skill`: explicit human-authored capability package
- `system prompt`: session-level instruction layer

These are not interchangeable.

In particular:

- `recipe` is not a `skill`
- authored skills are not the main research contribution
- Memory Plane governance is distinct from simple prompt concatenation or generic chat history

## Current Scope

MCP Mirror is currently strongest as:

- a real MCP runtime orchestration system
- a memory-governed tool-use research platform
- a mechanism evaluation environment for routing, failure blocking, and auditable execution

It is not yet positioned as:

- a general-purpose autonomous agent benchmark winner
- a fully unconstrained planner for arbitrary open-world tool ecosystems

## Screens and Panels

The frontend is not just a chat surface. It also acts as a visualization layer for core runtime objects, including:

- main chat workspace
- task center
- MCP runtime center
- Tool Execution Memory panel
- Memory Plane and routing diagnostics
- health and onboarding panels
- approval and replay flows

This makes the internal governance process inspectable rather than hidden inside prompts.

## Development Notes

Single-source operational rules:

1. Backend entrypoint: `web_interface/backend/app.py`
2. MCP config source of truth: `mcp_config.json`
3. Validate configuration before startup
4. CDAR failure should not crash backend startup
5. Secrets must come from environment variables or runtime overrides
6. Architecture changes should be reflected in `docs/ARCHITECTURE.md`

## Testing and Utility Scripts

Useful scripts under `scripts/` include:

- `start_backend.ps1`
- `start_frontend.ps1`
- `start_external_mcp_servers.ps1`
- `validate_config.py`
- `run_all_experiments.py`
- `agent_runtime_smoke.py`
- `browser_runtime_smoke.py`
- `mcp_onboarding_gate.py`

The repository also contains dataset generation, audit, and experiment utilities for internal evaluation workflows.

## Documentation

See:

- `docs/ARCHITECTURE.md`
- `docs/RECIPE_VS_SKILLS_COMPARISON.md`
- `docs/RESEARCH_PLAN.md`
- `docs/PAPER_MAINLINE_EXPERIMENT_MATRIX.md`

## Contributing

Contributions are welcome, especially in the following areas:

- MCP runtime integration
- execution observability
- Memory Plane analysis and diagnostics
- Tool Execution Memory evaluation
- frontend runtime visualization
- safer harness policies and approval flows
- portability beyond Windows-first scripts

If you plan to make architectural changes, please update the corresponding documentation in `docs/`.

## Citation

If you use MCP Mirror in academic work, please cite the corresponding paper or project page once the public citation record is finalized.

Example placeholder:

```bibtex
@software{mcp_mirror,
  title  = {MCP Mirror},
  author = {Author(s) to be added},
  year   = {2026},
  url    = {https://github.com/your-org/mcp-mirror}
}
```

## License

This repository does not yet include a license file.

Before public open-source release, add a `LICENSE` file and update this section accordingly. Common choices for research software include `MIT`, `Apache-2.0`, or `BSD-3-Clause`.
