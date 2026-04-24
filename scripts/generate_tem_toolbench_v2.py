from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from path_portability import MCP_MIRROR_ROOT_TOKEN, encode_portable_paths

OUT_DIR = ROOT / 'datasets' / 'tem_toolbench_v2'
OUT_ALL = OUT_DIR / 'tem_toolbench_v2.jsonl'
OUT_TRAIN = OUT_DIR / 'tem_toolbench_v2_train.jsonl'
OUT_DEV = OUT_DIR / 'tem_toolbench_v2_dev.jsonl'
OUT_TEST = OUT_DIR / 'tem_toolbench_v2_test.jsonl'
OUT_META = OUT_DIR / 'tem_toolbench_v2_meta.json'
SEED = 20260412
TOTAL = 2000
TRAIN = 1000
DEV = 400
TEST = 600
FS_STATE = OUT_DIR / 'fs_state'
LOCAL_FETCH_URL = 'http://127.0.0.1:8000/health'


def wjsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(encode_portable_paths(row, project_root=ROOT), ensure_ascii=False) + '\n')


def step(tool: str, server: str, arguments: dict[str, Any], ok: bool, err_t: str = '', err_m: str = '', expect: list[str] | None = None) -> dict[str, Any]:
    obj = {
        'tool': tool,
        'server': server,
        'arguments': arguments,
        'should_succeed': ok,
        'error_type': err_t,
        'error_message': err_m,
    }
    if expect:
        obj['expect_contains'] = expect
    return obj


def episode(eid: str, task: str, category: str, difficulty: str, tools: list[str], ok: bool, steps: list[dict[str, Any]], cause: str = '', focus: list[str] | None = None) -> dict[str, Any]:
    row = {
        'id': eid,
        'task': task,
        'category': category,
        'difficulty': difficulty,
        'tools_available': tools,
        'expected_success': ok,
        'steps': steps,
    }
    if cause:
        row['expected_failure_cause'] = cause
    if focus:
        row['memory_focus'] = focus
    return row


def ensure_fs() -> dict[str, str]:
    files = {
        'people': 'people/alice_profile.txt',
        'project': 'projects/tem_notes.md',
        'archive': 'archive/session_log.txt',
        'checklist': 'checklists/review_plan.txt',
    }
    contents = {
        'people': '\n'.join([
            'name: Alice Chen',
            'role: research engineer',
            'project: MCP Mirror',
            'favorite_memory_pattern: create_entities -> search_nodes -> open_nodes',
            'office: room-314',
        ]),
        'project': '\n'.join([
            '# TEM Notes',
            'priority: reduce repeated tool failure',
            'key metric: waste_call_rate',
            'status: active',
        ]),
        'archive': '\n'.join([
            '[session] recall prior failure traces',
            '[session] compare successful tool recipes',
            '[session] avoid fake benchmark claims',
        ]),
        'checklist': '\n'.join([
            '1. verify live MCP tool inventory',
            '2. reset stale guards',
            '3. run benchmark',
            '4. inspect false blocks',
        ]),
    }
    FS_STATE.mkdir(parents=True, exist_ok=True)
    for key, rel in files.items():
        path = FS_STATE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents[key], encoding='utf-8')
    img = FS_STATE / 'demo_image.png'
    if not img.exists():
        img.write_bytes(b'placeholder')
    return files


def abs_rel(rel: str) -> str:
    return str(FS_STATE / rel)


def ent(prefix: str, i: int, slot: int) -> str:
    return f'tem_v2_{prefix}_{i:04d}_entity_{slot}'


def fact(prefix: str, i: int, slot: int) -> str:
    return f'fact::{prefix}::{i:04d}::{slot}'


def build_memory_recall(i: int, success: bool) -> dict[str, Any]:
    if success:
        e = ent('memory_recall', i, 1)
        f = fact('memory_recall', i, 1)
        return episode(
            f'memory_recall_s_{i:04d}', f'Create and retrieve a memory entity {i}', 'memory_recall', 'easy',
            ['create_entities', 'search_nodes', 'open_nodes'], True,
            [
                step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'fact', 'observations': [f]}]}, True, expect=[e, f]),
                step('search_nodes', 'memory', {'query': f}, True, expect=[e, f]),
                step('open_nodes', 'memory', {'names': [e]}, True, expect=[e, f]),
            ], focus=['store', 'exact_recall']
        )
    return episode(
        f'memory_recall_f_{i:04d}', f'Trigger official memory create_entities validation failure {i}', 'memory_recall', 'easy',
        ['create_entities'], False,
        [step('create_entities', 'memory', {}, False, 'ValidationError', 'Invalid input: expected array, received undefined')],
        cause='ValidationError', focus=['schema_validation']
    )


def build_memory_distractor(i: int, success: bool) -> dict[str, Any]:
    if success:
        a = ent('memory_distractor', i, 1)
        b = ent('memory_distractor', i, 2)
        target = f'target-note::{i:04d}::critical finding'
        noise = f'distractor-note::{i:04d}::secondary detail'
        return episode(
            f'memory_distractor_s_{i:04d}', f'Retrieve target entity under distractor load {i}', 'memory_distractor_recall', 'medium',
            ['create_entities', 'search_nodes', 'open_nodes'], True,
            [
                step('create_entities', 'memory', {'entities': [
                    {'name': b, 'entityType': 'distractor', 'observations': [noise]},
                    {'name': a, 'entityType': 'target', 'observations': [target]},
                ]}, True, expect=[a, b]),
                step('search_nodes', 'memory', {'query': 'critical finding'}, True, expect=[a, target]),
                step('open_nodes', 'memory', {'names': [a]}, True, expect=[a, target]),
            ], focus=['distractor_resistance', 'retrieval_precision']
        )
    return episode(
        f'memory_distractor_f_{i:04d}', f'Trigger official memory search_nodes validation failure {i}', 'memory_distractor_recall', 'medium',
        ['search_nodes'], False,
        [step('search_nodes', 'memory', {}, False, 'ValidationError', 'Invalid input: expected string, received undefined')],
        cause='ValidationError', focus=['schema_validation']
    )


def build_memory_cross_tool(i: int, success: bool, files: dict[str, str]) -> dict[str, Any]:
    if success:
        project = abs_rel(files['project'])
        e = ent('memory_cross_tool', i, 1)
        case_token = f'cross-tool-case::{i:04d}'
        obs = f'{case_token}::filesystem-pointer::{project}'
        return episode(
            f'memory_cross_tool_s_{i:04d}', f'Store a filesystem pointer in memory and verify the file {i}', 'memory_cross_tool_verification', 'hard',
            ['create_entities', 'search_nodes', 'read_text_file'], True,
            [
                step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'file_ref', 'observations': [obs]}]}, True, expect=[e, project]),
                step('search_nodes', 'memory', {'query': case_token}, True, expect=[e, project]),
                step('read_text_file', 'filesystem', {'path': project}, True, expect=['TEM Notes', 'waste_call_rate']),
            ], focus=['cross_tool_linking', 'verification']
        )
    return episode(
        f'memory_cross_tool_f_{i:04d}', f'Attempt official filesystem access outside allowed root {i}', 'memory_cross_tool_verification', 'hard',
        ['read_text_file'], False,
        [step('read_text_file', 'filesystem', {'path': 'C:\\Windows\\System32\\drivers\\etc\\hosts'}, False, 'PermissionError', 'Access denied - path outside allowed directories')],
        cause='PermissionError', focus=['unsafe_action_blocking']
    )


def build_filesystem_probe(i: int, success: bool, files: dict[str, str]) -> dict[str, Any]:
    if success:
        archive = abs_rel(files['archive'])
        archive_dir = str((FS_STATE / 'archive').resolve())
        return episode(
            f'filesystem_probe_s_{i:04d}', f'Locate archived TEM trace using official filesystem tools {i}', 'filesystem_probe', 'medium',
            ['list_allowed_directories', 'search_files', 'read_text_file'], True,
            [
                step('list_allowed_directories', 'filesystem', {}, True, expect=[str(ROOT.resolve())]),
                # Official filesystem search_files searches the provided directory.
                # Use the target parent directory rather than assuming recursive search.
                step('search_files', 'filesystem', {'path': archive_dir, 'pattern': 'session_log.txt'}, True, expect=[archive]),
                step('read_text_file', 'filesystem', {'path': archive}, True, expect=['avoid fake benchmark claims', 'compare successful tool recipes']),
            ], focus=['externalized_trace_lookup']
        )
    missing = str((ROOT / f'definitely_missing_{i:04d}.txt').resolve())
    return episode(
        f'filesystem_probe_f_{i:04d}', f'Read a definitely missing official filesystem path {i}', 'filesystem_probe', 'medium',
        ['read_text_file'], False,
        [step('read_text_file', 'filesystem', {'path': missing}, False, 'FileNotFoundError', 'ENOENT: no such file or directory')],
        cause='FileNotFoundError', focus=['resource_not_found']
    )


def build_filesystem_writeback(i: int, success: bool) -> dict[str, Any]:
    out_abs = str((FS_STATE / 'generated' / f'case_{i:04d}.txt').resolve())
    out_dir = str((FS_STATE / 'generated').resolve())
    if success:
        content = '\n'.join([f'case: {i:04d}', 'note: writeback verification', 'metric: false_block_rate'])
        return episode(
            f'filesystem_writeback_s_{i:04d}', f'Write and verify official filesystem artifact {i}', 'filesystem_writeback', 'hard',
            ['create_directory', 'write_file', 'read_text_file', 'search_files'], True,
            [
                step('create_directory', 'filesystem', {'path': out_dir}, True),
                step('write_file', 'filesystem', {'path': out_abs, 'content': content}, True, expect=[out_abs]),
                step('read_text_file', 'filesystem', {'path': out_abs}, True, expect=['writeback verification', 'false_block_rate']),
                step('search_files', 'filesystem', {'path': out_dir, 'pattern': f'case_{i:04d}.txt'}, True, expect=[out_abs]),
            ], focus=['tool_effect_verification']
        )
    return episode(
        f'filesystem_writeback_f_{i:04d}', f'Trigger official write_file validation failure {i}', 'filesystem_writeback', 'hard',
        ['write_file'], False,
        [step('write_file', 'filesystem', {'path': out_abs}, False, 'ValidationError', 'Invalid input: expected string, received undefined')],
        cause='ValidationError', focus=['schema_validation']
    )


def build_plan_memory(i: int, success: bool) -> dict[str, Any]:
    if success:
        e = ent('plan_memory', i, 1)
        obs = f'plan::{i:04d}::verify_mcp_tool_health'
        return episode(
            f'plan_memory_s_{i:04d}', f'Generate a plan and store it in official memory {i}', 'plan_memory_loop', 'medium',
            ['sequentialthinking', 'create_entities', 'search_nodes'], True,
            [
                step('sequentialthinking', 'sequential_thinking', {'thought': f'Plan MCP health verification for case {i:04d}', 'nextThoughtNeeded': False, 'thoughtNumber': 1, 'totalThoughts': 1}, True, expect=['thoughtNumber', 'totalThoughts']),
                step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'plan', 'observations': [obs]}]}, True, expect=[e, obs]),
                step('search_nodes', 'memory', {'query': obs}, True, expect=[e, obs]),
            ], focus=['plan_preservation', 'reuse_ready_state']
        )
    return episode(
        f'plan_memory_f_{i:04d}', f'Trigger official sequentialthinking validation failure {i}', 'plan_memory_loop', 'medium',
        ['sequentialthinking'], False,
        [step('sequentialthinking', 'sequential_thinking', {}, False, 'ValidationError', 'Invalid input: expected string, received undefined')],
        cause='ValidationError', focus=['schema_validation']
    )


def build_plan_filesystem(i: int, success: bool, files: dict[str, str]) -> dict[str, Any]:
    if success:
        checklist = abs_rel(files['checklist'])
        checklist_dir = str((FS_STATE / 'checklists').resolve())
        return episode(
            f'plan_filesystem_s_{i:04d}', f'Plan then verify checklist evidence using official tools {i}', 'plan_filesystem_grounding', 'hard',
            ['sequentialthinking', 'read_text_file', 'search_files'], True,
            [
                step('sequentialthinking', 'sequential_thinking', {'thought': f'Verify benchmark checklist for case {i:04d}', 'nextThoughtNeeded': False, 'thoughtNumber': 1, 'totalThoughts': 1}, True, expect=['thoughtNumber', 'totalThoughts']),
                step('read_text_file', 'filesystem', {'path': checklist}, True, expect=['run benchmark', 'inspect false blocks']),
                # Official filesystem search_files does not recurse across all
                # fixture subdirectories in the current runtime.
                step('search_files', 'filesystem', {'path': checklist_dir, 'pattern': 'review_plan.txt'}, True, expect=[checklist]),
            ], focus=['grounded_plan_execution']
        )
    return episode(
        f'plan_filesystem_f_{i:04d}', f'Trigger official search_files validation failure {i}', 'plan_filesystem_grounding', 'hard',
        ['search_files'], False,
        [step('search_files', 'filesystem', {'path': str(FS_STATE.resolve())}, False, 'ValidationError', 'Invalid input: expected string, received undefined')],
        cause='ValidationError', focus=['schema_validation']
    )


def build_fetch_memory(i: int, success: bool) -> dict[str, Any]:
    if success:
        e = ent('fetch_memory', i, 1)
        case_token = f'fetch-health-case::{i:04d}'
        obs = f'{case_token}::url::{LOCAL_FETCH_URL}'
        return episode(
            f'fetch_memory_s_{i:04d}', f'Fetch a web page and bridge result into official memory {i}', 'fetch_memory_bridge', 'hard',
            ['fetch', 'create_entities', 'search_nodes'], True,
            [
                step('fetch', 'fetch', {'url': LOCAL_FETCH_URL, 'max_length': 1000}, True, expect=['"status":"healthy"', '"mcp_manager":"available"']),
                step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'url_fact', 'observations': [obs]}]}, True, expect=[e, obs]),
                step('search_nodes', 'memory', {'query': case_token}, True, expect=[e, obs]),
            ], focus=['cross_tool_bridge']
        )
    return episode(
        f'fetch_memory_f_{i:04d}', f'Trigger official fetch URL validation failure {i}', 'fetch_memory_bridge', 'hard',
        ['fetch'], False,
        [step('fetch', 'fetch', {'url': 'not-a-url'}, False, 'ValidationError', 'Input should be a valid URL')],
        cause='ValidationError', focus=['external_failure_capture']
    )


def build_memory_chain(i: int, success: bool, files: dict[str, str]) -> dict[str, Any]:
    if success:
        people = abs_rel(files['people'])
        project = abs_rel(files['project'])
        a = ent('memory_chain', i, 1)
        b = ent('memory_chain', i, 2)
        person_obs = f'person-case::{i:04d}::Alice Chen::{people}'
        project_obs = f'project-case::{i:04d}::TEM Notes::{project}'
        return episode(
            f'memory_chain_s_{i:04d}', f'Store two linked pointers and verify both through official tools {i}', 'memory_chain_grounding', 'hard',
            ['create_entities', 'search_nodes', 'read_text_file'], True,
            [
                step('create_entities', 'memory', {'entities': [
                    {'name': a, 'entityType': 'file_ref', 'observations': [person_obs]},
                    {'name': b, 'entityType': 'file_ref', 'observations': [project_obs]},
                ]}, True, expect=[a, b, people, project]),
                step('search_nodes', 'memory', {'query': f'person-case::{i:04d}'}, True, expect=[a, people]),
                step('read_text_file', 'filesystem', {'path': people}, True, expect=['Alice Chen', 'research engineer']),
                step('read_text_file', 'filesystem', {'path': project}, True, expect=['TEM Notes', 'waste_call_rate']),
            ], focus=['cross_tool_linking', 'verification', 'externalized_trace_lookup']
        )
    missing = str((FS_STATE / 'generated' / f'not_created_{i:04d}.txt').resolve())
    e = ent('memory_chain_fail', i, 1)
    stale_obs = f'stale-case::{i:04d}::path::{missing}'
    return episode(
        f'memory_chain_f_{i:04d}', f'Store stale pointer then fail on grounded file read {i}', 'memory_chain_grounding', 'hard',
        ['create_entities', 'search_nodes', 'read_text_file'], False,
        [
            step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'file_ref', 'observations': [stale_obs]}]}, True, expect=[e, missing]),
            step('search_nodes', 'memory', {'query': f'stale-case::{i:04d}'}, True, expect=[e, missing]),
            step('read_text_file', 'filesystem', {'path': missing}, False, 'FileNotFoundError', 'ENOENT: no such file or directory'),
        ], cause='FileNotFoundError', focus=['resource_not_found', 'cross_tool_verification']
    )


def build_plan_memory_fs(i: int, success: bool, files: dict[str, str]) -> dict[str, Any]:
    if success:
        checklist = abs_rel(files['checklist'])
        out_abs = str((FS_STATE / 'generated' / f'plan_loop_{i:04d}.txt').resolve())
        out_dir = str((FS_STATE / 'generated').resolve())
        e = ent('plan_memory_filesystem', i, 1)
        case_token = f'artifact-case::{i:04d}'
        obs = f'{case_token}::{out_abs}'
        content = '\n'.join([f'case: {i:04d}', 'loop: plan-memory-filesystem', 'signal: reuse-ready-state'])
        return episode(
            f'plan_memory_fs_s_{i:04d}', f'Plan, persist, write artifact and verify links {i}', 'plan_memory_filesystem_loop', 'hard',
            ['sequentialthinking', 'read_text_file', 'create_entities', 'search_nodes', 'create_directory', 'write_file', 'search_files'], True,
            [
                step('sequentialthinking', 'sequential_thinking', {'thought': f'Plan memory/filesystem verification loop for case {i:04d}', 'nextThoughtNeeded': False, 'thoughtNumber': 1, 'totalThoughts': 1}, True, expect=['thoughtNumber', 'totalThoughts']),
                step('read_text_file', 'filesystem', {'path': checklist}, True, expect=['run benchmark', 'inspect false blocks']),
                step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'artifact', 'observations': [obs]}]}, True, expect=[e, out_abs]),
                step('create_directory', 'filesystem', {'path': out_dir}, True),
                step('write_file', 'filesystem', {'path': out_abs, 'content': content}, True, expect=[out_abs]),
                step('search_nodes', 'memory', {'query': case_token}, True, expect=[e, out_abs]),
                step('search_files', 'filesystem', {'path': out_dir, 'pattern': f'plan_loop_{i:04d}.txt'}, True, expect=[out_abs]),
            ], focus=['plan_preservation', 'reuse_ready_state', 'tool_effect_verification']
        )
    return episode(
        f'plan_memory_fs_f_{i:04d}', f'Plan then fail on unsafe official write target {i}', 'plan_memory_filesystem_loop', 'hard',
        ['sequentialthinking', 'write_file'], False,
        [
            step('sequentialthinking', 'sequential_thinking', {'thought': 'Write a file outside the allowed project root', 'nextThoughtNeeded': False, 'thoughtNumber': 1, 'totalThoughts': 1}, True, expect=['thoughtNumber', 'totalThoughts']),
            step('write_file', 'filesystem', {'path': 'C:\\Windows\\Temp\\plan_loop.txt', 'content': 'unsafe'}, False, 'PermissionError', 'Access denied - path outside allowed directories'),
        ], cause='PermissionError', focus=['unsafe_action_blocking', 'plan_preservation']
    )


def build_memory_graph_audit(i: int, success: bool) -> dict[str, Any]:
    if success:
        e = ent('memory_graph_audit', i, 1)
        obs = f'audit-signal::{i:04d}'
        return episode(
            f'memory_graph_audit_s_{i:04d}', f'Store memory then audit official graph state {i}', 'memory_graph_audit', 'medium',
            ['create_entities', 'read_graph', 'search_nodes'], True,
            [
                step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'audit', 'observations': [obs]}]}, True, expect=[e, obs]),
                step('read_graph', 'memory', {}, True, expect=['entities', e]),
                step('search_nodes', 'memory', {'query': obs}, True, expect=[e, obs]),
            ], focus=['store', 'verification', 'state_recording']
        )
    e = ent('memory_graph_audit_fail', i, 1)
    return episode(
        f'memory_graph_audit_f_{i:04d}', f'Store memory then fail on missing official search_nodes query {i}', 'memory_graph_audit', 'medium',
        ['create_entities', 'read_graph', 'search_nodes'], False,
        [
            step('create_entities', 'memory', {'entities': [{'name': e, 'entityType': 'audit', 'observations': [f'audit-fail::{i:04d}']}]}, True, expect=[f'audit-fail::{i:04d}']),
            step('read_graph', 'memory', {}, True, expect=['entities']),
            step('search_nodes', 'memory', {}, False, 'ValidationError', 'Invalid input: expected string, received undefined'),
        ], cause='ValidationError', focus=['schema_validation', 'verification']
    )


def build_cdar(i: int, success: bool) -> dict[str, Any]:
    if success:
        img = str(FS_STATE / 'demo_image.png')
        return episode(
            f'cdar_guard_s_{i:04d}', f'CDAR minimal valid-schema call shape {i}', 'cdar_guarding', 'hard',
            ['cdar_compositional_decomposed_adaptive_reasoning'], True,
            [step('cdar_compositional_decomposed_adaptive_reasoning', 'cdar_mcp', {'image_path': img, 'question': f'Describe sample {i:04d}'}, True)],
            focus=['tool_schema_coverage']
        )
    return episode(
        f'cdar_guard_f_{i:04d}', f'Trigger CDAR schema failure by omitting image_path {i}', 'cdar_guarding', 'hard',
        ['cdar_compositional_decomposed_adaptive_reasoning'], False,
        [step('cdar_compositional_decomposed_adaptive_reasoning', 'cdar_mcp', {'question': f'Describe sample {i:04d}'}, False, 'ValidationError', 'Missing required argument')],
        cause='ValidationError', focus=['schema_validation']
    )


def build() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    files = ensure_fs()
    specs = [
        (220, lambda i: build_memory_recall(i, True)), (80, lambda i: build_memory_recall(i, False)),
        (180, lambda i: build_memory_distractor(i, True)), (60, lambda i: build_memory_distractor(i, False)),
        (170, lambda i: build_memory_cross_tool(i, True, files)), (60, lambda i: build_memory_cross_tool(i, False, files)),
        (120, lambda i: build_filesystem_probe(i, True, files)), (50, lambda i: build_filesystem_probe(i, False, files)),
        (120, lambda i: build_filesystem_writeback(i, True)), (40, lambda i: build_filesystem_writeback(i, False)),
        (130, lambda i: build_plan_memory(i, True)), (50, lambda i: build_plan_memory(i, False)),
        (90, lambda i: build_plan_filesystem(i, True, files)), (30, lambda i: build_plan_filesystem(i, False, files)),
        (55, lambda i: build_fetch_memory(i, True)), (25, lambda i: build_fetch_memory(i, False)),
        (120, lambda i: build_memory_chain(i, True, files)), (50, lambda i: build_memory_chain(i, False, files)),
        (140, lambda i: build_plan_memory_fs(i, True, files)), (50, lambda i: build_plan_memory_fs(i, False, files)),
        (100, lambda i: build_memory_graph_audit(i, True)), (40, lambda i: build_memory_graph_audit(i, False)),
        (10, lambda i: build_cdar(i, True)), (10, lambda i: build_cdar(i, False)),
    ]
    rows: list[dict[str, Any]] = []
    for count, fn in specs:
        for i in range(1, count + 1):
            rows.append(fn(i))
    if len(rows) != TOTAL:
        raise RuntimeError(f'Expected {TOTAL} rows, got {len(rows)}')
    rng.shuffle(rows)
    return rows


def write(rows: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    train = rows[:TRAIN]
    dev = rows[TRAIN:TRAIN+DEV]
    test = rows[TRAIN+DEV:]
    wjsonl(OUT_ALL, rows)
    wjsonl(OUT_TRAIN, train)
    wjsonl(OUT_DEV, dev)
    wjsonl(OUT_TEST, test)
    cat = defaultdict(lambda: {'total': 0, 'success': 0, 'failure': 0})
    diff = Counter()
    focus = Counter()
    tools = Counter()
    causes = Counter()
    for ep in rows:
        c = ep['category']
        cat[c]['total'] += 1
        if ep['expected_success']:
            cat[c]['success'] += 1
        else:
            cat[c]['failure'] += 1
            causes[ep.get('expected_failure_cause', 'unknown')] += 1
        diff[ep['difficulty']] += 1
        for f in ep.get('memory_focus', []):
            focus[f] += 1
        for t in ep.get('tools_available', []):
            tools[t] += 1
    meta = {
        'name': 'TEM-ToolBench-v2',
        'version': '2.6-official-mcp-strict-portable-paths',
        'path_portability': {
            'root_token': MCP_MIRROR_ROOT_TOKEN,
            'runtime_resolution': 'Dataset paths under the repository root are stored with a portable root token and expanded at tool-call time.',
            'intentional_external_negative_paths': [
                'C:\\Windows\\System32\\drivers\\etc\\hosts',
                'C:\\Windows\\Temp\\plan_loop.txt',
            ],
        },
        'seed': SEED,
        'total_episodes': len(rows),
        'splits': {'train': len(train), 'dev': len(dev), 'test': len(test)},
        'max_steps_required': max((len(ep.get('steps', [])) for ep in rows), default=0),
        'schema_type': 'official_mcp_servers',
        'categories': dict(cat),
        'difficulty_distribution': dict(diff),
        'memory_focus_distribution': dict(focus),
        'tool_coverage': dict(tools),
        'failure_cause_distribution': dict(causes),
        'official_runtime_tools': {
            'filesystem': ['read_text_file', 'write_file', 'search_files', 'list_allowed_directories', 'create_directory'],
            'fetch': ['fetch'],
            'memory': ['create_entities', 'add_observations', 'search_nodes', 'open_nodes', 'read_graph', 'delete_entities'],
            'sequential_thinking': ['sequentialthinking'],
            'cdar_mcp': ['cdar_compositional_decomposed_adaptive_reasoning'],
        },
        'verified_live_failure_patterns': [
            'create_entities missing entities -> Invalid input: expected array, received undefined',
            'search_nodes missing query -> Invalid input: expected string, received undefined',
            'search_files missing pattern -> Invalid input: expected string, received undefined',
            'write_file missing content -> Invalid input: expected string, received undefined',
            'sequentialthinking missing required fields -> Invalid input: expected string/boolean/number',
            'fetch invalid URL -> Input should be a valid URL',
            'read_text_file missing file -> ENOENT: no such file or directory',
            'read_text_file outside allowed root -> Access denied - path outside allowed directories',
            'cdar missing image_path -> Missing required argument',
        ],
        'notes': [
            'This is the canonical internal benchmark for the current official MCP runtime.',
            'This repository keeps only the official MCP-schema mainline benchmark artifacts.',
            'Official memory server is a knowledge graph API, so memory episodes use create_entities/search_nodes/open_nodes/read_graph.',
            'Official fetch server exposes fetch only; old head_url/fetch_url wrapper tools are legacy-only.',
            'Official sequential thinking server exposes sequentialthinking only; old think_stepwise/evaluate_plan are legacy-only.',
            'Filesystem search_files cases are aligned to the current official server semantics and search within the specified directory.',
            'Fetch success cases use the local MCP Mirror backend health endpoint to avoid external-network instability.',
            'Successful memory search cases query tokens that are explicitly written into the official memory graph earlier in the same episode.',
        ],
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    rows = build()
    write(rows)
    print(json.dumps({'dataset': str(OUT_ALL), 'meta': str(OUT_META), 'episodes': len(rows)}, ensure_ascii=False))
