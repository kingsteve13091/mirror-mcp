<p align="center">
  <img src="./data/banner.png" alt="MCP Mirror Banner" width="100%">
</p>

# MCP Mirror

MCP Mirror is a visual MCP orchestration system for building and studying memory-governed tool-using LLM agents.

It combines a React + TypeScript frontend, a FastAPI backend, real MCP runtimes, and an explicit memory governance layer for long-horizon tool use. Instead of treating tool calls as prompt-only behavior, MCP Mirror separates intent generation from routing, execution control, verification, and experience write-back.

## Why MCP Mirror

Most MCP clients focus on connecting tools and displaying results. MCP Mirror is built around a different question:

How can an agent use tools stably, audibly, and learnably over many turns?

The system introduces three core ideas:

- `Memory Plane`: an explicit governance layer between task intent and tool execution
- `Recipe`: learned procedural memory distilled from successful real tool executions
- `Guard`: learned failure memory distilled from repeated or risky failed executions

Together, these components support memory-aware routing, failure prevention, bounded recovery, and auditable replay.

## Core Features

- Real MCP runtime integration with official and external MCP servers
- Dynamic tool discovery from configured MCP servers at runtime
- Explicit `Memory Plane` for routing, retention, forgetting, attribution, and rollback
- `Tool Execution Memory` with dual-channel memory:
  - `recipe` for successful procedural reuse
  - `guard` for repeated failure prevention
- Harness-style execution governance for parameter compilation, schema-aware validation, prechecks, result verification, and bounded recovery
- Structured runtime event streaming to the frontend
- Workspace-level MCP server pools
- Lightweight agent runtime with approvals, replay, and task lifecycle control
- External multimodal reasoning support via custom FastMCP services

## Design Principle

Do not trust model-declared pseudo-calls. Trust only restricted real runtime events.

## What You Can See in the UI

The frontend is not just a chat surface. It also exposes the system's internal execution objects, including:

- main chat workspace
- MCP runtime center
- Tool Execution Memory panel
- Memory Plane and routing diagnostics
- approval and replay flows
- task and health panels

This makes the governance process inspectable instead of hiding it inside prompts.

## Requirements

Current development is Windows-first.

- Python `>= 3.12`
- Node.js `18` to `22` LTS
- PowerShell
- npm
- FastMCP or MCP-compatible runtime dependencies

Notes:

- The provided launch scripts are PowerShell-based
- Linux and macOS support may require adapting the startup scripts
- Custom multimodal services are expected to run as external persistent FastMCP SSE services

## Quick Start

### 1. Clone the repository

```powershell
git clone [https://github.com/kingsteve13091/mirror-mcp.git](https://github.com/kingsteve13091/mirror-mcp.git)
cd mirror-mcp
```

### 2. Create a Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If you use `uv`, you can also install from `pyproject.toml` and `uv.lock` with your preferred workflow.

### 3. Install frontend dependencies

```powershell
cd web_interface\frontend
npm install
cd ..\..
```

### 4. Configure environment variables

Create a `.env` file in the project root for any model or provider keys required by your deployment.

```env
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
SILICONFLOW_API_KEY=...
```

Do not commit secrets.

### 5. Validate configuration

```powershell
python .\scripts\validate_config.py
```

### 6. Start the backend

```powershell
.\scripts\start_backend.ps1
```

### 7. Start the frontend

Open a second terminal:

```powershell
.\scripts\start_frontend.ps1
```

Available endpoints:

- frontend: `http://localhost:3000`
- backend API docs: `http://localhost:8000/docs`

## Running External Custom Services

Custom multimodal reasoning services must run as external persistent FastMCP servers. They should not be imported directly into the backend process.

You can start them manually with:

```powershell
.\scripts\start_external_mcp_servers.ps1
```

Default endpoint:

- `http://127.0.0.1:9001/sse`

## Research Boundary

MCP Mirror intentionally separates the following concepts:

- `recipe`: learned procedural tool memory from successful real executions
- `guard`: learned counterfactual failure memory from repeated failures
- `skill`: explicit human-authored capability package
- `system prompt`: session-level instruction layer

These are not interchangeable. In particular:

- `recipe` is not a `skill`
- authored skills are not the main research contribution
- Memory Plane governance is not the same thing as generic prompt concatenation

## Current Scope

MCP Mirror is currently strongest as:

- a real MCP runtime orchestration system
- a memory-governed tool-use research platform
- a mechanism evaluation environment for routing, failure blocking, and auditable execution

It is not yet positioned as:

- a general-purpose autonomous agent benchmark winner
- a fully unconstrained planner for arbitrary open-world tool ecosystems

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/RECIPE_VS_SKILLS_COMPARISON.md`
- `docs/RESEARCH_PLAN.md`
- `docs/PAPER_MAINLINE_EXPERIMENT_MATRIX.md`

## Contributing

Contributions are welcome, especially in these areas:

- MCP runtime integration
- execution observability
- Memory Plane analysis and diagnostics
- Tool Execution Memory evaluation
- frontend runtime visualization
- safer harness policies and approval flows

If you plan to make architectural changes, please update the corresponding documentation in `docs/`.

## Citation

If you use MCP Mirror in academic work, please cite the corresponding paper or project page once the public citation record is finalized.

```bibtex
@software{mcp_mirror,
  title  = {MCP Mirror},
  author = {Cheong Yik Sheng},
  year   = {2026},
  url    = {[https://github.com/kingsteve13091/mirror-mcp](https://github.com/kingsteve13091/mirror-mcp)}
}
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
```
