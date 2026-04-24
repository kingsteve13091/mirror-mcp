# ✨ MCP Mirror

> **Memory-Governed MCP Orchestration for Tool-Using LLM Agents**

MCP Mirror is a **visual orchestration system** for building and studying  
**memory-aware, tool-using LLM agents** over long horizons.

It combines:

- ⚡ React + TypeScript frontend  
- 🧠 FastAPI backend  
- 🔌 Real MCP runtimes  
- 🧩 Explicit memory governance layer  

---

## 🚀 What Makes It Different

Most MCP clients:

> connect tools → call tools → show results  

**MCP Mirror instead asks:**

> How can agents use tools **stably, audibly, and learnably over time?**

### Core Ideas

- 🧠 **Memory Plane**  
  Governs routing, execution, and learning (not just prompts)

- 📘 **Recipe**  
  Procedural memory distilled from successful executions

- ⚠️ **Guard**  
  Failure memory that prevents repeated mistakes

👉 Together, they enable:

- memory-aware routing  
- failure prevention  
- bounded recovery  
- auditable execution replay  

---

## 🧩 System Architecture

```text
User → Intent → Memory Plane → Tool Routing → Harness → Runtime → Feedback → Memory
````

### Layers

1. **Frontend** — chat + visualization panels
2. **Backend** — orchestration & session control
3. **Memory Plane** — governance & routing
4. **Tool Memory** — recipe / guard
5. **Harness Runtime** — safe execution
6. **Real MCP Runtime** — actual tools

---

## 🔥 Key Features

* ✅ Real MCP runtime integration (official + external)
* 🔍 Dynamic tool discovery
* 🧠 Explicit Memory Plane (routing / rollback / attribution)
* 📘 Dual memory system:

  * `recipe` (success reuse)
  * `guard` (failure blocking)
* 🛡️ Execution harness:

  * validation
  * prechecks
  * recovery
* 📡 Structured event streaming
* 🧪 Research-ready evaluation environment
* 🖥️ Full visual observability (not a black box)

---

## 🖼️ Interface Overview

* 💬 Chat workspace
* 🧠 Memory Plane visualization
* 📘 Tool Execution Memory panel
* 🧰 MCP runtime center
* 🔁 Replay & approval system

---

## ⚡ Quick Start

### 1. Clone

```bash
git clone <your-repo-url>
cd mirror_mcp
```

### 2. Backend setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Frontend

```bash
cd web_interface/frontend
npm install
cd ../..
```

### 4. Environment

Create `.env`:

```env
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
SILICONFLOW_API_KEY=...
```

### 5. Run

```bash
.\scripts\start_backend.ps1
.\scripts\start_frontend.ps1
```

* Frontend: [http://localhost:3000](http://localhost:3000)
* Backend: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🔌 External MCP (CDAR)

Run separately:

```bash
.\scripts\start_external_mcp_servers.ps1
```

Default endpoint:

```
http://127.0.0.1:9001/sse
```

---

## 🧪 Research Positioning

MCP Mirror is designed as:

* ✅ Tool-use orchestration system
* ✅ Memory-governed agent research platform
* ✅ Execution audit & evaluation environment

Not intended (yet) as:

* ❌ fully autonomous general agent
* ❌ benchmark-optimized planner

---

## 🧠 Key Design Principle

> ❌ Do NOT trust model-declared tool calls
> ✅ Trust only real runtime execution events

---

## 📁 Project Structure

```text
mirror_mcp/
├─ web_interface/
│  ├─ backend/
│  └─ frontend/
├─ scripts/
├─ docs/
├─ experiments/
├─ datasets/
└─ mcp_config.json
```

---

## 📚 Documentation

* `docs/ARCHITECTURE.md`
* `docs/RESEARCH_PLAN.md`
* `docs/RECIPE_VS_SKILLS_COMPARISON.md`

---

## 🤝 Contributing

We welcome contributions in:

* MCP runtime integration
* Memory Plane design
* execution observability
* frontend visualization
* safety & governance

---

## 📖 Citation

```bibtex
@software{mcp_mirror,
  title  = {MCP Mirror},
  year   = {2026}
}
```

---

## 📜 License

⚠️ Not yet specified
(Add MIT / Apache-2.0 before open-source release)

```

---

如果你下一步想**再拉高一个档次（顶会级 GitHub 页面）**，我可以帮你加：

- :contentReference[oaicite:0]{index=0}
- :contentReference[oaicite:1]{index=1}
- :contentReference[oaicite:2]{index=2}

直接说一声你要“:contentReference[oaicite:3]{index=3}”，我给你做一个可以放论文里的版本。
```
