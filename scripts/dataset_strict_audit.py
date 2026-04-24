"""Strict local audit for external benchmark datasets.

The audit is intentionally conservative:
- It reports official/full dataset availability and scale.
- It does not label a dataset "directly adapted" unless the current live runner
  can execute its task format with current MCP tools.
- It separates memory-system relevance from MCP-tool execution compatibility.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "datasets" / "external"
OUT = EXT / "dataset_strict_audit.json"


def _repo_size(path: Path) -> tuple[int, int]:
    total = 0
    files = 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return files, total


def _git_head(path: Path) -> str:
    head = path / ".git" / "HEAD"
    if not head.exists():
        return ""
    txt = head.read_text(encoding="utf-8", errors="ignore").strip()
    if txt.startswith("ref: "):
        ref = path / ".git" / txt.split(" ", 1)[1]
        return ref.read_text(encoding="utf-8", errors="ignore").strip() if ref.exists() else txt
    return txt


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def _jsonl_count(path: Path) -> tuple[int, dict[str, Any] | None]:
    count = 0
    first: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            count += 1
            if first is None:
                try:
                    obj = json.loads(line)
                    first = obj if isinstance(obj, dict) else {"_non_dict": True}
                except Exception as exc:  # noqa: BLE001
                    first = {"_parse_error": str(exc)}
    return count, first


def _current_tools() -> tuple[set[tuple[str, str]], dict[str, set[str]]]:
    available_pairs: set[tuple[str, str]] = set()
    by_server: dict[str, set[str]] = defaultdict(set)
    try:
        r = requests.get("http://127.0.0.1:8000/api/mcp/servers", timeout=15)
        r.raise_for_status()
        servers = r.json()["servers"]["servers"]
        for server_info in servers:
            server = str(server_info.get("name", ""))
            for tool in server_info.get("tools", []):
                tool_name = str(tool)
                available_pairs.add((server, tool_name))
                by_server[server].add(tool_name)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN no backend tools: {exc}")
    return available_pairs, by_server


def audit_mcp_toolbench_pp(avail_pairs: set[tuple[str, str]]) -> dict[str, Any]:
    path = EXT / "mcp_toolbench_pp"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    data_dir = path / "data"
    category_summary: dict[str, dict[str, int]] = {}
    total_items = 0
    total_items_with_labels = 0
    direct_full_match = 0
    mcp_servers_seen: Counter[str] = Counter()
    tools_seen: Counter[str] = Counter()

    json_files = sorted(data_dir.glob("**/*.json"))
    for jf in json_files:
        try:
            obj = _read_json(jf)
        except Exception:
            continue
        if not isinstance(obj, list):
            continue
        n = len(obj)
        total_items += n
        local_with_labels = 0
        local_full_match = 0
        for ep in obj:
            labels = ep.get("function_call_label") if isinstance(ep, dict) else None
            if not isinstance(labels, list) or not labels:
                continue
            local_with_labels += 1
            total_items_with_labels += 1
            ok = True
            for st in labels:
                if not isinstance(st, dict):
                    ok = False
                    break
                server = str(st.get("mcp_server", "")).strip()
                tool = str(st.get("name", "")).strip()
                mcp_servers_seen[server] += 1
                tools_seen[f"{server}:{tool}"] += 1
                if (server, tool) not in avail_pairs:
                    ok = False
            if ok:
                local_full_match += 1
                direct_full_match += 1
        cat = jf.parent.name
        category_summary.setdefault(cat, {"files": 0, "items": 0, "with_labels": 0, "direct_full_match": 0})
        category_summary[cat]["files"] += 1
        category_summary[cat]["items"] += n
        category_summary[cat]["with_labels"] += local_with_labels
        category_summary[cat]["direct_full_match"] += local_full_match

    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "data_json_files": len(json_files),
        "total_items": total_items,
        "items_with_function_call_label": total_items_with_labels,
        "direct_full_match_items": direct_full_match,
        "direct_full_match_rate": round(direct_full_match / max(1, total_items_with_labels), 4),
        "category_summary": category_summary,
        "top_mcp_servers_seen": mcp_servers_seen.most_common(10),
        "top_tools_seen": tools_seen.most_common(15),
        "strict_verdict": "external tool benchmark, but only directly usable for current tools where full labels match live server/tool names",
    }


def audit_mcpbench() -> dict[str, Any]:
    path = EXT / "mcpbench"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    jsonl_files = sorted(path.glob("**/*.jsonl"))
    file_counts: dict[str, int] = {}
    sample_fields: dict[str, list[str]] = {}
    total_lines = 0
    for fp in jsonl_files:
        n, first = _jsonl_count(fp)
        rel = str(fp.relative_to(path))
        file_counts[rel] = n
        total_lines += n
        sample_fields[rel] = sorted(first.keys()) if isinstance(first, dict) else ["_non_dict"]
    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "jsonl_files": len(jsonl_files),
        "total_jsonl_items": total_lines,
        "jsonl_counts": file_counts,
        "sample_fields": sample_fields,
        "strict_verdict": "external prompt/answer benchmark; not a direct MCP episode format for current runner",
    }


def audit_mcpmark() -> dict[str, Any]:
    path = EXT / "mcpmark"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    meta_files = sorted((path / "tasks").glob("**/meta.json"))
    by_root: Counter[str] = Counter()
    sample_meta_keys: dict[str, list[str]] = {}
    for mf in meta_files:
        rel = mf.relative_to(path / "tasks")
        root_name = rel.parts[0] if rel.parts else "unknown"
        by_root[root_name] += 1
        if root_name not in sample_meta_keys:
            try:
                m = _read_json(mf)
                sample_meta_keys[root_name] = sorted(m.keys()) if isinstance(m, dict) else ["_non_dict"]
            except Exception:
                sample_meta_keys[root_name] = ["_parse_error"]
    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "meta_task_count": len(meta_files),
        "tasks_by_root": dict(by_root),
        "sample_meta_keys": sample_meta_keys,
        "strict_verdict": "external MCP task benchmark; filesystem branch is conceptually relevant but needs adapter/state/verifier integration",
    }


def audit_bfcl() -> dict[str, Any]:
    path = EXT / "bfcl"
    if not path.exists():
        return {"present": False}
    counts: dict[str, int] = {}
    sample_fields: dict[str, list[str]] = {}
    for fp in sorted(path.glob("BFCL_*.json")):
        count = 0
        first: dict[str, Any] | None = None
        with fp.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                count += 1
                if first is None:
                    try:
                        obj = json.loads(line)
                        first = obj if isinstance(obj, dict) else {"_non_dict": True}
                    except Exception as exc:  # noqa: BLE001
                        first = {"_parse_error": str(exc)}
        counts[fp.name] = count
        sample_fields[fp.name] = sorted(first.keys()) if isinstance(first, dict) else []
    return {
        "present": True,
        "files": len(counts),
        "line_counts": counts,
        "total_items": sum(counts.values()),
        "sample_fields": sample_fields,
        "strict_verdict": "authoritative function-calling benchmark; useful baseline, but not a direct tool-execution-memory episode benchmark",
    }


def audit_longmemeval() -> dict[str, Any]:
    path = EXT / "longmemeval"
    if not path.exists():
        return {"present": False}
    s_path = path / "longmemeval_s_cleaned.json"
    m_path = path / "longmemeval_m_cleaned.json"
    s = _read_json(s_path) if s_path.exists() else []
    first = s[0] if isinstance(s, list) and s else {}
    qtypes = Counter(str(x.get("question_type", "")) for x in s if isinstance(x, dict))
    return {
        "present": True,
        "s_count": len(s) if isinstance(s, list) else None,
        "s_fields": sorted(first.keys()) if isinstance(first, dict) else [],
        "s_question_types": dict(qtypes),
        "m_size_bytes": m_path.stat().st_size if m_path.exists() else None,
        "strict_verdict": "strong external long-memory QA benchmark; relevant as memory-regression benchmark, not direct TEM tool-trace benchmark",
    }


def audit_locomo() -> dict[str, Any]:
    path = EXT / "locomo"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    data_path = path / "data" / "locomo10.json"
    data = _read_json(data_path) if data_path.exists() else []
    first = data[0] if isinstance(data, list) and data else {}
    qa_count = 0
    qa_categories: Counter[str] = Counter()
    for sample in data if isinstance(data, list) else []:
        for qa in sample.get("qa", []) if isinstance(sample, dict) else []:
            qa_count += 1
            qa_categories[str(qa.get("category", ""))] += 1
    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "conversation_count": len(data) if isinstance(data, list) else None,
        "sample_fields": sorted(first.keys()) if isinstance(first, dict) else [],
        "qa_count": qa_count,
        "qa_categories": dict(qa_categories),
        "strict_verdict": "external very-long-term conversational memory benchmark; relevant for memory QA/temporal evidence, needs adapter to current memory MCP server",
    }


def audit_halumem() -> dict[str, Any]:
    path = EXT / "halumem"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    data_files = sorted((path / "data").glob("*.jsonl"))
    counts: dict[str, int] = {}
    sample_fields: dict[str, list[str]] = {}
    for fp in data_files:
        n, first = _jsonl_count(fp)
        counts[fp.name] = n
        sample_fields[fp.name] = sorted(first.keys()) if isinstance(first, dict) else []
    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "jsonl_files": len(data_files),
        "jsonl_counts": counts,
        "sample_fields": sample_fields,
        "strict_verdict": "best-fit external memory-system benchmark among downloaded candidates for extraction/update/QA; still requires TEM/MCP wrapper implementation",
    }


def audit_goodai_ltm() -> dict[str, Any]:
    path = EXT / "goodai_ltm_benchmark"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    dataset_py = sorted((path / "datasets").glob("*.py"))
    configs = sorted((path / "configurations" / "published_benchmarks").glob("*.yml"))
    test_defs = sorted((path / "data" / "tests").glob("**/definitions/*.json"))
    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "dataset_generators": [p.name for p in dataset_py],
        "published_configs": [p.name for p in configs],
        "test_definition_files": len(test_defs),
        "strict_verdict": "external long-term agent-memory benchmark; relevant to delayed recall/prospective memory, but not directly MCP tool-memory without model-interface adapter",
    }


def audit_tau_bench() -> dict[str, Any]:
    path = EXT / "tau_bench"
    if not path.exists():
        return {"present": False}
    files, total = _repo_size(path)
    return {
        "present": True,
        "repo_path": str(path),
        "git_head": _git_head(path),
        "repo_files": files,
        "repo_size_bytes": total,
        "strict_verdict": "external interactive tool-use benchmark; uses own environments/tools, not current memory MCP server directly",
    }


def audit_tem_toolbench_v2() -> dict[str, Any]:
    path = ROOT / "datasets" / "tem_toolbench_v2" / "tem_toolbench_v2.jsonl"
    meta_path = ROOT / "datasets" / "tem_toolbench_v2" / "tem_toolbench_v2_meta.json"
    if not path.exists():
        return {"present": False}
    total = 0
    categories: Counter[str] = Counter()
    difficulties: Counter[str] = Counter()
    success = 0
    failure = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            ep = json.loads(line)
            categories[str(ep.get("category", ""))] += 1
            difficulties[str(ep.get("difficulty", ""))] += 1
            if ep.get("expected_success"):
                success += 1
            else:
                failure += 1
    meta = _read_json(meta_path) if meta_path.exists() else {}
    return {
        "present": True,
        "total_items": total,
        "success_items": success,
        "failure_items": failure,
        "categories": dict(categories),
        "difficulty_distribution": dict(difficulties),
        "meta_version": meta.get("version") if isinstance(meta, dict) else None,
        "strict_verdict": "internal synthetic benchmark; directly adapted to current MCP runner, but not external publication evidence by itself",
    }


def main() -> None:
    avail_pairs, by_server = _current_tools()
    report: dict[str, Any] = {
        "current_live_tools": {server: sorted(tools) for server, tools in by_server.items()},
        "TEMToolBenchV2": audit_tem_toolbench_v2(),
        "MCPToolBenchPP": audit_mcp_toolbench_pp(avail_pairs),
        "MCPBench": audit_mcpbench(),
        "MCPMark": audit_mcpmark(),
        "BFCL": audit_bfcl(),
        "LongMemEval": audit_longmemeval(),
        "LoCoMo": audit_locomo(),
        "HaluMem": audit_halumem(),
        "GoodAI_LTM_Benchmark": audit_goodai_ltm(),
        "tau_bench": audit_tau_bench(),
        "strict_overall_conclusion": [
            "Only TEMToolBenchV2 is directly adapted to the current live MCP runner today.",
            "HaluMem is the strongest downloaded external match for memory-system operation evaluation, but needs a TEM/MCP wrapper before real comparison.",
            "LongMemEval and LoCoMo are useful memory-regression benchmarks, not tool-execution-memory benchmarks.",
            "MCPToolBenchPP/MCPMark/BFCL/tau-bench are valuable external baselines but require adapters or additional tools for fair direct comparison.",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
