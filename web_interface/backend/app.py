#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MCP Chat Interface with SiliconFlow - 完全修复版本
支持真实的MCP工具调用和前后端完整连接
"""

import asyncio
import copy
from contextlib import asynccontextmanager
import io
import json
import logging
import os
import random
import re
import shutil
import sys
import time
import threading
import traceback
from collections import OrderedDict
import hashlib

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.websockets import WebSocketState
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


# 设置日志（控制台人类可读 + JSON 文件可查询）
_stdout_for_logging = sys.stdout
if hasattr(sys.stdout, "buffer"):
    try:
        _stdout_for_logging = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            write_through=True,
        )
    except Exception:
        _stdout_for_logging = sys.stdout

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(_stdout_for_logging),
        logging.FileHandler('mcp_chat.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)
INVISIBLE_TEXT_CHARS = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060"), None)

from structured_logger import setup_structured_logging, ExecutionTrace
slog = setup_structured_logging("mcp_mirror")

from context_engine import (
    context_engine,
    extract_attachment_content,
    reload_context_engine_parameters,
    build_workspace_context_block,
    load_workspace_agent_runtime_profile,
    load_workspace_agent_commands,
    load_workspace_agent_command,
    render_workspace_agent_command_context,
)
from workspace_mcp_pool import workspace_mcp_pool, safe_workspace_root
from tool_execution_memory import tem, reload_tem_parameters, infer_relevant_tool_names
from memory_control_plane import (
    memory_control_plane,
    reload_memory_plane_parameters,
    reset_memory_plane_runtime,
)
from parameter_learner import parameter_learner
from model_registry import (
    DEFAULT_MODEL_ID,
    OPENROUTER_DEFAULT_MODEL_ID,
    build_available_models,
)
from controlled_argument_policy import (
    build_initial_argument_state,
    generate_controlled_arguments,
    generate_memory_conditioned_arguments,
    normalize_argument_policy_mode,
    update_argument_state,
)
from mcp_config_store import (
    MCPConfigError,
    MCPServerConfigRequest,
    delete_mcp_server_config,
    list_mcp_server_configs,
    read_mcp_config,
    upsert_mcp_server_config,
)
from agent_skills import agent_skills_registry
from skill_runtime import SkillRuntimeResolver
from mcp_onboarding_service import MCPToolOnboardingService
from runtime_config_service import RuntimeConfigService
from request_runtime_service import RequestRuntimeService
from operation_audit import OperationAuditLog
from system_operation_policy import evaluate_system_operation_policy
from system_operation_harness import SystemOperationHarness
from resource_reference import build_resource_references
from agent_planner import build_agent_plan
from task_runtime import AgentTaskRuntime
from agent_task_executor import AgentTaskExecutor
from agent_run_scheduler import AgentRunScheduler
from harness_execution_engine import MCPHarnessExecutionEngine
from tool_autoroute_policy import (
    AUTO_TOOL_MIN_SCORE,
    arguments_ready_for_auto_execution,
    filter_auto_tool_candidates,
    is_auto_tool_allowed,
    tool_key,
)

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from mcp_server_contract import build_runtime_audit_report
from experiments.live_result_verifier import verify_step_response
if load_dotenv is not None:
    load_dotenv(project_root / ".env", override=False)
    load_dotenv(Path(__file__).with_name("config.env"), override=False)

# 导入增强MCP管理器
from enhanced_mcp_manager import enhanced_mcp_manager

# 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        previous = self.active_connections.get(client_id)
        self.active_connections[client_id] = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=1000)
            except Exception:
                pass
        logger.debug(f"client connected: {client_id}")

    def disconnect(self, client_id: str, websocket: Optional[WebSocket] = None):
        current = self.active_connections.get(client_id)
        if current is None:
            return
        if websocket is not None and current is not websocket:
            return
        del self.active_connections[client_id]
        logger.debug(f"client disconnected: {client_id}")

    def is_current_connection(self, client_id: str, websocket: WebSocket) -> bool:
        return self.active_connections.get(client_id) is websocket

    def is_active_connection(self, websocket: WebSocket) -> bool:
        return (
            websocket.client_state == WebSocketState.CONNECTED
            and websocket.application_state == WebSocketState.CONNECTED
        )

    async def send_to_websocket(self, websocket: WebSocket, message: dict) -> None:
        if not self.is_active_connection(websocket):
            raise RuntimeError("WebSocket is not connected")
        await websocket.send_text(json.dumps(message, ensure_ascii=False))

    async def send_personal_message(self, message: dict, client_id: str):
        websocket = self.active_connections.get(client_id)
        if websocket is not None:
            try:
                await self.send_to_websocket(websocket, message)
            except Exception as e:
                if self.active_connections.get(client_id) is not websocket:
                    logger.debug(f"skip send to stale websocket: {client_id}")
                    return
                if not self.is_active_connection(websocket):
                    logger.debug(f"drop send to closed websocket: {client_id}")
                else:
                    logger.warning(f"failed to send message to {client_id}: {e}")
                self.disconnect(client_id, websocket)

# 全局变量
manager = ConnectionManager()
siliconflow_api_key = None
siliconflow_base_url = None
openrouter_api_key = None
openrouter_base_url = None
available_models = []
shared_http_client: Optional[httpx.AsyncClient] = None
mcp_manager = enhanced_mcp_manager  # shared MCP manager instance
REQUEST_CACHE_MAX_SIZE = 500
REQUEST_JOURNAL_PATH = project_root / "artifacts" / "memory" / "request_runtime_journal.json"
REQUEST_JOURNAL_VERSION = 1
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
REGRESSION_SANDBOX_ROOT = project_root / "tmp" / "regression_sandbox"
regression_sandbox_lock = threading.RLock()
regression_sandbox_sessions: Dict[str, dict[str, Any]] = {}

# runtime defaults
DEFAULT_CHAT_TEMPERATURE = 0.7
DEFAULT_CHAT_MAX_TOKENS = 2000
DEFAULT_WS_CHAT_MAX_TOKENS = 2048
API_TIMEOUT_SECONDS = 60.0
TOOL_FOLLOWUP_API_TIMEOUT_SECONDS = 25.0
TOOL_FOLLOWUP_MAX_TOKENS = 600
TOOL_FOLLOWUP_RESULT_MAX_CHARS = 2400
MODEL_TOOL_CALL_MAX_STEPS = 4
MODEL_TOOL_CALL_MAX_PER_STEP = 6
MODEL_TOOL_MAX_VISIBLE_TOOLS = 80
DEFAULT_SERVER_PORT = 8000
FALLBACK_SERVER_PORT = 8001
SILICONFLOW_BASE_URL_DEFAULT = "https://api.siliconflow.cn/v1"
SILICONFLOW_GLOBAL_BASE_URL = "https://api.siliconflow.com/v1"
OPENROUTER_BASE_URL_DEFAULT = "https://openrouter.ai/api/v1"
OPENROUTER_MAX_RETRIES = 3
OPENROUTER_RETRY_BASE_SECONDS = 1.2
OPENROUTER_RETRY_MAX_SECONDS = 6.0
PATH_ARGUMENT_NAMES = {
    "path",
    "file",
    "file_path",
    "filepath",
    "filename",
    "source",
    "source_path",
    "input",
    "uri",
    "url",
}
IMAGE_ARGUMENT_NAMES = {
    "image",
    "image_path",
    "image_file",
    "image_filepath",
    "image_url",
    "photo",
    "photo_path",
    "screenshot",
    "screenshot_path",
}
TASK_TEXT_ARGUMENT_NAMES = {
    "question",
    "query",
    "prompt",
    "instruction",
    "task",
    "request",
    "user_request",
}
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
WEB_SEARCH_ENDPOINT = "https://duckduckgo.com/html/?q={query}"
WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[^\s\"'<>]+")
UNIX_PATH_PATTERN = re.compile(r"(?:\.{1,2}/|/)[^\s\"'<>]+")
AT_PATH_PATTERN = re.compile(
    r"@((?:\.{1,2}[\\/]|[A-Za-z]:\\|/)[^\s\"'`<>]+|(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,16})"
)
RELATIVE_FILE_PATTERN = re.compile(r"(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,16}")
QUOTED_PATH_PATTERN = re.compile(r"[\"'`]([^\"'`]*(?:\\|/)[^\"'`]*)[\"'`]")
AUTO_TOOL_ATTACHMENT_REFERENCE_HINTS = {
    "attachment",
    "attached",
    "upload",
    "uploaded",
    "file",
    "document",
    "pdf",
    "csv",
    "json",
    "txt",
    "log",
    "resume",
    "附件",
    "上传",
    "文件",
    "文档",
    "材料",
    "简历",
    "表格",
    "文本",
    "内容",
}
AUTO_TOOL_ATTACHMENT_ACTION_HINTS = {
    "read",
    "open",
    "inspect",
    "check",
    "review",
    "summarize",
    "summary",
    "extract",
    "analyze",
    "analyse",
    "parse",
    "find",
    "locate",
    "quote",
    "tell me",
    "look at",
    "what is in",
    "what's in",
    "阅读",
    "读取",
    "打开",
    "查看",
    "检查",
    "总结",
    "概括",
    "提取",
    "分析",
    "解析",
    "查找",
    "定位",
    "看看",
    "告诉我",
    "说了什么",
}
AUTO_TOOL_CONTEXTUAL_REFERENCE_HINTS = {
    "this file",
    "the file",
    "this attachment",
    "the attachment",
    "the uploaded file",
    "this document",
    "the document",
    "里面",
    "其中",
    "这份",
    "该文件",
    "这个文件",
    "这个附件",
    "这份文档",
}
AUTO_TOOL_IMAGE_ACTION_HINTS = {
    "describe",
    "caption",
    "analyze",
    "analyse",
    "inspect",
    "recognize",
    "identify",
    "what is in",
    "what's in",
    "look at",
    "read the image",
    "ocr",
    "分析",
    "看图",
    "看看图",
    "识别",
    "描述",
    "说明",
    "图片",
    "图像",
    "照片",
    "截图",
    "这张图",
    "这张图片",
    "图里",
    "图中",
}
FABRICATED_TOOL_CALL_PATTERNS = [
    re.compile(r"\b(?:i will|i'll|let me|i am going to|i'm going to)\s+(?:call|use|invoke|run)\b", re.IGNORECASE),
    re.compile(r"\b(?:call|use|invoke|run)\s+`?[a-zA-Z0-9_.-]+`?\s+tool\b", re.IGNORECASE),
    re.compile(r"(?:我将|我要|我会|接下来将|现在|接下来|首先.*?需要)\s*(?:调用|使用|运行)\s*`?[^`\n]{1,80}`?\s*工具"),
    re.compile(r"(?:调用|使用|运行)\s*`?[^`\n]{1,80}`?\s*工具\s*(?:来|以便|进行|完成)"),
    re.compile(r"\b(?:read_file|read_text_file|read_multiple_files|fetch|sequentialthinking|cdar[_a-zA-Z0-9]*)\s*\(", re.IGNORECASE),
]

# request models
class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = DEFAULT_MODEL_ID
    temperature: float = DEFAULT_CHAT_TEMPERATURE
    max_tokens: int = DEFAULT_CHAT_MAX_TOKENS
    stream: bool = False
    skill_ids: List[str] = []
    custom_system_prompt: str = ""
    attachments: List[Dict[str, Any]] = []
    attachment_plan: Dict[str, Any] = {}
    workspace_context: Dict[str, Any] = {}
    web_search_enabled: bool = False

class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    server_name: Optional[str] = None
    content: Optional[str] = None
    model_id: Optional[str] = None
    policy_confirmed: bool = False
    attachments: List[Dict[str, Any]] = []
    attachment_plan: Dict[str, Any] = {}
    skill_ids: List[str] = []
    custom_system_prompt: str = ""
    workspace_context: Dict[str, Any] = {}


class ToolPolicyUpdateRequest(BaseModel):
    enabled: bool = True
    default_action: str = "allow"
    tool_actions: Dict[str, str] = {}
    server_actions: Dict[str, str] = {}
    system_actions: Dict[str, str] = {}
    deny_risky_write_paths: bool = True


class AutoToolRoutingUpdateRequest(BaseModel):
    mode: str = "memory_plane_plus_fallback"


class MemoryPlaneRuntimeUpdateRequest(BaseModel):
    absorb_system_op_audit: bool = True


class AgentSkillsExternalConfigRequest(BaseModel):
    external_skill_dirs: List[str] = []


class AgentTaskCreateRequest(BaseModel):
    goal: str
    client_id: str = ""
    workspace_root: str = ""
    attachments: List[Dict[str, Any]] = []
    skill_ids: List[str] = []
    mode: str = "agent"
    run_kind: str = "interactive_chat"
    scheduled_for: str = ""
    parent_run_id: str = ""
    scheduler_id: str = ""


class AgentTaskApprovalDecisionRequest(BaseModel):
    client_id: str = ""
    workspace_root: str = ""
    attachments: List[Dict[str, Any]] = []
    note: str = ""


class SystemOperationRequest(BaseModel):
    action_type: str
    payload: Dict[str, Any] = {}
    client_id: str = ""
    task_id: str = ""
    workspace_root: str = ""
    policy_confirmed: bool = False


class ToolOnboardingSelfTestRequest(BaseModel):
    tool_keys: List[str] = []
    execute_safe_only: bool = True
    max_tools: int = 50
    workspace_root: str = ""


class WorkspaceContextPreviewRequest(BaseModel):
    workspace_root: str = ""
    agent_name: str = ""
    include_agent_profile: bool = True
    include_memory_file: bool = True
    include_chatlogs: bool = False
    workspace_agent_command: Optional[str] = None


class PolicyEvaluationRequest(BaseModel):
    query: str
    client_id: Optional[str] = None
    candidate_tools: List[str] = []
    expected_tool: Optional[str] = None
    dry_run: bool = True
    feature_mask: Dict[str, bool] = {}


class PolicyEvaluationBatchCase(BaseModel):
    id: Optional[str] = None
    query: str
    expected_tool: Optional[str] = None
    candidate_tools: List[str] = []
    client_id: Optional[str] = None


class PolicyEvaluationBatchRequest(BaseModel):
    cases: List[PolicyEvaluationBatchCase]
    dry_run: bool = True
    feature_mask: Dict[str, bool] = {}


class AutonomousTrajectoryStep(BaseModel):
    tool: str
    server: str = ""
    arguments: Dict[str, Any] = {}
    should_succeed: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    expect_contains: List[str] = []
    expect_not_contains: List[str] = []


class AutonomousTrajectoryCase(BaseModel):
    id: Optional[str] = None
    task: str
    category: Optional[str] = None
    difficulty: Optional[str] = None
    expected_success: bool = True
    candidate_tools: List[str] = []
    tools_available: List[str] = []
    memory_focus: List[str] = []
    steps: List[AutonomousTrajectoryStep]
    client_id: Optional[str] = None


class AutonomousTrajectoryRequest(BaseModel):
    cases: List[AutonomousTrajectoryCase]
    tem_mode: str = "full_tem"
    reset_tem_before_run: bool = False
    max_steps_per_case: int = 12
    execute_selected_tool: bool = True
    teacher_force_tools: bool = False
    argument_policy_mode: str = "gold"
    stop_on_misroute: bool = False
    stop_on_failure: bool = False
    restore_state_after_run: bool = True
    feature_mask: Dict[str, bool] = {}


class ShadowReplayBatchRequest(BaseModel):
    cases: List[PolicyEvaluationBatchCase]
    dry_run: bool = True
    feature_mask: Dict[str, bool] = {}


class GuardTradeoffStep(BaseModel):
    tool: str
    server: str
    arguments: Dict[str, Any] = {}
    should_succeed: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    role: Optional[str] = None


class GuardTradeoffCase(BaseModel):
    id: Optional[str] = None
    task: str
    expected_success: bool
    category: Optional[str] = None
    steps: List[GuardTradeoffStep]


class GuardTradeoffRequest(BaseModel):
    warmup_cases: List[GuardTradeoffCase] = []
    evaluation_cases: List[GuardTradeoffCase]
    tem_mode: str = "full_tem"
    reset_tem_before_run: bool = True
    clear_external_memory: bool = False
    restore_state_after_run: bool = True


class RecoveryUtilityRequest(BaseModel):
    cases: List[PolicyEvaluationBatchCase]
    restore_state_after_run: bool = True
    client_id_prefix: str = "recovery_eval"


AUTONOMOUS_VERIFICATION_COMPATIBILITY_RULES: dict[str, dict[str, Any]] = {
    "create_entities": {
        "ignore_expect_contains": True,
        "reason": "official_memory_server_create_entities_does_not_echo_written_entities",
    }
}


def _bucket_name(score: float) -> str:
    if score < 0.2:
        return "[0.0,0.2)"
    if score < 0.4:
        return "[0.2,0.4)"
    if score < 0.6:
        return "[0.4,0.6)"
    if score < 0.8:
        return "[0.6,0.8)"
    return "[0.8,1.0]"


def _get_filtered_tools(candidate_tools: Optional[List[str]] = None) -> tuple[List[Dict[str, Any]], set[str]]:
    tools = mcp_manager.get_all_tools() if mcp_manager else []
    all_tool_names = {str(tool.get("name", "")).strip() for tool in tools if str(tool.get("name", "")).strip()}
    filtered_tools = tools
    if candidate_tools:
        allowed = {name.strip() for name in candidate_tools if name.strip()}
        filtered_tools = [tool for tool in tools if str(tool.get("name", "")).strip() in allowed]
    return filtered_tools, all_tool_names


def _build_case_result(
    *,
    evaluation: dict[str, Any],
    case_id: str,
    expected_tool: str,
    candidate_pool_size: int,
) -> dict[str, Any]:
    recommended_tools = evaluation.get("recommended_tools", [])
    return {
        "id": case_id,
        "expected_tool": expected_tool,
        "top1_match": bool(expected_tool and recommended_tools and recommended_tools[0] == expected_tool),
        "topk_match": bool(expected_tool and expected_tool in recommended_tools),
        "candidate_pool_size": candidate_pool_size,
        **evaluation,
    }


def _summarize_batch_items(items: List[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    return {
        "total": total,
        "top1_accuracy": round(sum(1 for item in items if item.get("top1_match")) / total, 4) if total else 0.0,
        "topk_recall": round(sum(1 for item in items if item.get("topk_match")) / total, 4) if total else 0.0,
        "mean_top_score": round(sum(float(item.get("top_score", 0.0)) for item in items) / total, 4) if total else 0.0,
        "mean_candidate_count": round(sum(float(item.get("candidate_count", 0.0)) for item in items) / total, 4) if total else 0.0,
    }


def _build_calibration(items: List[dict[str, Any]]) -> List[dict[str, Any]]:
    calibration_bins: Dict[str, Dict[str, float]] = {}
    for item in items:
        hit = 1.0 if item.get("top1_match") else 0.0
        top_score = float(item.get("top_score", 0.0))
        bucket_name = _bucket_name(top_score)
        calibration = calibration_bins.setdefault(
            bucket_name,
            {"count": 0.0, "score_sum": 0.0, "top1_hits": 0.0},
        )
        calibration["count"] += 1.0
        calibration["score_sum"] += top_score
        calibration["top1_hits"] += hit
    return [
        {
            "bucket": bucket,
            "count": int(stats["count"]),
            "mean_predicted_score": round(stats["score_sum"] / stats["count"], 4) if stats["count"] else 0.0,
            "empirical_top1_accuracy": round(stats["top1_hits"] / stats["count"], 4) if stats["count"] else 0.0,
            "gap": round(
                abs((stats["score_sum"] / stats["count"]) - (stats["top1_hits"] / stats["count"])),
                4,
            ) if stats["count"] else 0.0,
        }
        for bucket, stats in calibration_bins.items()
    ]


def _normalize_step_expectation_for_verification(step: AutonomousTrajectoryStep) -> dict[str, Any]:
    expected = {
        "should_succeed": step.should_succeed,
        "error_message": step.error_message or "",
        "expect_contains": list(step.expect_contains or []),
        "expect_not_contains": list(step.expect_not_contains or []),
    }
    rule = AUTONOMOUS_VERIFICATION_COMPATIBILITY_RULES.get(str(step.tool).strip(), {})
    if bool(rule.get("ignore_expect_contains", False)):
        expected["expect_contains"] = []
        expected["verification_compatibility_rule"] = str(rule.get("reason", ""))
    return expected


def _build_mode_stats(items: List[dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    mode_stats: Dict[str, Dict[str, float]] = {}
    for item in items:
        router_type = str(item.get("router_type", "unknown"))
        hit = 1.0 if item.get("top1_match") else 0.0
        top_score = float(item.get("top_score", 0.0))
        mode_bucket = mode_stats.setdefault(
            router_type,
            {"count": 0.0, "top1_hits": 0.0, "topk_hits": 0.0, "score_sum": 0.0},
        )
        mode_bucket["count"] += 1.0
        mode_bucket["top1_hits"] += hit
        mode_bucket["topk_hits"] += 1.0 if item.get("topk_match") else 0.0
        mode_bucket["score_sum"] += top_score
    return {
        mode: {
            "cases": int(stats["count"]),
            "top1_accuracy": round(stats["top1_hits"] / stats["count"], 4) if stats["count"] else 0.0,
            "topk_recall": round(stats["topk_hits"] / stats["count"], 4) if stats["count"] else 0.0,
            "mean_top_score": round(stats["score_sum"] / stats["count"], 4) if stats["count"] else 0.0,
        }
        for mode, stats in mode_stats.items()
    }


def _tool_catalog_for_names(candidate_tools: List[str]) -> List[Dict[str, Any]]:
    filtered_tools, _ = _get_filtered_tools(candidate_tools)
    return filtered_tools


def _resolve_candidate_tools_for_case(case: AutonomousTrajectoryCase) -> List[str]:
    candidate_names: List[str] = []
    for raw_name in list(case.candidate_tools or []) + list(case.tools_available or []):
        name = str(raw_name).strip()
        if name and name not in candidate_names:
            candidate_names.append(name)
    if candidate_names:
        return candidate_names
    inferred: List[str] = []
    for step in case.steps:
        name = str(step.tool).strip()
        if name and name not in inferred:
            inferred.append(name)
    return inferred


def _summarize_autonomous_rows(items: List[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(items)
    total_steps = sum(int(item.get("steps_total", 0)) for item in items)
    routed_steps = sum(int(item.get("routed_steps", 0)) for item in items)
    route_hits = sum(int(item.get("route_hits", 0)) for item in items)
    executed_steps = sum(int(item.get("executed_steps", 0)) for item in items)
    successful_calls = sum(int(item.get("successful_calls", 0)) for item in items)
    blocked_calls = sum(int(item.get("blocked_calls", 0)) for item in items)
    verified_steps = sum(int(item.get("verified_steps", 0)) for item in items)
    misroutes = sum(int(item.get("misroute_count", 0)) for item in items)
    failed_calls = sum(int(item.get("failed_calls", 0)) for item in items)
    actual_success_cases = sum(1 for item in items if item.get("actual_success"))
    expectation_matched_cases = sum(1 for item in items if item.get("expectation_matched"))
    wasted_calls = sum(int(item.get("wasted_calls", 0)) for item in items)
    policy_steps_total = 0
    policy_supported_steps = 0
    policy_fallback_steps = 0
    policy_unsupported_steps = 0
    memory_conditioned_steps = 0
    memory_conditioned_supported_steps = 0
    memory_conditioned_reused_steps = 0
    exact_match_steps = 0
    schema_match_steps = 0
    per_category: Dict[str, Dict[str, float]] = {}
    per_step: Dict[str, Dict[str, float]] = {}

    for item in items:
        category = str(item.get("category", "") or "uncategorized")
        category_bucket = per_category.setdefault(
            category,
            {
                "cases": 0.0,
                "actual_success_cases": 0.0,
                "expectation_matched_cases": 0.0,
                "policy_steps": 0.0,
                "fallback_steps": 0.0,
                "unsupported_steps": 0.0,
                "memory_conditioned_steps": 0.0,
                "memory_conditioned_supported_steps": 0.0,
                "memory_conditioned_reused_steps": 0.0,
            },
        )
        category_bucket["cases"] += 1.0
        category_bucket["actual_success_cases"] += 1.0 if item.get("actual_success") else 0.0
        category_bucket["expectation_matched_cases"] += 1.0 if item.get("expectation_matched") else 0.0

        for step_record in item.get("step_records", []) or []:
            if not isinstance(step_record, dict):
                continue
            policy = step_record.get("argument_policy", {}) or {}
            mode = str(policy.get("mode", "gold"))
            supported = bool(policy.get("supported", False))
            fallback_used = bool(policy.get("fallback_used", False))
            derivation_path = [str(part) for part in list(policy.get("derivation_path", [])) if str(part).strip()]
            reused_state = any(part.startswith("state.") for part in derivation_path)
            step_index_key = str(int(step_record.get("step_index", -1)) + 1) if str(step_record.get("step_index", "")).strip() else "unknown"
            step_bucket = per_step.setdefault(
                step_index_key,
                {
                    "steps": 0.0,
                    "supported_steps": 0.0,
                    "fallback_steps": 0.0,
                    "unsupported_steps": 0.0,
                    "memory_conditioned_steps": 0.0,
                    "memory_conditioned_supported_steps": 0.0,
                    "memory_conditioned_reused_steps": 0.0,
                    "verified_steps": 0.0,
                    "successful_calls": 0.0,
                },
            )

            policy_steps_total += 1
            category_bucket["policy_steps"] += 1.0
            step_bucket["steps"] += 1.0
            if supported:
                policy_supported_steps += 1
                step_bucket["supported_steps"] += 1.0
            else:
                policy_unsupported_steps += 1
                category_bucket["unsupported_steps"] += 1.0
                step_bucket["unsupported_steps"] += 1.0
            if fallback_used:
                policy_fallback_steps += 1
                category_bucket["fallback_steps"] += 1.0
                step_bucket["fallback_steps"] += 1.0
            if bool(policy.get("exact_match", False)):
                exact_match_steps += 1
            if bool(policy.get("schema_match", False)):
                schema_match_steps += 1
            if bool(step_record.get("verified", False)):
                step_bucket["verified_steps"] += 1.0
            result_payload = step_record.get("result", {}) or {}
            if bool(isinstance(result_payload, dict) and result_payload.get("success", False)):
                step_bucket["successful_calls"] += 1.0

            if mode.startswith("memory_conditioned"):
                memory_conditioned_steps += 1
                category_bucket["memory_conditioned_steps"] += 1.0
                step_bucket["memory_conditioned_steps"] += 1.0
                if supported:
                    memory_conditioned_supported_steps += 1
                    category_bucket["memory_conditioned_supported_steps"] += 1.0
                    step_bucket["memory_conditioned_supported_steps"] += 1.0
                if reused_state:
                    memory_conditioned_reused_steps += 1
                    category_bucket["memory_conditioned_reused_steps"] += 1.0
                    step_bucket["memory_conditioned_reused_steps"] += 1.0

    per_category_summary = {
        category: {
            "cases": int(stats["cases"]),
            "actual_case_success_rate": round(stats["actual_success_cases"] / stats["cases"], 4) if stats["cases"] else 0.0,
            "expectation_match_rate": round(stats["expectation_matched_cases"] / stats["cases"], 4) if stats["cases"] else 0.0,
            "policy_steps": int(stats["policy_steps"]),
            "fallback_rate": round(stats["fallback_steps"] / stats["policy_steps"], 4) if stats["policy_steps"] else 0.0,
            "unsupported_rate": round(stats["unsupported_steps"] / stats["policy_steps"], 4) if stats["policy_steps"] else 0.0,
            "memory_conditioned_step_share": round(stats["memory_conditioned_steps"] / stats["policy_steps"], 4) if stats["policy_steps"] else 0.0,
            "memory_conditioned_supported_rate": round(
                stats["memory_conditioned_supported_steps"] / stats["memory_conditioned_steps"], 4
            ) if stats["memory_conditioned_steps"] else 0.0,
            "state_reuse_rate": round(
                stats["memory_conditioned_reused_steps"] / stats["memory_conditioned_steps"], 4
            ) if stats["memory_conditioned_steps"] else 0.0,
        }
        for category, stats in per_category.items()
    }
    per_step_summary = {
        step_idx: {
            "steps": int(stats["steps"]),
            "supported_rate": round(stats["supported_steps"] / stats["steps"], 4) if stats["steps"] else 0.0,
            "fallback_rate": round(stats["fallback_steps"] / stats["steps"], 4) if stats["steps"] else 0.0,
            "unsupported_rate": round(stats["unsupported_steps"] / stats["steps"], 4) if stats["steps"] else 0.0,
            "memory_conditioned_step_share": round(stats["memory_conditioned_steps"] / stats["steps"], 4) if stats["steps"] else 0.0,
            "state_reuse_rate": round(
                stats["memory_conditioned_reused_steps"] / stats["memory_conditioned_steps"], 4
            ) if stats["memory_conditioned_steps"] else 0.0,
            "verified_rate": round(stats["verified_steps"] / stats["steps"], 4) if stats["steps"] else 0.0,
            "successful_call_rate": round(stats["successful_calls"] / stats["steps"], 4) if stats["steps"] else 0.0,
        }
        for step_idx, stats in per_step.items()
    }
    return {
        "total_cases": total_cases,
        "total_steps": total_steps,
        "routed_steps": routed_steps,
        "route_top1_accuracy": round(route_hits / routed_steps, 4) if routed_steps else 0.0,
        "execution_rate": round(executed_steps / routed_steps, 4) if routed_steps else 0.0,
        "tool_success_rate": round(successful_calls / executed_steps, 4) if executed_steps else 0.0,
        "blocked_call_rate": round(blocked_calls / executed_steps, 4) if executed_steps else 0.0,
        "verification_rate": round(verified_steps / executed_steps, 4) if executed_steps else 0.0,
        "misroute_rate": round(misroutes / routed_steps, 4) if routed_steps else 0.0,
        "wasted_call_rate": round(wasted_calls / executed_steps, 4) if executed_steps else 0.0,
        "actual_case_success_rate": round(actual_success_cases / total_cases, 4) if total_cases else 0.0,
        "expectation_match_rate": round(expectation_matched_cases / total_cases, 4) if total_cases else 0.0,
        "argument_policy": {
            "policy_steps": policy_steps_total,
            "supported_rate": round(policy_supported_steps / policy_steps_total, 4) if policy_steps_total else 0.0,
            "fallback_rate": round(policy_fallback_steps / policy_steps_total, 4) if policy_steps_total else 0.0,
            "unsupported_rate": round(policy_unsupported_steps / policy_steps_total, 4) if policy_steps_total else 0.0,
            "schema_match_rate": round(schema_match_steps / policy_steps_total, 4) if policy_steps_total else 0.0,
            "exact_match_rate": round(exact_match_steps / policy_steps_total, 4) if policy_steps_total else 0.0,
            "memory_conditioned_step_share": round(memory_conditioned_steps / policy_steps_total, 4) if policy_steps_total else 0.0,
            "memory_conditioned_supported_rate": round(
                memory_conditioned_supported_steps / memory_conditioned_steps, 4
            ) if memory_conditioned_steps else 0.0,
            "state_reuse_rate": round(
                memory_conditioned_reused_steps / memory_conditioned_steps, 4
            ) if memory_conditioned_steps else 0.0,
            "counts": {
                "policy_steps": policy_steps_total,
                "supported_steps": policy_supported_steps,
                "fallback_steps": policy_fallback_steps,
                "unsupported_steps": policy_unsupported_steps,
                "memory_conditioned_steps": memory_conditioned_steps,
                "memory_conditioned_supported_steps": memory_conditioned_supported_steps,
                "memory_conditioned_reused_steps": memory_conditioned_reused_steps,
            },
        },
        "per_category": per_category_summary,
        "per_step": per_step_summary,
        "totals": {
            "total_cases": total_cases,
            "total_steps": total_steps,
            "routed_steps": routed_steps,
            "route_hits": route_hits,
            "executed_steps": executed_steps,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "blocked_calls": blocked_calls,
            "verified_steps": verified_steps,
            "misroutes": misroutes,
            "wasted_calls": wasted_calls,
            "actual_success_cases": actual_success_cases,
            "expectation_matched_cases": expectation_matched_cases,
        },
    }


class GovernanceRollbackRequest(BaseModel):
    reason: str = "manual_recovery_check"

class ResourceRequest(BaseModel):
    uri: str
    server_name: Optional[str] = None

class PromptRequest(BaseModel):
    name: str
    arguments: Optional[Dict[str, str]] = None
    server_name: Optional[str] = None


class CustomModelConfig(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    type: str = "text"
    max_tokens: int = 8192
    provider: str = "openrouter"


class ProviderRuntimeConfigRequest(BaseModel):
    siliconflow_api_key: Optional[str] = None
    siliconflow_base_url: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = None
    default_model: Optional[str] = None
    custom_models: List[CustomModelConfig] = []


class ProviderConnectivityCheckRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class TEMModeRequest(BaseModel):
    mode: str


class TEMResetRequest(BaseModel):
    recipes: bool = False
    guards: bool = False
    traces: bool = False
    pending: bool = True


class MemoryPlaneResetRequest(BaseModel):
    router: bool = True
    traces: bool = False


class RegressionSandboxBeginRequest(BaseModel):
    label: str = "browser_runtime_smoke"
    include_uploads: bool = True


class RegressionSandboxRestoreRequest(BaseModel):
    sandbox_id: str


async def send_request_delivery(
    client_id: str,
    request_id: Optional[str],
    status: str,
    *,
    message: str = "",
    details: Optional[Dict[str, Any]] = None,
):
    """Notify the frontend about the lifecycle of a user-originated websocket request."""
    if not request_id:
        return
    await manager.send_personal_message(
        {
            "type": "request_delivery",
            "request_id": request_id,
            "status": status,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        },
        client_id,
    )


async def _send_action_event(
    client_id: str,
    *,
    request_id: Optional[str],
    action_id: str,
    stage: str,
    title: str,
    status: str = "running",
    summary: str = "",
    target: Optional[Dict[str, Any]] = None,
    source_plane: str = "mcp",
    resource_refs: Optional[List[Dict[str, Any]]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    await manager.send_personal_message(
        {
            "type": "action_event",
            "request_id": request_id,
            "action_id": action_id,
            "stage": stage,
            "status": status,
            "title": title,
            "summary": summary,
            "source_plane": source_plane,
            "target": details.get("target") if isinstance(details, dict) and isinstance(details.get("target"), dict) else (target or {}),
            "resource_refs": resource_refs or [],
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        },
        client_id,
    )


def _build_recovery_attempt(
    *,
    tool_name: str,
    server_name: str,
    resolved_arguments: Dict[str, Any],
    original_user_content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    workspace_root: str = "",
    result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    normalized_tool_name = str(tool_name or "").strip().lower()
    current_args = dict(resolved_arguments or {})
    error_text = str((result or {}).get("error") or (result or {}).get("message") or "").strip().lower()
    attachment_list = attachments if isinstance(attachments, list) else []

    if normalized_tool_name in {"read_file", "read_text_file", "read_multiple_files"}:
        if "outside current filesystem allowed roots" in error_text or "outside allowed roots" in error_text:
            uploaded_path = _get_uploaded_attachment_filesystem_path(
                attachment_list[0] if attachment_list else {},
                workspace_root=workspace_root,
            )
            if uploaded_path and str(current_args.get("path") or "").strip() != uploaded_path:
                next_args = {**current_args, "path": uploaded_path}
                return {
                    "strategy": "prefer_uploaded_workspace_copy",
                    "reason": "Retry with the uploaded workspace-local copy of the attachment.",
                    "arguments": next_args,
                }

        if not str(current_args.get("path") or "").strip():
            uploaded_path = _get_uploaded_attachment_filesystem_path(
                attachment_list[0] if attachment_list else {},
                workspace_root=workspace_root,
            )
            if uploaded_path:
                next_args = {**current_args, "path": uploaded_path}
                return {
                    "strategy": "fill_missing_path_from_attachment",
                    "reason": "Retry with the uploaded attachment path.",
                    "arguments": next_args,
                }

    if _is_fetch_like_tool({"name": tool_name, "server": server_name, "input_schema": {"properties": {"url": {"type": "string"}}}}):
        current_url = str(current_args.get("url") or "").strip()
        extracted_url = _extract_path_like_text(original_user_content, prefer_url=True, workspace_root=workspace_root)
        if not current_url and extracted_url and URL_PATTERN.match(extracted_url):
            next_args = {**current_args, "url": extracted_url}
            return {
                "strategy": "fill_missing_url_from_query",
                "reason": "Retry with URL extracted from the user query.",
                "arguments": next_args,
            }

    if normalized_tool_name == "sequentialthinking":
        required_defaults = {
            "thought": str(current_args.get("thought") or original_user_content or "Analyze the request step by step.").strip(),
            "nextThoughtNeeded": bool(current_args.get("nextThoughtNeeded", False)),
            "thoughtNumber": int(current_args.get("thoughtNumber", 1) or 1),
            "totalThoughts": int(current_args.get("totalThoughts", 1) or 1),
        }
        if current_args != {**current_args, **required_defaults}:
            next_args = {**current_args, **required_defaults}
            return {
                "strategy": "fill_sequentialthinking_defaults",
                "reason": "Retry with safe sequential thinking defaults.",
                "arguments": next_args,
            }

    if any(marker in error_text for marker in {"validation error", "invalid input", "missing required"}):
        text_like_retry = dict(current_args)
        if not str(text_like_retry.get("text") or "").strip():
            text_like_retry["text"] = str(original_user_content or "").strip()
        if text_like_retry != current_args:
            return {
                "strategy": "fill_generic_text_input",
                "reason": "Retry with the original user content as generic text input.",
                "arguments": text_like_retry,
            }

    return None


def get_shared_http_client() -> httpx.AsyncClient:
    global shared_http_client
    if shared_http_client is None or shared_http_client.is_closed:
        shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(API_TIMEOUT_SECONDS),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
        )
    return shared_http_client


runtime_config_service = RuntimeConfigService(
    build_available_models=build_available_models,
    default_model_id=DEFAULT_MODEL_ID,
    openrouter_default_model_id=OPENROUTER_DEFAULT_MODEL_ID,
    siliconflow_base_url_default=SILICONFLOW_BASE_URL_DEFAULT,
    openrouter_base_url_default=OPENROUTER_BASE_URL_DEFAULT,
    get_shared_http_client=get_shared_http_client,
)
runtime_provider_overrides = runtime_config_service.provider_overrides
runtime_tool_policy = runtime_config_service.tool_policy
runtime_auto_tool_routing = runtime_config_service.auto_tool_routing


request_runtime_service = RequestRuntimeService(
    journal_path=REQUEST_JOURNAL_PATH,
    max_size=REQUEST_CACHE_MAX_SIZE,
    journal_version=REQUEST_JOURNAL_VERSION,
    default_model_id=DEFAULT_MODEL_ID,
    summarize_request_result_payload=lambda payload: _summarize_request_result_payload(payload),
)
operation_audit_log = OperationAuditLog(project_root / "artifacts" / "memory" / "system_operation_audit.jsonl")
system_operation_harness = SystemOperationHarness(
    project_root=project_root,
    logs_root=project_root / "artifacts" / "logs",
)
agent_task_runtime = AgentTaskRuntime(path=project_root / "artifacts" / "memory" / "agent_tasks.json")
request_result_cache = request_runtime_service.result_cache
inflight_requests = request_runtime_service.inflight_requests
inflight_request_owners = request_runtime_service.inflight_request_owners
request_runtime_journal = request_runtime_service.runtime_journal
request_journal_lock = request_runtime_service.lock


async def _execute_agent_mcp_step(
    task_id: str,
    arguments: Dict[str, Any],
    tool_name: str,
    server_name: str,
    workspace_root: str,
) -> Dict[str, Any]:
    safe_server = str(server_name or "").strip()
    active_mcp_manager = mcp_manager
    if str(workspace_root or "").strip():
        active_mcp_manager, _ = await _get_effective_mcp_manager({"workspace_root": workspace_root})
    if not active_mcp_manager:
        return {
            "success": False,
            "task_id": task_id,
            "tool_name": tool_name,
            "server_name": safe_server,
            "error": "No active MCP manager is available.",
        }
    tool_catalog = active_mcp_manager.get_all_tools() if hasattr(active_mcp_manager, "get_all_tools") else []
    matched_tool = next(
        (
            tool
            for tool in tool_catalog
            if str(tool.get("name", "")).strip() == str(tool_name).strip()
            and (not safe_server or str(tool.get("server", "")).strip() == safe_server)
        ),
        None,
    )
    if matched_tool is None:
        fallback = _resolve_tool_route_from_goal(
            str(tool_name or ""),
            attachments=[],
            tools=tool_catalog,
        )
        if fallback:
            tool_name = str(fallback.get("tool_name", tool_name))
            safe_server = str(fallback.get("server_name", safe_server))
    try:
        normalized_arguments = active_mcp_manager.normalize_tool_arguments(tool_name, arguments or {}, safe_server)
    except Exception:
        normalized_arguments = dict(arguments or {})
    result = await active_mcp_manager.call_tool(tool_name, normalized_arguments, safe_server or None)
    return {
        "success": False if isinstance(result, dict) and result.get("success") is False else True,
        "task_id": task_id,
        "tool_name": tool_name,
        "server_name": safe_server,
        "arguments": normalized_arguments,
        "result": result,
    }


agent_task_executor = AgentTaskExecutor(
    runtime=agent_task_runtime,
    operation_audit_log=operation_audit_log,
    system_operation_harness=system_operation_harness,
    runtime_config_service=runtime_config_service,
    memory_control_plane=memory_control_plane,
    tool_runner=_execute_agent_mcp_step,
    system_op_audit_ingestor=memory_control_plane.register_system_operation_audit,
)
skill_runtime_resolver = SkillRuntimeResolver(agent_skills_registry)
agent_run_scheduler = AgentRunScheduler(
    runtime=agent_task_runtime,
    executor=agent_task_executor,
)


async def _get_effective_mcp_manager(
    workspace_context_config: Optional[Dict[str, Any]] = None,
):
    workspace_root = ""
    if isinstance(workspace_context_config, dict):
        workspace_root = str(workspace_context_config.get("workspace_root", "") or "").strip()
    if not workspace_root:
        return mcp_manager, {
            "workspace_enabled": False,
            "workspace_root": "",
            "workspace_config_path": "",
            "workspace_servers": [],
            "sources": ["mcp_config.json"],
        }
    try:
        workspace_manager, metadata = await workspace_mcp_pool.get_manager(workspace_root, base_manager=mcp_manager)
        return workspace_manager or mcp_manager, metadata
    except Exception as exc:
        logger.warning("failed to load workspace MCP manager for %s: %s", workspace_root, exc)
        return mcp_manager, {
            "workspace_enabled": False,
            "workspace_root": workspace_root,
            "workspace_config_path": "",
            "workspace_servers": [],
            "sources": ["mcp_config.json"],
            "error": str(exc),
        }


def _build_assistant_message_id(request_id: Optional[str]) -> str:
    normalized_request_id = str(request_id or "").strip()
    if normalized_request_id:
        return f"assistant-{normalized_request_id}"
    return f"assistant-{uuid.uuid4().hex}"


async def _send_response_start_event(
    client_id: str,
    *,
    request_id: Optional[str],
    message_id: str,
    model_id: str,
    model_name: str,
    timestamp: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    await manager.send_personal_message(
        {
            "type": "response_start",
            "id": message_id,
            "request_id": request_id,
            "model_used": model_id,
            "model_name": model_name,
            "timestamp": timestamp or datetime.now().isoformat(),
            "metadata": metadata or {},
        },
        client_id,
    )


async def _send_response_delta_event(
    client_id: str,
    *,
    request_id: Optional[str],
    message_id: str,
    delta: str,
) -> None:
    if not delta:
        return
    await manager.send_personal_message(
        {
            "type": "response_delta",
            "id": message_id,
            "request_id": request_id,
            "delta": delta,
            "timestamp": datetime.now().isoformat(),
        },
        client_id,
    )


async def _send_response_done_event(
    client_id: str,
    *,
    request_id: Optional[str],
    message_id: str,
    content: str,
    model_id: str,
    model_name: str,
    timestamp: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    memory: Optional[Dict[str, Any]] = None,
    memory_plane: Optional[Dict[str, Any]] = None,
    run_trace: Optional[Dict[str, Any]] = None,
    generated_images: Optional[List[Dict[str, Any]]] = None,
) -> None:
    image_outputs = generated_images if isinstance(generated_images, list) else []
    event_metadata = dict(metadata or {})
    if image_outputs:
        event_metadata["generated_images"] = image_outputs
    await manager.send_personal_message(
        {
            "type": "response_done",
            "id": message_id,
            "request_id": request_id,
            "content": content,
            "generated_images": image_outputs,
            "image_paths": [
                str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                for item in image_outputs
                if isinstance(item, dict) and str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
            ],
            "model_used": model_id,
            "model_name": model_name,
            "memory": memory,
            "memory_plane": memory_plane,
            "run_trace": run_trace,
            "timestamp": timestamp or datetime.now().isoformat(),
            "metadata": event_metadata,
        },
        client_id,
    )


def _guess_image_mime_type(value: str, fallback: str = "image/png") -> str:
    text = str(value or "").strip().lower()
    if text.startswith("data:") and ";" in text:
        return text[5:text.find(";")] or fallback
    if ".jpg" in text or ".jpeg" in text:
        return "image/jpeg"
    if ".webp" in text:
        return "image/webp"
    if ".gif" in text:
        return "image/gif"
    if ".svg" in text:
        return "image/svg+xml"
    return fallback


def _normalize_generated_image_entry(value: Any, *, source: str = "model") -> Optional[Dict[str, Any]]:
    if not value:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("data:image/") or text.startswith("http://") or text.startswith("https://"):
            return {
                "url": text,
                "mime_type": _guess_image_mime_type(text),
                "source": source,
            }
        if len(text) > 80 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", text):
            compact = re.sub(r"\s+", "", text)
            return {
                "data_url": f"data:image/png;base64,{compact}",
                "mime_type": "image/png",
                "source": source,
            }
        return None
    if not isinstance(value, dict):
        return None

    mime_type = str(
        value.get("mime_type")
        or value.get("mimeType")
        or value.get("media_type")
        or value.get("type")
        or "image/png"
    )
    if not mime_type.startswith("image/"):
        mime_type = _guess_image_mime_type(str(value.get("url") or value.get("image_url") or ""), "image/png")

    url_value = value.get("url") or value.get("image_url") or value.get("uri") or value.get("path")
    if isinstance(url_value, dict):
        url_value = url_value.get("url")
    if isinstance(url_value, str) and url_value.strip():
        image_url = url_value.strip()
        return {
            "url": image_url,
            "mime_type": _guess_image_mime_type(image_url, mime_type),
            "alt": str(value.get("alt") or value.get("revised_prompt") or value.get("prompt") or "").strip(),
            "source": str(value.get("source") or source),
        }

    b64_value = (
        value.get("b64_json")
        or value.get("base64")
        or value.get("base64_data")
        or value.get("image_base64")
        or value.get("data")
    )
    if isinstance(b64_value, str) and b64_value.strip():
        compact = b64_value.strip()
        if compact.startswith("data:image/"):
            data_url = compact
            mime_type = _guess_image_mime_type(data_url, mime_type)
        else:
            compact = re.sub(r"\s+", "", compact)
            data_url = f"data:{mime_type};base64,{compact}"
        return {
            "data_url": data_url,
            "mime_type": mime_type,
            "alt": str(value.get("alt") or value.get("revised_prompt") or value.get("prompt") or "").strip(),
            "source": str(value.get("source") or source),
        }
    return None


def _collect_generated_images_from_value(value: Any, *, source: str = "model") -> List[Dict[str, Any]]:
    images: List[Dict[str, Any]] = []
    normalized = _normalize_generated_image_entry(value, source=source)
    if normalized:
        images.append(normalized)
        return images
    if isinstance(value, list):
        for item in value:
            images.extend(_collect_generated_images_from_value(item, source=source))
    elif isinstance(value, dict):
        for key in (
            "data",
            "images",
            "image",
            "output_image",
            "image_url",
            "generated_images",
            "artifacts",
            "outputs",
            "content",
        ):
            if key in value:
                images.extend(_collect_generated_images_from_value(value.get(key), source=source))
    return images


def _dedupe_generated_images(images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        image_url = str(image.get("url") or image.get("data_url") or image.get("path") or "").strip()
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        result.append({key: value for key, value in image.items() if value not in ("", None)})
    return result


def _extract_generated_images_from_result(result: Any) -> List[Dict[str, Any]]:
    return _dedupe_generated_images(_collect_generated_images_from_value(result, source="model"))


def _extract_stream_text_delta(delta_payload: Any) -> str:
    if isinstance(delta_payload, str):
        return delta_payload
    if isinstance(delta_payload, list):
        parts: List[str] = []
        for item in delta_payload:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "") or "").strip().lower()
            if item_type in {"text", "output_text"}:
                text_value = item.get("text", "")
                if isinstance(text_value, str):
                    parts.append(text_value)
        return "".join(parts)
    return ""


async def _stream_chat_completion_to_client(
    client: "httpx.AsyncClient",
    *,
    client_id: str,
    request_id: Optional[str],
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    provider: str,
    model_id: str,
    model_name: str,
    timeout_seconds: float = API_TIMEOUT_SECONDS,
    memory: Optional[Dict[str, Any]] = None,
    memory_plane: Optional[Dict[str, Any]] = None,
    run_trace: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    import httpx

    retries = OPENROUTER_MAX_RETRIES if provider == "openrouter" else 1
    stream_payload = {**payload, "stream": True}
    message_id = _build_assistant_message_id(request_id)
    start_sent = False

    for attempt in range(1, retries + 1):
        async with client.stream(
            "POST",
            url,
            headers=headers,
            json=stream_payload,
            timeout=timeout_seconds,
        ) as response:
            if response.status_code == 429 and attempt < retries:
                delay = min(
                    OPENROUTER_RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0.0, 0.4),
                    OPENROUTER_RETRY_MAX_SECONDS,
                )
                logger.warning(f"OpenRouter rate limited during stream setup (429), retry {attempt}/{retries} in {delay:.2f}s")
                await asyncio.sleep(delay)
                continue

            if response.status_code != 200:
                error_text = (await response.aread()).decode("utf-8", errors="replace")[:500]
                raise RuntimeError(_friendly_provider_error(provider, response.status_code, error_text))

            collected_chunks: List[str] = []
            async for raw_line in response.aiter_lines():
                line = str(raw_line or "").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except Exception:
                    continue

                choices = chunk.get("choices", []) if isinstance(chunk, dict) else []
                if not choices or not isinstance(choices[0], dict):
                    continue
                delta_obj = choices[0].get("delta", {})
                if not isinstance(delta_obj, dict):
                    continue

                text_delta = _extract_stream_text_delta(delta_obj.get("content"))
                if not text_delta:
                    continue

                if not start_sent:
                    await _send_response_start_event(
                        client_id,
                        request_id=request_id,
                        message_id=message_id,
                        model_id=model_id,
                        model_name=model_name,
                        metadata=metadata,
                    )
                    start_sent = True

                collected_chunks.append(text_delta)
                await _send_response_delta_event(
                    client_id,
                    request_id=request_id,
                    message_id=message_id,
                    delta=text_delta,
                )

            final_content = "".join(collected_chunks).strip()
            if not final_content:
                return None

            await _send_response_done_event(
                client_id,
                request_id=request_id,
                message_id=message_id,
                content=final_content,
                model_id=model_id,
                model_name=model_name,
                metadata=metadata,
                memory=memory,
                memory_plane=memory_plane,
                run_trace=run_trace,
            )

            return {
                "id": message_id,
                "content": final_content,
                "streamed": True,
            }

    return None


def _clean_extracted_path_text(value: str) -> str:
    return str(value or "").strip().rstrip(".,;:!?)]}>，。；：！？）】》」'")


def _resolve_workspace_relative_path(value: str, workspace_root: str = "") -> str:
    normalized = _clean_extracted_path_text(value)
    if not normalized:
        return ""
    candidate = Path(normalized)
    if candidate.is_absolute():
        return str(candidate)

    workspace_candidate_root = safe_workspace_root(workspace_root)
    if workspace_candidate_root is not None:
        try:
            workspace_candidate = (workspace_candidate_root / candidate).resolve()
            if workspace_candidate.exists():
                return str(workspace_candidate)
        except Exception:
            pass

    project_candidate = (project_root / candidate).resolve()
    try:
        project_candidate.relative_to(project_root.resolve())
    except Exception:
        return normalized
    if project_candidate.exists():
        return str(project_candidate)
    if workspace_candidate_root is not None:
        try:
            return str((workspace_candidate_root / candidate).resolve())
        except Exception:
            return normalized
    return normalized


def _get_filesystem_allowed_roots() -> List[Path]:
    fallback_root = project_root.resolve()
    try:
        config = read_mcp_config()
    except Exception as exc:
        logger.warning(f"failed to read filesystem allowed roots from mcp_config.json: {exc}")
        return [fallback_root]

    servers = config.get("mcpServers") if isinstance(config, dict) else {}
    filesystem_config = servers.get("filesystem") if isinstance(servers, dict) else {}
    args = filesystem_config.get("args") if isinstance(filesystem_config, dict) else []
    if not isinstance(args, list):
        return [fallback_root]

    roots: List[Path] = []
    try:
        package_index = args.index("@modelcontextprotocol/server-filesystem")
        path_args = args[package_index + 1 :]
    except ValueError:
        path_args = args

    for raw_value in path_args:
        value = str(raw_value or "").strip()
        if not value or value.startswith("-"):
            continue
        if value.startswith("@modelcontextprotocol/"):
            continue
        try:
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
            roots.append(resolved)
        except Exception:
            continue

    return roots or [fallback_root]


def _is_filesystem_path_allowed(value: str, workspace_root: str = "") -> bool:
    normalized = _clean_extracted_path_text(value)
    if not normalized:
        return False

    resolved_text = _resolve_workspace_relative_path(normalized, workspace_root=workspace_root)
    candidate = Path(resolved_text)
    if not candidate.is_absolute():
        try:
            candidate = (project_root / candidate).resolve()
        except Exception:
            return False

    try:
        resolved_candidate = candidate.resolve()
    except Exception:
        return False

    allowed_roots = _get_filesystem_allowed_roots()
    workspace_candidate_root = safe_workspace_root(workspace_root)
    if workspace_candidate_root is not None:
        allowed_roots = [*allowed_roots, workspace_candidate_root.resolve()]

    for root in allowed_roots:
        try:
            resolved_candidate.relative_to(root)
            return True
        except Exception:
            continue

    return False


def _get_uploaded_attachment_filesystem_path(attachment: Dict[str, Any], workspace_root: str = "") -> str:
    if not isinstance(attachment, dict):
        return ""
    candidate = str(attachment.get("file_path") or attachment.get("path") or "").strip()
    if candidate and _is_filesystem_path_allowed(candidate, workspace_root=workspace_root):
        return candidate
    return ""


def _get_uploaded_image_attachment(attachments: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not isinstance(attachments, list):
        return {}
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        mime_type = str(attachment.get("mime_type") or attachment.get("content_type") or "").strip().lower()
        if bool(attachment.get("is_image")) or mime_type.startswith("image/"):
            return attachment
    return {}


def _get_uploaded_image_path(attachments: Optional[List[Dict[str, Any]]], workspace_root: str = "") -> str:
    image_attachment = _get_uploaded_image_attachment(attachments)
    return _get_uploaded_attachment_filesystem_path(image_attachment, workspace_root=workspace_root)


def _should_prefer_uploaded_attachment_path(
    *,
    server_name: str,
    key: str,
    prefer_url: bool,
    candidate_value: Any,
    uploaded_attachment_path: str,
) -> bool:
    if not uploaded_attachment_path:
        return False

    normalized_key = str(key or "").strip().lower()
    if prefer_url or "filename" in normalized_key:
        return False

    candidate_text = str(candidate_value or "").strip()
    if not candidate_text:
        return True
    return not _is_filesystem_path_allowed(candidate_text)


def _is_likely_image_argument(name: str, schema: Any) -> bool:
    normalized_name = str(name or "").strip().lower()
    description = ""
    if isinstance(schema, dict):
        description = str(schema.get("description") or schema.get("title") or "").lower()
    return (
        normalized_name in IMAGE_ARGUMENT_NAMES
        or normalized_name.endswith("image_path")
        or normalized_name.endswith("_image")
        or "image" in normalized_name
        or "photo" in normalized_name
        or "screenshot" in normalized_name
        or "image" in description
        or "photo" in description
        or "screenshot" in description
    )


def _is_likely_task_text_argument(name: str, schema: Any) -> bool:
    normalized_name = str(name or "").strip().lower()
    description = ""
    if isinstance(schema, dict):
        description = str(schema.get("description") or schema.get("title") or "").lower()
    return (
        normalized_name in TASK_TEXT_ARGUMENT_NAMES
        or normalized_name.endswith("_question")
        or normalized_name.endswith("_query")
        or normalized_name.endswith("_prompt")
        or "question" in normalized_name
        or "query" in normalized_name
        or "prompt" in normalized_name
        or "instruction" in normalized_name
        or "user request" in description
        or "user question" in description
        or "question" in description
        or "prompt" in description
    )


def _with_friendly_tool_error(result: Any) -> Any:
    if not isinstance(result, dict):
        return result

    tool_name = str(result.get("tool_name", "")).strip()
    server_name = str(result.get("server", result.get("server_name", ""))).strip().lower()
    error_text = str(result.get("error", "") or "").strip()
    lowered = error_text.lower()

    if server_name == "filesystem" and "access denied - path outside allowed directories" in lowered:
        friendly = (
            "This local path is outside the filesystem MCP allowed roots. "
            "If this came from a local file, upload it first so the system can read the workspace copy under "
            "D:\\mirror_mcp, or add that directory to the filesystem server allowed directories."
        )
        return {
            **result,
            "error": friendly,
            "raw_error": error_text,
            "error_type": result.get("error_type") or "FilesystemPathOutsideAllowedRoots",
            "error_hint": {
                "kind": "filesystem_allowed_roots",
                "tool_name": tool_name,
                "server": server_name,
                "allowed_roots": [str(root) for root in _get_filesystem_allowed_roots()],
                "suggestion": friendly,
            },
        }

    return result


def _looks_like_fabricated_tool_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in FABRICATED_TOOL_CALL_PATTERNS)


def _extract_path_like_text(text: str, prefer_url: bool = False, workspace_root: str = "") -> str:
    normalized = str(text or "")
    url_match = URL_PATTERN.search(normalized)
    if prefer_url and url_match:
        return _clean_extracted_path_text(url_match.group(0))
    quoted_match = QUOTED_PATH_PATTERN.search(normalized)
    if quoted_match:
        return _resolve_workspace_relative_path(quoted_match.group(1), workspace_root=workspace_root)
    at_path_match = AT_PATH_PATTERN.search(normalized)
    if at_path_match:
        return _resolve_workspace_relative_path(at_path_match.group(1), workspace_root=workspace_root)
    windows_match = WINDOWS_PATH_PATTERN.search(normalized)
    if windows_match:
        return _clean_extracted_path_text(windows_match.group(0))
    relative_match = RELATIVE_FILE_PATTERN.search(normalized)
    if relative_match:
        return _resolve_workspace_relative_path(relative_match.group(0), workspace_root=workspace_root)
    unix_match = UNIX_PATH_PATTERN.search(normalized)
    if unix_match:
        return _resolve_workspace_relative_path(unix_match.group(0), workspace_root=workspace_root)
    return _clean_extracted_path_text(url_match.group(0)) if url_match else ""


def _is_likely_path_argument(name: str, schema: Any) -> bool:
    normalized_name = str(name or "").strip().lower()
    description = ""
    if isinstance(schema, dict):
        description = str(schema.get("description") or schema.get("title") or "").lower()
    description_has_path_hint = any(
        hint in description
        for hint in {
            "path",
            "file path",
            "filepath",
            "filename",
            "directory",
            "uri",
            "url",
        }
    )
    return (
        normalized_name in PATH_ARGUMENT_NAMES
        or normalized_name.endswith("_path")
        or normalized_name.endswith("path")
        or "filename" in normalized_name
        or "file" in normalized_name
        or normalized_name in {"uri", "url"}
        or description_has_path_hint
    )


def _tool_schema_properties(tool: Dict[str, Any]) -> Dict[str, Any]:
    schema = tool.get("input_schema") if isinstance(tool, dict) else {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    return properties if isinstance(properties, dict) else {}


def _tool_has_path_like_argument(tool: Dict[str, Any]) -> bool:
    return any(_is_likely_path_argument(str(key), value) for key, value in _tool_schema_properties(tool).items())


def _tool_has_url_like_argument(tool: Dict[str, Any]) -> bool:
    for key, value in _tool_schema_properties(tool).items():
        key_text = str(key or "").strip().lower()
        description = str(value.get("description", "") if isinstance(value, dict) else "").lower()
        if key_text in {"url", "uri"} or "url" in key_text or "uri" in key_text or "url" in description:
            return True
    return False


def _is_fetch_like_tool(tool: Dict[str, Any]) -> bool:
    tool_name = str(tool.get("name", "")).strip().lower()
    description = str(tool.get("description", "") or "").strip().lower()
    return _tool_has_url_like_argument(tool) and (
        tool_name in {"fetch", "get_url", "read_url", "web_fetch"}
        or "fetch" in tool_name
        or "url" in tool_name
        or "fetches a url" in description
        or "web" in description
    )


def _build_web_search_url(query: str) -> str:
    from urllib.parse import quote_plus

    normalized = re.sub(r"\s+", " ", str(query or "").strip())
    normalized = URL_PATTERN.sub("", normalized).strip()
    if not normalized:
        normalized = str(query or "").strip() or "latest information"
    return WEB_SEARCH_ENDPOINT.format(query=quote_plus(normalized[:240]))


def _is_file_read_tool(tool: Dict[str, Any]) -> bool:
    tool_name = str(tool.get("name", "")).strip().lower()
    description = str(tool.get("description", "") or "").strip().lower()
    return _tool_has_path_like_argument(tool) and (
        tool_name in {"read_file", "read_text_file"}
        or ("read" in tool_name and "file" in tool_name)
        or "read the complete contents of a file" in description
        or "file system as text" in description
    )


def _is_file_info_tool(tool: Dict[str, Any]) -> bool:
    tool_name = str(tool.get("name", "")).strip().lower()
    return _tool_has_path_like_argument(tool) and (
        tool_name in {"get_file_info", "stat_file", "file_info"}
        or ("file" in tool_name and ("info" in tool_name or "stat" in tool_name or "metadata" in tool_name))
    )


def _is_file_listing_tool(tool: Dict[str, Any]) -> bool:
    tool_name = str(tool.get("name", "")).strip().lower()
    return _tool_has_path_like_argument(tool) and (
        tool_name in {"list_directory", "directory_tree", "list_directory_with_sizes"}
        or "list_directory" in tool_name
        or "directory_tree" in tool_name
    )


def _is_file_search_tool(tool: Dict[str, Any]) -> bool:
    tool_name = str(tool.get("name", "")).strip().lower()
    return _tool_has_path_like_argument(tool) and (
        tool_name in {"search_files", "find_files"}
        or ("search" in tool_name and "file" in tool_name)
        or ("find" in tool_name and "file" in tool_name)
    )


def _is_file_allowed_roots_tool(tool: Dict[str, Any]) -> bool:
    return str(tool.get("name", "")).strip().lower() in {"list_allowed_directories", "allowed_directories"}


def _choose_tool_instance_by_name(
    candidate_tools: List[Dict[str, Any]],
    tool_name: str,
    *,
    workspace_root: str = "",
) -> Optional[Dict[str, Any]]:
    normalized_tool_name = str(tool_name or "").strip()
    if not normalized_tool_name:
        return None

    matches = [
        tool
        for tool in candidate_tools
        if str(tool.get("name", "")).strip() == normalized_tool_name
    ]
    if not matches:
        return None

    if str(workspace_root or "").strip():
        preferred_workspace_match = next(
            (
                tool
                for tool in matches
                if str(tool.get("server", "")).strip().lower() != "filesystem"
            ),
            None,
        )
        if preferred_workspace_match is not None:
            return preferred_workspace_match

    return matches[0]


def _prefer_tool_candidate(
    candidate_tools: List[Dict[str, Any]],
    predicate,
    *,
    workspace_root: str = "",
) -> Optional[Dict[str, Any]]:
    matches = [tool for tool in candidate_tools if predicate(tool)]
    if not matches:
        return None

    if str(workspace_root or "").strip():
        preferred_workspace_match = next(
            (
                tool
                for tool in matches
                if str(tool.get("server", "")).strip().lower() != "filesystem"
            ),
            None,
        )
        if preferred_workspace_match is not None:
            return preferred_workspace_match

    return matches[0]


def _infer_tool_arguments_from_context(
    *,
    tool_name: str,
    server_name: str,
    arguments: Dict[str, Any],
    content: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
    active_mcp_manager: Optional[Any] = None,
    workspace_root: str = "",
    web_search_enabled: bool = False,
) -> tuple[Dict[str, Any], List[str]]:
    """Fill obvious MCP arguments from user text and uploaded attachment metadata."""
    effective_mcp_manager = active_mcp_manager or mcp_manager
    if not effective_mcp_manager:
        return dict(arguments or {}), []

    candidates = [
        tool
        for tool in effective_mcp_manager.get_all_tools()
        if tool.get("name") == tool_name and (not server_name or tool.get("server") == server_name)
    ]
    if not candidates:
        return dict(arguments or {}), []

    tool = candidates[0]
    schema = tool.get("input_schema") or {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        return dict(arguments or {}), []

    next_args = dict(arguments or {})
    inferred_fields: List[str] = []
    attachment_list = attachments if isinstance(attachments, list) else []
    first_attachment = attachment_list[0] if attachment_list and isinstance(attachment_list[0], dict) else {}
    normalized_server_name = str(server_name or "").strip().lower()
    uploaded_attachment_path = _get_uploaded_attachment_filesystem_path(first_attachment, workspace_root=workspace_root)
    uploaded_image_attachment = _get_uploaded_image_attachment(attachment_list)
    uploaded_image_path = _get_uploaded_image_path(attachment_list, workspace_root=workspace_root)

    for key, property_schema in properties.items():
        existing = next_args.get(key)
        if isinstance(property_schema, dict):
            schema_type = (
                effective_mcp_manager._resolve_schema_type(property_schema)
                if effective_mcp_manager and hasattr(effective_mcp_manager, "_resolve_schema_type")
                else str(property_schema.get("type", ""))
            )
            if str(schema_type).strip().lower() not in {"", "string"}:
                continue
        key_text = str(key)
        if not (
            _is_likely_path_argument(key_text, property_schema)
            or _is_likely_image_argument(key_text, property_schema)
            or _is_likely_task_text_argument(key_text, property_schema)
        ):
            continue

        lower_key = key_text.lower()
        schema_description = str(property_schema.get("description", "") if isinstance(property_schema, dict) else "").lower()
        prefer_url = lower_key in {"url", "uri"} or "url" in schema_description
        prefer_image = _is_likely_image_argument(key_text, property_schema)
        prefer_task_text = _is_likely_task_text_argument(key_text, property_schema)

        if existing is not None and (not isinstance(existing, str) or existing.strip()):
            if isinstance(existing, str) and not prefer_url and _is_likely_path_argument(key_text, property_schema):
                resolved_existing = _resolve_workspace_relative_path(existing, workspace_root=workspace_root)
                if resolved_existing and resolved_existing != existing:
                    next_args[key_text] = resolved_existing
                    inferred_fields.append(key_text)
                    continue
            if (
                uploaded_image_path
                and prefer_image
                and not prefer_url
                and not _is_filesystem_path_allowed(str(existing), workspace_root=workspace_root)
            ):
                next_args[key_text] = uploaded_image_path
                inferred_fields.append(key_text)
                continue
            if _should_prefer_uploaded_attachment_path(
                server_name=normalized_server_name,
                key=lower_key,
                prefer_url=prefer_url,
                candidate_value=existing,
                uploaded_attachment_path=uploaded_attachment_path,
            ):
                next_args[key_text] = uploaded_attachment_path
                inferred_fields.append(key_text)
            continue

        if web_search_enabled and prefer_url and _is_fetch_like_tool(tool):
            search_url = _build_web_search_url(content)
            if search_url:
                next_args[key_text] = search_url
                inferred_fields.append(key_text)
                continue

        if prefer_task_text:
            inferred_text = str(content or "").strip()
            if inferred_text:
                next_args[key_text] = inferred_text
                inferred_fields.append(key_text)
            continue

        inferred_value = _extract_path_like_text(content, prefer_url=prefer_url, workspace_root=workspace_root)

        if uploaded_image_path and prefer_image and not prefer_url:
            inferred_value = uploaded_image_path
        elif uploaded_image_attachment and prefer_url and uploaded_image_attachment.get("url") and prefer_image:
            inferred_value = str(uploaded_image_attachment.get("url"))

        if _should_prefer_uploaded_attachment_path(
            server_name=normalized_server_name,
            key=lower_key,
            prefer_url=prefer_url,
            candidate_value=inferred_value,
            uploaded_attachment_path=uploaded_attachment_path,
        ):
            inferred_value = uploaded_attachment_path

        if not inferred_value and first_attachment:
            if prefer_url and first_attachment.get("url"):
                inferred_value = str(first_attachment.get("url"))
            elif "filename" in lower_key:
                inferred_value = str(first_attachment.get("original_filename") or first_attachment.get("filename") or "")
            else:
                inferred_value = str(
                    first_attachment.get("file_path")
                    or first_attachment.get("path")
                    or first_attachment.get("url")
                    or first_attachment.get("filename")
                    or ""
                )

        if inferred_value:
            next_args[key_text] = inferred_value
            inferred_fields.append(key_text)

    # Generic schema-driven fallback for text/query style inputs. This keeps
    # newly added MCP tools usable without bespoke registration code.
    normalized_tool_name = str(tool_name or "").strip().lower()
    for key, property_schema in properties.items():
        if key in next_args and str(next_args.get(key) or "").strip():
            continue
        key_text = str(key or "").strip()
        lower_key = key_text.lower()
        if not key_text:
            continue
        schema_type = ""
        if isinstance(property_schema, dict):
            schema_type = (
                effective_mcp_manager._resolve_schema_type(property_schema)
                if effective_mcp_manager and hasattr(effective_mcp_manager, "_resolve_schema_type")
                else str(property_schema.get("type", ""))
            )
        if str(schema_type).strip().lower() != "string":
            continue
        if lower_key in {"text", "input", "query", "prompt", "instruction", "message", "body"}:
            inferred_text = str(content or "").strip()
            if inferred_text:
                next_args[key_text] = inferred_text
                if key_text not in inferred_fields:
                    inferred_fields.append(key_text)

    if effective_mcp_manager and hasattr(effective_mcp_manager, "normalize_tool_arguments"):
        try:
            next_args = effective_mcp_manager.normalize_tool_arguments(tool_name, next_args, server_name)
        except Exception as exc:
            logger.warning(f"tool argument normalization failed for {tool_name}: {exc}")

    normalized_query = str(content or "").strip().lower()
    if _is_file_read_tool(tool):
        wants_tail_focus = any(
            token in normalized_query
            for token in {
                "final_marker",
                "marker",
                "last line",
                "tail",
                "end of file",
                "最后一行",
                "末尾",
                "结尾",
                "标记",
            }
        )
        wants_precise_excerpt = any(
            token in normalized_query
            for token in {
                "exact",
                "exact line",
                "which line",
                "line is",
                "哪一行",
                "精确",
                "原文",
            }
        )
        if wants_tail_focus and "tail" not in next_args:
            next_args["tail"] = 40
            if "tail" not in inferred_fields:
                inferred_fields.append("tail")
        elif wants_precise_excerpt and "head" not in next_args and "tail" not in next_args:
            next_args["head"] = 80
            if "head" not in inferred_fields:
                inferred_fields.append("head")

    return next_args, inferred_fields


def _normalize_tool_arguments_runtime(
    tool_name: str,
    server_name: str,
    arguments: Optional[Dict[str, Any]],
    active_mcp_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    effective_mcp_manager = active_mcp_manager or mcp_manager
    normalized = dict(arguments or {})
    if effective_mcp_manager and hasattr(effective_mcp_manager, "normalize_tool_arguments"):
        try:
            normalized = effective_mcp_manager.normalize_tool_arguments(tool_name, normalized, server_name)
        except Exception as exc:
            logger.warning(f"runtime argument normalization failed for {tool_name}: {exc}")
    return normalized


mcp_harness_engine = MCPHarnessExecutionEngine(
    infer_tool_arguments_from_context=_infer_tool_arguments_from_context,
    normalize_tool_arguments_runtime=_normalize_tool_arguments_runtime,
    path_allowed_fn=_is_filesystem_path_allowed,
)


mcp_onboarding_service = MCPToolOnboardingService(
    project_root=project_root,
    get_default_manager=lambda: mcp_manager,
    safe_workspace_root=safe_workspace_root,
    infer_tool_arguments_from_context=_infer_tool_arguments_from_context,
    normalize_tool_arguments_runtime=_normalize_tool_arguments_runtime,
    is_auto_tool_allowed=is_auto_tool_allowed,
    arguments_ready_for_auto_execution=arguments_ready_for_auto_execution,
    tool_key=tool_key,
    is_fetch_like_tool=_is_fetch_like_tool,
    is_file_allowed_roots_tool=_is_file_allowed_roots_tool,
    tool_has_path_like_argument=_tool_has_path_like_argument,
    is_file_listing_tool=_is_file_listing_tool,
    is_file_info_tool=_is_file_info_tool,
    is_file_read_tool=_is_file_read_tool,
    is_file_search_tool=_is_file_search_tool,
)


def _has_non_image_attachment(attachments: Any) -> bool:
    if not isinstance(attachments, list):
        return False
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        mime_type = str(attachment.get("mime_type") or attachment.get("content_type") or "").strip().lower()
        if bool(attachment.get("is_image")) or mime_type.startswith("image/"):
            continue
        return True
    return False


def _query_requests_attachment_grounding(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not normalized:
        return False

    has_reference_hint = any(hint in normalized for hint in AUTO_TOOL_ATTACHMENT_REFERENCE_HINTS)
    has_action_hint = any(hint in normalized for hint in AUTO_TOOL_ATTACHMENT_ACTION_HINTS)
    has_contextual_reference = any(hint in normalized for hint in AUTO_TOOL_CONTEXTUAL_REFERENCE_HINTS)

    return bool(has_action_hint and (has_reference_hint or has_contextual_reference))


def _should_attempt_auto_tool(
    *,
    query: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    attachment_plan: Optional[Dict[str, Any]] = None,
    workspace_root: str = "",
    web_search_enabled: bool = False,
) -> bool:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return False

    if web_search_enabled:
        return True

    explicit_url = _extract_path_like_text(normalized_query, prefer_url=True, workspace_root=workspace_root)
    if explicit_url and URL_PATTERN.match(explicit_url):
        return True

    explicit_path = _extract_path_like_text(normalized_query, prefer_url=False, workspace_root=workspace_root)
    if explicit_path and not URL_PATTERN.match(explicit_path):
        return True

    if _attachment_plan_has_role(attachment_plan, "tool_grounding") and _query_requests_attachment_grounding(normalized_query):
        return True

    if _has_non_image_attachment(attachments) and _query_requests_attachment_grounding(normalized_query):
        return True

    if _has_image_attachment(attachments):
        lowered_query = normalized_query.lower()
        if any(hint in lowered_query for hint in AUTO_TOOL_IMAGE_ACTION_HINTS):
            return True

    return False


def _requires_grounded_tool_result(
    *,
    query: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    attachment_plan: Optional[Dict[str, Any]] = None,
    model_id: str = "",
    image_data: Optional[str] = None,
    image_data_list: Optional[List[str]] = None,
    workspace_root: str = "",
) -> bool:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return False
    if _should_suppress_tools_for_multimodal_image_request(
        query=normalized_query,
        model_id=model_id,
        attachments=attachments,
        attachment_plan=attachment_plan,
        image_data=image_data,
        image_data_list=image_data_list,
    ):
        return False
    if (
        _is_multimodal_model(model_id)
        and (image_data or image_data_list or _attachment_plan_has_role(attachment_plan, "visual_model") or _has_image_attachment(attachments))
        and not _has_non_image_attachment(attachments)
    ):
        return False
    return _should_attempt_auto_tool(
        query=normalized_query,
        attachments=attachments,
        attachment_plan=attachment_plan,
        workspace_root=workspace_root,
    )


def _should_suppress_tools_for_multimodal_image_request(
    *,
    query: str,
    model_id: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    attachment_plan: Optional[Dict[str, Any]] = None,
    image_data: Optional[str] = None,
    image_data_list: Optional[List[str]] = None,
    workspace_root: str = "",
) -> bool:
    attachment_list = attachments if isinstance(attachments, list) else []
    has_visual_input = bool(
        image_data
        or image_data_list
        or _attachment_plan_has_role(attachment_plan, "visual_model")
        or _has_image_attachment(attachment_list)
    )
    if not has_visual_input:
        return False
    if not _is_multimodal_model(model_id):
        return False
    if _has_non_image_attachment(attachment_list):
        return False
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return True
    if normalized_query.startswith("@"):
        return False
    explicit_url = _extract_path_like_text(normalized_query, prefer_url=True, workspace_root=workspace_root)
    if explicit_url and URL_PATTERN.match(explicit_url):
        return False
    explicit_path = _extract_path_like_text(normalized_query, prefer_url=False, workspace_root=workspace_root)
    if explicit_path and not URL_PATTERN.match(explicit_path):
        return False
    return True


def _tool_lookup_by_key(tool_key: str) -> Optional[Dict[str, Any]]:
    normalized_key = str(tool_key or "").strip().lower()
    if not normalized_key or not mcp_manager:
        return None
    for tool in mcp_manager.get_all_tools():
        server = str(tool.get("server", "")).strip().lower()
        name = str(tool.get("name", "")).strip().lower()
        if f"{server}.{name}" == normalized_key:
            return tool
    return None


def _normalize_tool_policy_names(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {
        str(item).strip().lower()
        for item in values
        if str(item).strip()
    }


def _filter_tools_by_workspace_agent_profile(
    tools: List[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not profile:
        return tools
    allowed_servers = _normalize_tool_policy_names(profile.get("allowMCPs"))
    if not allowed_servers:
        return tools

    filtered: List[Dict[str, Any]] = []
    for tool in tools:
        server_name = str(tool.get("server", "")).strip().lower()
        if allowed_servers and server_name not in allowed_servers:
            continue
        filtered.append(tool)
    return filtered


def _merge_workspace_agent_profile_with_session_overrides(
    profile: Optional[Dict[str, Any]],
    workspace_context_config: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    base_profile: Dict[str, Any] = dict(profile or {})
    config = workspace_context_config if isinstance(workspace_context_config, dict) else {}

    session_allow_mcps = _normalize_tool_policy_names(config.get("session_allow_mcps"))

    if not base_profile and not session_allow_mcps:
        return None

    allow_values = _normalize_tool_policy_names(base_profile.get("allowMCPs"))
    allow_values.update(session_allow_mcps)

    merged_profile = dict(base_profile)
    merged_profile["allowMCPs"] = sorted(allow_values)
    return merged_profile


def _resolve_skill_runtime_for_request(
    *,
    requested_skill_ids: Optional[List[str]],
    query: str,
    workspace_context_config: Optional[Dict[str, Any]],
    workspace_agent_profile: Optional[Dict[str, Any]],
    model_id: str,
    available_tools: Optional[List[Dict[str, Any]]] = None,
    scopes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    workspace_config = workspace_context_config if isinstance(workspace_context_config, dict) else {}
    resolution = skill_runtime_resolver.resolve(
        requested_skill_ids=requested_skill_ids,
        query=query,
        workspace_root=str(workspace_config.get("workspace_root", "") or ""),
        scopes=scopes or ["chat"],
        model_id=model_id,
        available_tools=available_tools or [],
        current_allowed_mcp_servers=(workspace_agent_profile or {}).get("allowMCPs", []),
    )
    return resolution.to_payload()


def _merge_workspace_profile_with_skill_runtime(
    profile: Optional[Dict[str, Any]],
    skill_runtime: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    base_profile: Dict[str, Any] = dict(profile or {})
    runtime_payload = skill_runtime if isinstance(skill_runtime, dict) else {}
    runtime_servers = _normalize_tool_policy_names(
        ((runtime_payload.get("capability_overlay") or {}) if isinstance(runtime_payload.get("capability_overlay"), dict) else {}).get("allowed_mcp_servers")
    )
    if not base_profile and not runtime_servers:
        return None

    allow_values = _normalize_tool_policy_names(base_profile.get("allowMCPs"))
    allow_values.update(runtime_servers)
    merged_profile = dict(base_profile)
    merged_profile["allowMCPs"] = sorted(allow_values)
    if runtime_payload:
        merged_profile["skill_runtime"] = runtime_payload
        if ((runtime_payload.get("capability_overlay") or {}) if isinstance(runtime_payload.get("capability_overlay"), dict) else {}).get("requires_confirmation"):
            merged_profile["isConfirmCallTool"] = True
    return merged_profile


def _select_auto_tool_candidate(
    *,
    client_id: str,
    query: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    allowed_tools: Optional[List[Dict[str, Any]]] = None,
    workspace_root: str = "",
    active_mcp_manager: Optional[Any] = None,
    web_search_enabled: bool = False,
) -> Optional[Dict[str, Any]]:
    tools = allowed_tools if isinstance(allowed_tools, list) else (mcp_manager.get_all_tools() if mcp_manager else [])
    if not tools:
        return None

    effective_mcp_manager = active_mcp_manager or mcp_manager
    auto_tool_routing_state = get_runtime_auto_tool_routing_state()
    fallback_enabled = bool(auto_tool_routing_state.get("fallback_enabled", True))
    candidate_tools = filter_auto_tool_candidates(
        tools,
        resolve_schema_type=(
            effective_mcp_manager._resolve_schema_type
            if effective_mcp_manager and hasattr(effective_mcp_manager, "_resolve_schema_type")
            else None
        ),
    )
    if not candidate_tools:
        return None

    attachment_list = attachments if isinstance(attachments, list) else []
    first_attachment = attachment_list[0] if attachment_list and isinstance(attachment_list[0], dict) else {}
    uploaded_attachment_path = _get_uploaded_attachment_filesystem_path(first_attachment, workspace_root=workspace_root)
    if uploaded_attachment_path:
        filtered_tools: list[Dict[str, Any]] = []
        for tool in candidate_tools:
            tool_name = str(tool.get("name", "")).strip().lower()
            if not _tool_has_path_like_argument(tool):
                filtered_tools.append(tool)
                continue
            if _is_file_read_tool(tool) or _is_file_info_tool(tool):
                filtered_tools.append(tool)
                continue
            if tool_name == "read_multiple_files":
                continue
            filtered_tools.append(tool)
        if filtered_tools:
            candidate_tools = filtered_tools

    candidate_tool_names = [
        str(tool.get("name", "")).strip()
        for tool in candidate_tools
        if str(tool.get("name", "")).strip()
    ]
    attachment_list = attachments if isinstance(attachments, list) else []

    def _tool_is_ready_for_auto_execution(tool: Dict[str, Any]) -> bool:
        tool_name_value = str(tool.get("name", "")).strip()
        server_name_value = str(tool.get("server", "")).strip()
        inferred_arguments, _ = _infer_tool_arguments_from_context(
            tool_name=tool_name_value,
            server_name=server_name_value,
            arguments={},
            content=query,
            attachments=attachment_list,
            active_mcp_manager=effective_mcp_manager,
            workspace_root=workspace_root,
        )
        inferred_arguments = _normalize_tool_arguments_runtime(
            tool_name_value,
            server_name_value,
            inferred_arguments,
            active_mcp_manager=effective_mcp_manager,
        )
        return arguments_ready_for_auto_execution(
            tool,
            inferred_arguments,
            content=query,
            resolve_schema_type=(
                effective_mcp_manager._resolve_schema_type
                if effective_mcp_manager and hasattr(effective_mcp_manager, "_resolve_schema_type")
                else None
            ),
        )

    def _build_fallback_candidate(
        *,
        tool: Dict[str, Any],
        reason: str,
        router_type: str,
    ) -> Dict[str, Any]:
        fallback_tool_name = str(tool.get("name", "")).strip()
        fallback_server_name = str(tool.get("server", "")).strip()
        fallback_plan = memory_control_plane.build_routed_tool_execution_plan(
            client_id=client_id,
            query=query,
            candidate_tool_names=[fallback_tool_name],
            tool_catalog=[tool],
            arguments={},
            context_engine=context_engine,
            tem=tem,
            server_name=fallback_server_name,
            dry_run=False,
        )
        fallback_plan["phase"] = "policy_routed_tool_call"
        fallback_plan["tool_name"] = fallback_tool_name
        fallback_plan["server_name"] = fallback_server_name
        fallback_plan["query"] = query
        routing = fallback_plan.setdefault("routing", {})
        routing["selected_tools"] = [fallback_tool_name]
        routing["relevant_tools"] = [fallback_tool_name]
        routing["context_tool_names"] = [fallback_tool_name]
        routing["scores"] = [
            {
                "tool_name": fallback_tool_name,
                "final_score": 1.0,
                "reason": reason,
            }
        ]
        routing["reason"] = reason
        routing["router_type"] = router_type
        routing["evaluation_ready"] = True
        execution_policy = fallback_plan.setdefault("execution_policy", {})
        execution_policy["candidate_tool_count"] = 1
        execution_policy["recommended_action"] = execution_policy.get("recommended_action", "proceed")
        execution_policy["fallback_reason"] = reason
        return {
            "tool": tool,
            "memory_plan": fallback_plan,
            "score": {"tool_name": fallback_tool_name, "final_score": 1.0},
            "reason": reason,
            "candidate_tools": [tool],
            "candidate_tool_names": [fallback_tool_name],
        }

    explicit_url = _extract_path_like_text(query, prefer_url=True, workspace_root=workspace_root)
    if fallback_enabled and web_search_enabled:
        preferred_fetch_tool = _prefer_tool_candidate(
            candidate_tools,
            _is_fetch_like_tool,
            workspace_root=workspace_root,
        )
        if preferred_fetch_tool:
            return _build_fallback_candidate(
                tool=preferred_fetch_tool,
                reason="web_search_requested_fallback",
                router_type="web_search_fallback_router",
            )

    if fallback_enabled and explicit_url and URL_PATTERN.match(explicit_url):
        preferred_fetch_tool = _prefer_tool_candidate(
            candidate_tools,
            _is_fetch_like_tool,
            workspace_root=workspace_root,
        )
        if preferred_fetch_tool:
            return _build_fallback_candidate(
                tool=preferred_fetch_tool,
                reason="explicit_url_grounding_fallback",
                router_type="url_grounded_fallback_router",
            )

    if fallback_enabled and uploaded_attachment_path and _query_requests_attachment_grounding(query):
        preferred_attachment_tool = _prefer_tool_candidate(
            candidate_tools,
            _is_file_read_tool,
            workspace_root=workspace_root,
        )
        if preferred_attachment_tool:
            return _build_fallback_candidate(
                tool=preferred_attachment_tool,
                reason="uploaded_attachment_grounding_fallback",
                router_type="attachment_grounded_fallback_router",
            )

    if fallback_enabled and _has_image_attachment(attachments):
        normalized_query = str(query or "").strip().lower()
        if any(hint in normalized_query for hint in AUTO_TOOL_IMAGE_ACTION_HINTS):
            preferred_cdar_tool = _prefer_tool_candidate(
                candidate_tools,
                lambda tool: str(tool.get("server", "")).strip() == "cdar_mcp"
                and str(tool.get("name", "")).strip() == "cdar_compositional_decomposed_adaptive_reasoning",
                workspace_root=workspace_root,
            )
            if preferred_cdar_tool and _tool_is_ready_for_auto_execution(preferred_cdar_tool):
                return _build_fallback_candidate(
                    tool=preferred_cdar_tool,
                    reason="uploaded_image_grounding_fallback",
                    router_type="image_grounded_fallback_router",
                )

    memory_plan = memory_control_plane.build_routed_tool_execution_plan(
        client_id=client_id,
        query=query,
        candidate_tool_names=candidate_tool_names,
        tool_catalog=candidate_tools,
        arguments={},
        context_engine=context_engine,
        tem=tem,
        dry_run=True,
    )
    routing = memory_plan.get("routing", {})
    scores = routing.get("scores", []) if isinstance(routing, dict) else []
    if scores:
        for score in scores:
            tool_name = str(score.get("tool_name", "")).strip()
            matched_tool = _choose_tool_instance_by_name(
                candidate_tools,
                tool_name,
                workspace_root=workspace_root,
            )
            if not matched_tool:
                continue
            final_score = float(score.get("final_score", 0.0) or 0.0)
            if final_score < AUTO_TOOL_MIN_SCORE:
                continue
            if not _tool_is_ready_for_auto_execution(matched_tool):
                continue
            return {
                "tool": matched_tool,
                "memory_plan": memory_plan,
                "score": score,
                "reason": "memory_plane_auto_route",
                "candidate_tools": candidate_tools,
                "candidate_tool_names": candidate_tool_names,
            }

    if not fallback_enabled:
        return None

    extracted_path = _extract_path_like_text(query, prefer_url=False, workspace_root=workspace_root)
    if extracted_path and not URL_PATTERN.match(extracted_path):
        preferred_read_tool = _prefer_tool_candidate(
            candidate_tools,
            _is_file_read_tool,
            workspace_root=workspace_root,
        )
        if preferred_read_tool:
            return _build_fallback_candidate(
                tool=preferred_read_tool,
                reason="explicit_path_grounding_fallback",
                router_type="path_grounded_fallback_router",
            )

    return None


def _should_bypass_model_tool_loop_for_candidate(candidate: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(candidate, dict):
        return False
    reason = str(candidate.get("reason", "") or "").strip().lower()
    if not reason:
        return False
    if reason == "memory_plane_auto_route":
        return False
    return reason in {
        "explicit_url_grounding_fallback",
        "uploaded_attachment_grounding_fallback",
        "uploaded_image_grounding_fallback",
        "explicit_path_grounding_fallback",
        "web_search_requested_fallback",
    }


async def _execute_tool_call_internal(
    *,
    client_id: str,
    request_id: Optional[str],
    tool_name: str,
    server_name: str,
    arguments: Dict[str, Any],
    original_user_content: str,
    model_id: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    skill_ids: Optional[List[str]] = None,
    custom_system_prompt: str = "",
    workspace_context_config: Optional[Dict[str, Any]] = None,
    active_mcp_manager: Optional[Any] = None,
    policy_confirmed: bool = False,
    memory_plan_override: Optional[dict[str, Any]] = None,
    auto_tool_call: bool = False,
    auto_tool_reason: str = "",
    auto_tool_confidence: Optional[float] = None,
    allow_recipe_preflight_block: bool = False,
    include_followup_response: bool = True,
) -> Dict[str, Any]:
    effective_mcp_manager = active_mcp_manager or mcp_manager
    workspace_root = str(workspace_context_config.get("workspace_root", "") or "") if isinstance(workspace_context_config, dict) else ""
    harness_prepared = mcp_harness_engine.prepare_tool_call(
        manager=effective_mcp_manager,
        tool_name=tool_name or "",
        server_name=server_name,
        arguments=arguments,
        content=original_user_content,
        attachments=attachments if isinstance(attachments, list) else [],
        workspace_root=workspace_root,
        request_id=request_id,
        source="chat_auto_tool" if auto_tool_call else "chat_manual_tool",
    )
    if not harness_prepared.get("ok"):
        blocked_payload = {
            "type": "tool_blocked",
            "tool_name": tool_name,
            "reason": harness_prepared.get("error", "Harness preparation failed."),
            "suggestion": "Check whether the MCP server is online and the tool is visible in the current workspace/runtime.",
            "block_source": "harness_prepare",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "harness": {
                "action": harness_prepared.get("action", {}),
                "capability_snapshot": harness_prepared.get("capability_snapshot", {}),
            },
        }
        await manager.send_personal_message(blocked_payload, client_id)
        return {
            "final_payload": blocked_payload,
            "delivery_status": "blocked",
            "delivery_message": blocked_payload["reason"],
            "success": False,
            "latency_ms": 0.0,
        }

    harness_contract = harness_prepared.get("contract", {})
    harness_compiler = harness_prepared.get("compiler", {})
    harness_precheck = harness_prepared.get("precheck", {})
    resolved_arguments = dict(harness_compiler.get("arguments", {}) or {})
    inferred_fields = list(harness_compiler.get("inferred_fields", []) or [])
    harness_action = harness_prepared.get("action", {})
    harness_capability_snapshot = harness_prepared.get("capability_snapshot", {})
    action_id = str(harness_action.get("action_id") or f"mcp-action-{uuid.uuid4().hex[:12]}")
    resource_refs = build_resource_references(
        content=original_user_content,
        attachments=attachments if isinstance(attachments, list) else [],
        workspace_root=workspace_root,
        project_root=project_root,
    )
    await _send_action_event(
        client_id,
        request_id=request_id,
        action_id=action_id,
        stage="prepared",
        status="running",
        title="Preparing tool call",
        summary=f"{server_name}.{tool_name}".strip("."),
        target={"server": server_name, "tool": tool_name},
        resource_refs=resource_refs,
        details={
            "target": {"server": server_name, "tool": tool_name},
            "contract": harness_contract,
            "compiler": harness_compiler,
        },
    )
    if harness_precheck.get("blocking"):
        await _send_action_event(
            client_id,
            request_id=request_id,
            action_id=action_id,
            stage="precheck",
            status="blocked",
            title="Tool precheck blocked",
            summary=harness_precheck.get("reason") or "Harness precheck blocked the tool call.",
            target={"server": server_name, "tool": tool_name},
            resource_refs=resource_refs,
            details={
                "target": {"server": server_name, "tool": tool_name},
                "precheck": harness_precheck,
            },
        )
        blocked_payload = {
            "type": "tool_blocked",
            "tool_name": tool_name,
            "reason": harness_precheck.get("reason") or "Harness precheck blocked the tool call.",
            "suggestion": harness_precheck.get("suggestion") or "Adjust the request or attachment grounding and retry.",
            "block_source": "harness_precheck",
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "harness": {
                "action": harness_action,
                "contract": harness_contract,
                "compiler": harness_compiler,
                "precheck": harness_precheck,
                "capability_snapshot": harness_capability_snapshot,
            },
            "resource_refs": resource_refs,
        }
        await manager.send_personal_message(blocked_payload, client_id)
        return {
            "final_payload": blocked_payload,
            "delivery_status": "blocked",
            "delivery_message": blocked_payload["reason"],
            "success": False,
            "latency_ms": 0.0,
        }

    skill_runtime = _resolve_skill_runtime_for_request(
        requested_skill_ids=skill_ids,
        query=original_user_content or f"{server_name}.{tool_name}",
        workspace_context_config=workspace_context_config,
        workspace_agent_profile=load_workspace_agent_runtime_profile(
            workspace_root=workspace_root,
            agent_name=str((workspace_context_config or {}).get("agent_name", "") or ""),
        ),
        model_id=model_id,
        available_tools=(effective_mcp_manager.get_all_tools() if effective_mcp_manager else []),
        scopes=["tool_call", "tool_followup", "tool_routing"],
    )

    memory_plan = memory_plan_override or memory_control_plane.build_tool_memory_plan(
        client_id=client_id,
        tool_name=tool_name,
        arguments=resolved_arguments,
        server_name=server_name,
        task_description=original_user_content or tool_name,
        tem=tem,
        allow_recipe_preflight_block=allow_recipe_preflight_block,
    )
    recipe_preflight = memory_plan.get("execution_policy", {}).get("recipe_preflight", {})
    policy_block = evaluate_runtime_tool_policy(
        server_name=server_name,
        tool_name=tool_name,
        arguments=resolved_arguments,
        policy_confirmed=policy_confirmed,
    )
    if policy_block:
        blocked_payload = {
            "type": "tool_blocked",
            "tool_name": tool_name,
            "reason": policy_block["reason"],
            "suggestion": policy_block["suggestion"],
            "block_source": policy_block.get("block_source", "policy"),
            "policy_action": policy_block.get("policy_action"),
            "policy_reason": policy_block.get("policy_reason"),
            "recipe_preflight": recipe_preflight,
            "memory_plane": memory_plan,
            "run_trace": build_tool_run_trace(
                request_id=request_id,
                server_name=server_name,
                tool_name=tool_name,
                arguments=resolved_arguments,
                memory_plan=memory_plan,
                policy_block=policy_block,
                blocked=True,
                success=False,
            ),
            "inferred_arguments": inferred_fields,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
        }
        await manager.send_personal_message(blocked_payload, client_id)
        return {
            "final_payload": blocked_payload,
            "delivery_status": "blocked",
            "delivery_message": policy_block["reason"],
            "success": False,
            "latency_ms": 0.0,
        }

    block_info = tem.before_tool_call(
        tool_name,
        resolved_arguments,
        server_name,
        task_description=original_user_content or tool_name,
        enforce_recipe_preflight_block=False,
        enforce_guard_block=False,
    )
    if block_info:
        causal_trace = memory_control_plane.register_tool_outcome(
            selected_tool=tool_name,
            plan=memory_plan,
            success=False,
            blocked=True,
            guard_id=block_info.get("guard_id", ""),
            counterfactual=block_info.get("suggestion", ""),
            tem=tem,
        )
        blocked_payload = {
            "type": "tool_blocked",
            "tool_name": tool_name,
            "reason": block_info["reason"],
            "suggestion": block_info["suggestion"],
            "guard_id": block_info.get("guard_id", ""),
            "block_source": block_info.get("block_source", "guard"),
            "guard_evidence": block_info.get("guard_evidence"),
            "recipe_preflight": block_info.get("recipe_preflight", recipe_preflight),
            "memory_plane": memory_plan,
            "causal_trace": causal_trace,
            "run_trace": build_tool_run_trace(
                request_id=request_id,
                server_name=server_name,
                tool_name=tool_name,
                arguments=resolved_arguments,
                memory_plan=memory_plan,
                blocked=True,
                success=False,
            ),
            "inferred_arguments": inferred_fields,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
        }
        await manager.send_personal_message(blocked_payload, client_id)
        return {
            "final_payload": blocked_payload,
            "delivery_status": "blocked",
            "delivery_message": block_info["reason"],
            "success": False,
            "latency_ms": 0.0,
        }

    if original_user_content:
        _record_tool_user_message(client_id, original_user_content, attachments if isinstance(attachments, list) else [])

    await send_request_delivery(
        client_id,
        request_id,
        "processing",
        message=f"Running MCP tool {tool_name}",
        details={"server_name": server_name, "auto_tool_call": auto_tool_call},
    )
    await _send_action_event(
        client_id,
        request_id=request_id,
        action_id=action_id,
        stage="started",
        status="running",
        title="Calling MCP tool",
        summary=f"{server_name}.{tool_name}".strip("."),
        target={"server": server_name, "tool": tool_name},
        resource_refs=resource_refs,
        details={
            "target": {"server": server_name, "tool": tool_name},
            "arguments": resolved_arguments,
            "inferred_arguments": inferred_fields,
        },
    )
    t0 = time.time()
    result = await effective_mcp_manager.call_tool(tool_name, resolved_arguments, server_name) if effective_mcp_manager and hasattr(effective_mcp_manager, "call_tool") else {
        "success": False,
        "error": "MCP manager unavailable",
        "message": "Unable to execute tool",
    }
    result = _with_friendly_tool_error(result)
    latency_ms = round((time.time() - t0) * 1000, 1)
    if inferred_fields and isinstance(result, dict):
        result = {
            **result,
            "inferred_arguments": inferred_fields,
        }

    success = False
    error_type = ""
    error_message = ""
    if isinstance(result, dict):
        success = bool(result.get("success", False))
        if not success:
            error_type = result.get("error_type", type(result.get("error", "")).__name__)
            error_message = str(result.get("error", result.get("message", "")))
    harness_postcheck = mcp_harness_engine.finalize_tool_call(
        contract=harness_contract,
        result=result,
    )
    recovery_attempt: Optional[Dict[str, Any]] = None
    recovery_result: Optional[Dict[str, Any]] = None
    if not success:
        recovery_attempt = _build_recovery_attempt(
            tool_name=tool_name,
            server_name=server_name,
            resolved_arguments=resolved_arguments,
            original_user_content=original_user_content,
            attachments=attachments if isinstance(attachments, list) else [],
            workspace_root=workspace_root,
            result=result if isinstance(result, dict) else {},
        )
        if recovery_attempt:
            recovery_args = dict(recovery_attempt.get("arguments", {}) or {})
            await _send_action_event(
                client_id,
                request_id=request_id,
                action_id=action_id,
                stage="recovering",
                status="running",
                title="Recovering tool call",
                summary=str(recovery_attempt.get("reason") or "Retrying with repaired arguments."),
                target={"server": server_name, "tool": tool_name},
                resource_refs=resource_refs,
                details={
                    "target": {"server": server_name, "tool": tool_name},
                    "strategy": recovery_attempt.get("strategy"),
                    "arguments": recovery_args,
                },
            )
            t_recovery = time.time()
            recovery_raw = await effective_mcp_manager.call_tool(tool_name, recovery_args, server_name) if effective_mcp_manager and hasattr(effective_mcp_manager, "call_tool") else {
                "success": False,
                "error": "MCP manager unavailable during recovery",
            }
            recovery_result = _with_friendly_tool_error(recovery_raw)
            recovery_latency_ms = round((time.time() - t_recovery) * 1000, 1)
            recovery_success = bool(isinstance(recovery_result, dict) and recovery_result.get("success", False))
            await _send_action_event(
                client_id,
                request_id=request_id,
                action_id=action_id,
                stage="recovered" if recovery_success else "recovery_failed",
                status="success" if recovery_success else "failed",
                title="Recovery finished",
                summary="Recovery retry succeeded" if recovery_success else str((recovery_result or {}).get("error") or "Recovery retry failed"),
                target={"server": server_name, "tool": tool_name},
                resource_refs=resource_refs,
                details={
                    "target": {"server": server_name, "tool": tool_name},
                    "strategy": recovery_attempt.get("strategy"),
                    "latency_ms": recovery_latency_ms,
                    "result": recovery_result,
                },
            )
            if recovery_success:
                result = recovery_result
                resolved_arguments = recovery_args
                success = True
                error_type = ""
                error_message = ""
                latency_ms = round(latency_ms + recovery_latency_ms, 1)
                harness_compiler = {
                    **harness_compiler,
                    "recovered": True,
                    "recovery_strategy": recovery_attempt.get("strategy"),
                    "recovery_reason": recovery_attempt.get("reason"),
                }
                harness_postcheck = mcp_harness_engine.finalize_tool_call(
                    contract=harness_contract,
                    result=result,
                )
    await _send_action_event(
        client_id,
        request_id=request_id,
        action_id=action_id,
        stage="observed",
        status="success" if success else "failed",
        title="Tool observation received",
        summary=(
            "Tool call completed"
            if success
            else (error_message or "Tool call failed")
        ),
        target={"server": server_name, "tool": tool_name},
        resource_refs=resource_refs,
        details={
            "target": {"server": server_name, "tool": tool_name},
            "latency_ms": latency_ms,
            "postcheck": harness_postcheck,
            "recovery": {
                "attempted": bool(recovery_attempt),
                "strategy": recovery_attempt.get("strategy") if isinstance(recovery_attempt, dict) else "",
                "success": bool(success and recovery_attempt),
                "result": recovery_result,
            },
        },
    )

    tem_event = tem.after_tool_call(
        client_id=client_id,
        tool_name=tool_name,
        arguments=resolved_arguments,
        result=result,
        success=success,
        error_type=error_type,
        error_message=error_message,
        latency_ms=latency_ms,
        server_name=server_name,
        task_description=original_user_content or f"Tool call: {tool_name}",
    )
    causal_trace = memory_control_plane.register_tool_outcome(
        selected_tool=tool_name,
        plan=memory_plan,
        success=success,
        blocked=False,
        tem=tem,
    )

    context_engine.record_tool_result(client_id, tool_name, result)

    tool_result_payload = {
        "type": "tool_result",
        "tool_name": tool_name,
        "server_name": server_name,
        "arguments": resolved_arguments,
        "result": result,
        "tem_event": tem_event,
        "memory_plane": memory_plan,
        "causal_trace": causal_trace,
        "recipe_preflight": recipe_preflight,
        "skill_runtime": skill_runtime,
        "harness": {
            "action": harness_action,
            "contract": harness_contract,
            "compiler": harness_compiler,
            "precheck": harness_precheck,
            "postcheck": harness_postcheck,
            "recovery": {
                "attempted": bool(recovery_attempt),
                "strategy": recovery_attempt.get("strategy") if isinstance(recovery_attempt, dict) else "",
                "success": bool(success and recovery_attempt),
                "result": recovery_result,
            },
            "capability_snapshot": harness_capability_snapshot,
        },
        "resource_refs": resource_refs,
        "run_trace": build_tool_run_trace(
            request_id=request_id,
            server_name=server_name,
            tool_name=tool_name,
            arguments=resolved_arguments,
            memory_plan=memory_plan,
            latency_ms=latency_ms,
            success=success,
        ),
        "inferred_arguments": inferred_fields,
        "request_id": request_id,
        "timestamp": datetime.now().isoformat(),
    }
    await manager.send_personal_message(tool_result_payload, client_id)

    final_payload = tool_result_payload
    delivery_status = "completed" if success else "failed"
    delivery_message = "Tool execution finished" if success else (error_message or "Tool execution failed")

    if not include_followup_response:
        return {
            "final_payload": final_payload,
            "tool_result_payload": tool_result_payload,
            "delivery_status": delivery_status,
            "delivery_message": delivery_message,
            "success": success,
            "latency_ms": latency_ms,
        }

    try:
        followup_payload = await _generate_tool_followup_response(
            client_id=client_id,
            request_id=request_id,
            model_id=model_id,
            original_user_content=original_user_content,
            tool_name=tool_name,
            server_name=server_name,
            arguments=resolved_arguments,
            result=result,
            attachments=attachments if isinstance(attachments, list) else [],
            inferred_fields=inferred_fields,
            custom_system_prompt=custom_system_prompt,
            skill_ids=skill_ids,
            workspace_context_config=workspace_context_config,
            stream_to_client=True,
        )
        followup_payload["metadata"] = {
            **(
                followup_payload.get("metadata", {})
                if isinstance(followup_payload.get("metadata", {}), dict)
                else {}
            ),
            "tool_name": tool_name,
            "server_name": server_name,
            "tool_result_available": True,
            "tool_evidence": copy.deepcopy(tool_result_payload),
            "arguments": resolved_arguments,
            "result": result,
            "inferred_arguments": inferred_fields,
            "execution_time": latency_ms / 1000.0 if latency_ms is not None else None,
            "tools_used": [tool_key(server_name, tool_name)],
            "auto_tool_call": auto_tool_call,
            "auto_tool_reason": auto_tool_reason,
            "auto_tool_confidence": auto_tool_confidence,
        }
        followup_payload["tem_event"] = tem_event
        followup_payload["memory_plane"] = memory_plan
        followup_payload["causal_trace"] = causal_trace
        followup_payload["recipe_preflight"] = recipe_preflight
        followup_payload["run_trace"] = tool_result_payload.get("run_trace")
        followup_payload["execution_time"] = latency_ms / 1000.0 if latency_ms is not None else None
        followup_payload["tools_used"] = [tool_key(server_name, tool_name)]
        await manager.send_personal_message(followup_payload, client_id)
        final_payload = followup_payload
        delivery_message = "Tool execution finished and summarized by model" if success else "Tool failed, and the model returned an explanation"
    except Exception as followup_error:
        logger.warning(f"tool follow-up response generation failed: {followup_error}")
        final_payload = {
            "type": "response",
            "content": (
                f"Tool `{server_name}.{tool_name}` {'completed' if success else 'failed'}, "
                f"but the model summary step failed.\n\n"
                f"Tool status: {'success' if success else 'failed'}.\n"
                f"Next step: inspect the tool evidence block below and retry the response with an available model if needed.\n\n"
                f"Summary failure: {str(followup_error)}"
            ),
            "model_used": model_id,
            "model_name": _resolve_model_name(model_id or _resolve_runtime_default_model()),
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "tool_name": tool_name,
                "server_name": server_name,
                "tool_result_available": True,
                "tool_evidence": copy.deepcopy(tool_result_payload),
                "arguments": resolved_arguments,
                "result": result,
                "inferred_arguments": inferred_fields,
                "execution_time": latency_ms / 1000.0 if latency_ms is not None else None,
                "tools_used": [tool_key(server_name, tool_name)],
                "followup_error": str(followup_error),
                "followup_fallback": True,
                "auto_tool_call": auto_tool_call,
                "auto_tool_reason": auto_tool_reason,
                "auto_tool_confidence": auto_tool_confidence,
            },
            "tem_event": tem_event,
            "memory_plane": memory_plan,
            "causal_trace": causal_trace,
            "recipe_preflight": recipe_preflight,
            "run_trace": tool_result_payload.get("run_trace"),
            "execution_time": latency_ms / 1000.0 if latency_ms is not None else None,
            "tools_used": [tool_key(server_name, tool_name)],
        }
        await manager.send_personal_message(final_payload, client_id)
        delivery_message = (
            f"Tool executed, but model summary failed: {followup_error}"
            if success
            else f"Tool failed, and model explanation also failed: {followup_error}"
        )

    return {
        "final_payload": final_payload,
        "tool_result_payload": tool_result_payload,
        "delivery_status": delivery_status,
        "delivery_message": delivery_message,
        "success": success,
        "latency_ms": latency_ms,
    }


def _request_runtime_now() -> str:
    return request_runtime_service.now()


def _summarize_request_message(message: dict[str, Any]) -> dict[str, Any]:
    return request_runtime_service.summarize_request_message(message)


def _request_runtime_status_from_payload(payload: dict[str, Any]) -> str:
    return request_runtime_service.runtime_status_from_payload(payload)


def _delivery_status_from_runtime_status(runtime_status: str) -> str:
    return request_runtime_service.delivery_status_from_runtime_status(runtime_status)


def _delivery_message_for_replay(runtime_status: str) -> str:
    return request_runtime_service.delivery_message_for_replay(runtime_status)


def _build_interrupted_request_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return request_runtime_service.build_interrupted_request_payload(entry)


def _build_request_replay_payload(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    return request_runtime_service.build_request_replay_payload(payload, source=source)


def _trim_request_runtime_state() -> bool:
    return request_runtime_service.trim_state()


def _persist_request_runtime_journal() -> None:
    request_runtime_service.persist_journal()


def _remember_request_inflight(request_id: Optional[str], message: dict[str, Any], client_id: str) -> None:
    request_runtime_service.remember_inflight(request_id, message, client_id)


def _load_request_runtime_journal() -> None:
    request_runtime_service.load_journal()


def _remember_request_result(request_id: Optional[str], payload: dict[str, Any]) -> None:
    request_runtime_service.remember_result(request_id, payload)


def _ordered_deepcopy(data: OrderedDict | dict[str, Any]) -> OrderedDict:
    return request_runtime_service.ordered_deepcopy(data)


def _regression_sandbox_targets(include_uploads: bool) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = [
        {
            "name": "recipes_dir",
            "path": project_root / "artifacts" / "recipes",
            "kind": "dir",
        },
        {
            "name": "guards_dir",
            "path": project_root / "artifacts" / "guards",
            "kind": "dir",
        },
        {
            "name": "memory_dir",
            "path": project_root / "artifacts" / "memory",
            "kind": "dir",
        },
        {
            "name": "error_centroids",
            "path": project_root / "artifacts" / "error_centroids.json",
            "kind": "file",
        },
    ]
    if include_uploads:
        targets.append(
            {
                "name": "uploads_dir",
                "path": UPLOAD_DIR,
                "kind": "dir",
            }
        )
    return targets


def _snapshot_path_to_dir(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _remove_path_if_exists(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _capture_regression_runtime_snapshot() -> dict[str, Any]:
    request_runtime_snapshot = request_runtime_service.snapshot_state()
    return {
        "memory_plane": memory_control_plane.snapshot_runtime_state(context_engine, tem),
        "runtime_provider_overrides": copy.deepcopy(runtime_provider_overrides),
        "runtime_tool_policy": copy.deepcopy(runtime_tool_policy),
        "runtime_auto_tool_routing": copy.deepcopy(runtime_auto_tool_routing),
        **request_runtime_snapshot,
    }


def _restore_regression_runtime_snapshot(snapshot: dict[str, Any]) -> None:
    runtime_provider_overrides.clear()
    runtime_provider_overrides.update(copy.deepcopy(snapshot.get("runtime_provider_overrides", {})))

    runtime_tool_policy.clear()
    runtime_tool_policy.update(copy.deepcopy(snapshot.get("runtime_tool_policy", {})))

    runtime_auto_tool_routing.clear()
    runtime_auto_tool_routing.update(copy.deepcopy(snapshot.get("runtime_auto_tool_routing", {})))

    initialize_siliconflow()
    memory_control_plane.restore_runtime_state(
        copy.deepcopy(snapshot.get("memory_plane", {})),
        context_engine,
        tem,
    )
    request_runtime_service.restore_state(snapshot)


def _begin_regression_sandbox(label: str, include_uploads: bool) -> dict[str, Any]:
    sandbox_id = f"regression_{uuid.uuid4().hex[:12]}"
    snapshot_dir = REGRESSION_SANDBOX_ROOT / sandbox_id
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    manifest: list[dict[str, Any]] = []
    for target in _regression_sandbox_targets(include_uploads):
        source_path = Path(target["path"])
        snapshot_path = snapshot_dir / str(target["name"])
        existed = source_path.exists()
        entry = {
            "name": str(target["name"]),
            "path": str(source_path),
            "kind": str(target["kind"]),
            "existed": existed,
            "snapshot_path": str(snapshot_path),
        }
        if existed:
            _snapshot_path_to_dir(source_path, snapshot_path)
        manifest.append(entry)

    session = {
        "sandbox_id": sandbox_id,
        "label": label,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "snapshot_dir": str(snapshot_dir),
        "manifest": manifest,
        "runtime_snapshot": _capture_regression_runtime_snapshot(),
    }
    with regression_sandbox_lock:
        regression_sandbox_sessions[sandbox_id] = session
    return {
        "ok": True,
        "sandbox_id": sandbox_id,
        "label": label,
        "snapshot_dir": str(snapshot_dir),
        "tracked_targets": [entry["name"] for entry in manifest],
    }


async def _restore_regression_sandbox(sandbox_id: str) -> dict[str, Any]:
    with regression_sandbox_lock:
        session = regression_sandbox_sessions.pop(sandbox_id, None)
    if not session:
        raise HTTPException(status_code=404, detail=f"Regression sandbox not found: {sandbox_id}")

    snapshot_dir = Path(str(session.get("snapshot_dir", "")))
    manifest = list(session.get("manifest", []))
    restored_targets: list[str] = []

    await workspace_mcp_pool.shutdown()

    for entry in manifest:
        target_path = Path(str(entry.get("path", "")))
        snapshot_path = Path(str(entry.get("snapshot_path", "")))
        try:
            _remove_path_if_exists(target_path)
            if entry.get("existed") and snapshot_path.exists():
                _snapshot_path_to_dir(snapshot_path, target_path)
            restored_targets.append(str(entry.get("name", target_path.name)))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restore sandbox target {target_path}: {exc}",
            ) from exc

    _restore_regression_runtime_snapshot(copy.deepcopy(session.get("runtime_snapshot", {})))

    try:
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
    except Exception:
        pass

    return {
        "ok": True,
        "sandbox_id": sandbox_id,
        "restored_targets": restored_targets,
        "removed_snapshot_dir": str(snapshot_dir),
    }


def _get_cached_request_result(request_id: Optional[str]) -> Optional[dict[str, Any]]:
    return request_runtime_service.get_cached_result(request_id)


def _register_inflight_request(request_id: Optional[str], client_id: str) -> bool:
    return request_runtime_service.register_inflight_request(request_id, client_id)


def _release_inflight_request(request_id: Optional[str]) -> list[str]:
    return request_runtime_service.release_inflight_request(request_id)


async def _replay_cached_result_to_watchers(request_id: Optional[str]) -> None:
    if not request_id:
        return
    cached = _get_cached_request_result(request_id)
    if not cached:
        return
    watchers = _release_inflight_request(request_id)
    for watcher_client_id in watchers:
        replay_payload = _build_request_replay_payload(cached, source="inflight_watcher")
        await manager.send_personal_message(replay_payload, watcher_client_id)
        runtime_status = _request_runtime_status_from_payload(cached)
        delivery_status = _delivery_status_from_runtime_status(runtime_status)
        await send_request_delivery(
            watcher_client_id,
            request_id,
            delivery_status,
            message=_delivery_message_for_replay(runtime_status),
        )


async def _replay_cached_request_to_client(client_id: str, request_id: Optional[str]) -> bool:
    cached = _get_cached_request_result(request_id)
    if not cached or not request_id:
        return False
    replay_payload = _build_request_replay_payload(cached, source="request_journal")
    await manager.send_personal_message(replay_payload, client_id)
    runtime_status = _request_runtime_status_from_payload(cached)
    await send_request_delivery(
        client_id,
        request_id,
        _delivery_status_from_runtime_status(runtime_status),
        message=_delivery_message_for_replay(runtime_status),
    )
    return True


def build_runtime_connection_payload(client_id: str) -> dict[str, Any]:
    active_models = _get_active_available_models()
    default_model = _resolve_runtime_default_model()
    full_model_catalog = _build_model_catalog_with_runtime_status(available_models)

    tools = mcp_manager.get_all_tools() if mcp_manager else []
    connected = [s["name"] for s in (mcp_manager.servers if mcp_manager else []) if s.get("status") == "connected"]

    return {
        "type": "connection",
        "status": "connected",
        "client_id": client_id,
        "siliconflow_available": siliconflow_api_key is not None,
        "openrouter_available": openrouter_api_key is not None,
        "providers_ready": bool(siliconflow_api_key or openrouter_api_key),
        "available_models": [model["id"] for model in active_models],
        "models": full_model_catalog,
        "default_model": default_model,
        "agent_skills": {
            "count": len(agent_skills_registry.skills),
            "skills": agent_skills_registry.list_summaries(),
            "roots": agent_skills_registry.get_skill_roots_summary(),
            "failed": list(agent_skills_registry.failed),
        },
        "mcp_servers_available": len(connected) > 0,
        "connected_servers": connected,
        "available_tools": [
            {"server": t.get("server", ""), "name": t["name"], "display_name": t.get("display_name", t["name"])}
            for t in tools
        ],
        "timestamp": datetime.now().isoformat(),
    }


def build_runtime_status_payload(
    *,
    event: str,
    client_id: Optional[str] = None,
    message: str = "",
) -> dict[str, Any]:
    runtime_state = get_runtime_provider_state()
    tools = mcp_manager.get_all_tools() if mcp_manager else []
    connected = [s["name"] for s in (mcp_manager.servers if mcp_manager else []) if s.get("status") == "connected"]
    memory_snapshot = memory_control_plane.get_runtime_snapshot()
    return {
        "type": "runtime_status_update",
        "event": event,
        "client_id": client_id,
        "message": message,
        "providers_ready": bool(siliconflow_api_key or openrouter_api_key),
        "providers": runtime_state["providers"],
        "models": runtime_state["models"],
        "agent_skills": {
            "count": len(agent_skills_registry.skills),
            "skills": agent_skills_registry.list_summaries(),
            "roots": agent_skills_registry.get_skill_roots_summary(),
            "failed": list(agent_skills_registry.failed),
        },
        "mcp": {
            "available": bool(mcp_manager),
            "connected_servers": connected,
            "tools_count": len(tools),
            "available_tools": [
                {"server": t.get("server", ""), "name": t["name"], "display_name": t.get("display_name", t["name"])}
                for t in tools
            ],
        },
        "tem": tem.get_mode_state(),
        "tool_policy": get_runtime_tool_policy_state(),
        "auto_tool_routing": get_runtime_auto_tool_routing_state(),
        "memory_plane": memory_snapshot,
        "timestamp": datetime.now().isoformat(),
    }


async def push_runtime_status_update(
    *,
    event: str,
    client_id: Optional[str] = None,
    message: str = "",
) -> None:
    payload = build_runtime_status_payload(event=event, client_id=client_id, message=message)
    targets = [client_id] if client_id else list(manager.active_connections.keys())
    for target_client_id in targets:
        await manager.send_personal_message(payload, target_client_id)

# 初始化MCP管理器
async def initialize_mcp_manager():
    """初始化MCP管理器"""
    global mcp_manager
    try:
        logger.info("initializing enhanced MCP manager...")
        
        # 确保使用全局的enhanced_mcp_manager实例
        success = await mcp_manager.initialize()
        
        if success:
            logger.info("enhanced MCP manager initialized successfully")
            logger.info(f"initialized MCP tools: {len(mcp_manager.get_all_tools())}")
            return True
        else:
            logger.error("failed to initialize enhanced MCP manager")
            return False
            
    except Exception as e:
        logger.error(f"error while initializing MCP manager: {e}")
        logger.error(traceback.format_exc())
        return False

# 初始化SiliconFlow
def _normalize_openrouter_base_url(value: Optional[str]) -> str:
    return runtime_config_service.normalize_openrouter_base_url(value)


def _normalize_siliconflow_base_url(value: Optional[str]) -> str:
    return runtime_config_service.normalize_siliconflow_base_url(value)


def _get_available_provider_names() -> set[str]:
    return runtime_config_service.get_available_provider_names()


def _get_active_available_models() -> List[Dict[str, Any]]:
    return runtime_config_service.get_active_available_models()


def _resolve_runtime_default_model() -> str:
    return runtime_config_service.resolve_runtime_default_model()


def _is_model_available_for_runtime(model_id: str) -> bool:
    return runtime_config_service.is_model_available_for_runtime(model_id)


def _is_multimodal_model(model_id: str) -> bool:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return False
    for model in available_models:
        if str(model.get("id", "")).strip() == normalized_model_id:
            return str(model.get("type", "")).strip().lower() == "multimodal"
    lowered = normalized_model_id.lower()
    return "vl" in lowered or "vision" in lowered or "multimodal" in lowered


def _has_image_attachment(attachments: Any) -> bool:
    if not isinstance(attachments, list):
        return False
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        mime_type = str(attachment.get("mime_type") or attachment.get("content_type") or "").lower()
        if bool(attachment.get("is_image")) or mime_type.startswith("image/"):
            return True
    return False


def _get_attachment_plan_items(attachment_plan: Any) -> list[dict[str, Any]]:
    if not isinstance(attachment_plan, dict):
        return []
    items = attachment_plan.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _attachment_plan_has_role(attachment_plan: Any, role: str) -> bool:
    normalized = str(role or "").strip()
    if not normalized:
        return False
    return any(str(item.get("transport_role") or "").strip() == normalized for item in _get_attachment_plan_items(attachment_plan))


def _build_model_catalog_with_runtime_status(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return runtime_config_service.build_model_catalog_with_runtime_status(models)


def resolve_provider_for_model(model_id: str) -> str:
    return runtime_config_service.resolve_provider_for_model(model_id)


def get_provider_runtime(provider: str) -> tuple[Optional[str], str]:
    return runtime_config_service.get_provider_runtime(provider)


def _resolve_model_name(model_id: str) -> str:
    return runtime_config_service.resolve_model_name(model_id)


def _extract_tool_result_text(result: Any) -> str:
    payload = result
    if isinstance(result, dict):
        if result.get("result") is not None:
            payload = result.get("result")
        elif result.get("raw_result") is not None:
            payload = result.get("raw_result")

    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    else:
        text = str(payload or "").strip()

    text = text.translate(INVISIBLE_TEXT_CHARS)
    return text.strip() or "(empty tool result)"


def _normalize_tool_result_for_summary(result: Any, max_chars: int = TOOL_FOLLOWUP_RESULT_MAX_CHARS) -> str:
    text = _extract_tool_result_text(result)
    if len(text) <= max_chars:
        return text
    notice = "\n...(tool result truncated; middle omitted, tail preserved)...\n"
    remaining = max(max_chars - len(notice), 200)
    head_chars = max(int(remaining * 0.55), 120)
    tail_chars = max(remaining - head_chars, 80)
    head = text[:head_chars].rstrip()
    tail = text[-tail_chars:].lstrip()
    return f"{head}{notice}{tail}"


def _extract_requested_response_prefix(original_user_content: str) -> str:
    content = str(original_user_content or "")
    patterns = [
        r'starting with\s+"([^"]+)"',
        r"starting with\s+'([^']+)'",
        r'以[“"]([^"”]+)[”"]开头',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _extract_grounded_line_candidates(
    original_user_content: str,
    result: Any,
    *,
    limit_lines: int = 5,
) -> list[str]:
    tool_text = _extract_tool_result_text(result)
    if not tool_text:
        return []

    candidate_tokens: list[str] = []
    candidate_tokens.extend(re.findall(r'"([^"]{3,120})"', str(original_user_content or "")))
    candidate_tokens.extend(re.findall(r"'([^']{3,120})'", str(original_user_content or "")))
    candidate_tokens.extend(re.findall(r"\b[A-Z][A-Z0-9_:-]{3,}\b", str(original_user_content or "")))

    seen_tokens: set[str] = set()
    normalized_tokens: list[str] = []
    for token in candidate_tokens:
        normalized = str(token or "").strip()
        folded = normalized.lower()
        if not normalized or folded in seen_tokens:
            continue
        seen_tokens.add(folded)
        normalized_tokens.append(normalized)

    if not normalized_tokens:
        return []

    matches: list[str] = []
    seen_lines: set[str] = set()
    for line in tool_text.splitlines():
        stripped = str(line or "").strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(token.lower() in lowered for token in normalized_tokens):
            if stripped not in seen_lines:
                seen_lines.add(stripped)
                matches.append(stripped)
                if len(matches) >= limit_lines:
                    break
    return matches


def _build_tool_followup_fallback_response(
    *,
    request_id: Optional[str],
    model_id: str,
    original_user_content: str,
    tool_name: str,
    server_name: str,
    result: Any,
    tool_success: bool,
    failure_reason: str,
) -> Dict[str, Any]:
    prefix = _extract_requested_response_prefix(original_user_content)
    matched_lines = _extract_grounded_line_candidates(original_user_content, result, limit_lines=3)
    fallback_prefix = f"{prefix} " if prefix else ""

    if tool_success and matched_lines:
        content = f"{fallback_prefix}文件中的目标行是：{matched_lines[0]}"
    elif tool_success:
        content = (
            f"{fallback_prefix}工具 `{server_name}.{tool_name}` 已成功执行。"
            f"模型总结阶段暂时不可用，因此先基于真实工具结果返回关键内容："
            f"{_normalize_tool_result_for_summary(result, max_chars=900)}"
        )
    else:
        content = (
            f"{fallback_prefix}工具 `{server_name}.{tool_name}` 执行未成功。"
            f"原因：{failure_reason or 'unknown error'}"
        )

    return {
        "type": "response",
        "content": content,
        "model_used": model_id,
        "model_name": _resolve_model_name(model_id),
        "request_id": request_id,
        "timestamp": datetime.now().isoformat(),
        "tool_summary": {
            "tool_name": tool_name,
            "server_name": server_name,
            "success": tool_success,
            "fallback": True,
            "fallback_reason": failure_reason,
            "matched_lines": matched_lines,
        },
    }


def _should_force_grounded_tool_followup(
    *,
    original_user_content: str,
    tool_name: str,
    server_name: str,
    result: Any,
    tool_success: bool,
) -> bool:
    if not tool_success:
        return False
    normalized_query = str(original_user_content or "").strip().lower()
    if not normalized_query:
        return False
    matched_lines = _extract_grounded_line_candidates(original_user_content, result, limit_lines=1)
    if not matched_lines:
        return False
    normalized_tool = str(tool_name or "").strip().lower()
    normalized_server = str(server_name or "").strip().lower()
    if normalized_server == "filesystem" and normalized_tool in {"read_text_file", "read_file", "read_multiple_files"}:
        if any(token in normalized_query for token in {"exact", "line", "marker", "final_marker", "精确", "原文", "哪一行", "标记"}):
            return True
    return False


def _record_tool_user_message(
    client_id: str,
    content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> None:
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return

    attachment_list = [
        attachment
        for attachment in (attachments or [])
        if isinstance(attachment, dict)
    ]

    memory = context_engine.get_memory(client_id)
    last_message = memory.messages[-1] if memory.messages else None
    if (
        isinstance(last_message, dict)
        and last_message.get("role") == "user"
        and str(last_message.get("content") or "") == normalized_content
    ):
        return

    memory.add_message("user", normalized_content, attachments=attachment_list)
    memory.save()


async def _generate_tool_followup_response(
    *,
    client_id: str,
    request_id: Optional[str],
    model_id: str,
    original_user_content: str,
    tool_name: str,
    server_name: str,
    arguments: Dict[str, Any],
    result: Any,
    attachments: Optional[List[Dict[str, Any]]] = None,
    inferred_fields: Optional[List[str]] = None,
    custom_system_prompt: str = "",
    skill_ids: Optional[List[str]] = None,
    workspace_context_config: Optional[Dict[str, Any]] = None,
    stream_to_client: bool = False,
) -> Dict[str, Any]:
    normalized_model_id = model_id or _resolve_runtime_default_model()
    if not _is_model_available_for_runtime(normalized_model_id):
        normalized_model_id = _resolve_runtime_default_model()

    provider = resolve_provider_for_model(normalized_model_id)
    api_key, api_base = get_provider_runtime(provider)
    if not api_key:
        raise RuntimeError(f"Model provider not configured: {provider}")

    attachment_names = [
        str(attachment.get("original_filename") or attachment.get("filename") or "").strip()
        for attachment in (attachments or [])
        if isinstance(attachment, dict)
    ]
    attachment_names = [name for name in attachment_names if name]

    skill_runtime = _resolve_skill_runtime_for_request(
        requested_skill_ids=skill_ids,
        query=original_user_content,
        workspace_context_config=workspace_context_config,
        workspace_agent_profile=load_workspace_agent_runtime_profile(
            workspace_root=str((workspace_context_config or {}).get("workspace_root", "") or ""),
            agent_name=str((workspace_context_config or {}).get("agent_name", "") or ""),
        ),
        model_id=normalized_model_id,
        available_tools=(mcp_manager.get_all_tools() if mcp_manager else []),
        scopes=["chat", "tool_followup"],
    )
    skills_context = str(skill_runtime.get("prompt_context", "") or "")
    workspace_context_text = ""
    workspace_context_metadata: Dict[str, Any] = {}
    if isinstance(workspace_context_config, dict):
        workspace_context_text, workspace_context_metadata = build_workspace_context_block(
            workspace_root=str(workspace_context_config.get("workspace_root", "") or ""),
            agent_name=str(workspace_context_config.get("agent_name", "") or ""),
            include_agent_profile=bool(workspace_context_config.get("include_agent_profile", True)),
            include_memory_file=bool(workspace_context_config.get("include_memory_file", True)),
            include_chatlogs=bool(workspace_context_config.get("include_chatlogs", False)),
        )

    tool_success = bool(isinstance(result, dict) and result.get("success", False))
    if _should_force_grounded_tool_followup(
        original_user_content=original_user_content,
        tool_name=tool_name,
        server_name=server_name,
        result=result,
        tool_success=tool_success,
    ):
        fallback = _build_tool_followup_fallback_response(
            request_id=request_id,
            model_id=normalized_model_id,
            original_user_content=original_user_content,
            tool_name=tool_name,
            server_name=server_name,
            result=result,
            tool_success=tool_success,
            failure_reason="grounded_exact_match",
        )
        context_engine.record_assistant_response(client_id, str(fallback.get("content", "")))
        return fallback
    system_parts = [
        "You are MCP Mirror's assistant.",
        "A real MCP tool has already executed.",
        "Use the tool output as grounded evidence and answer the user's original request directly.",
        "Do not dump raw JSON unless it is necessary for the user.",
        "If the tool failed, explain the failure plainly and suggest the safest next step.",
        "If the tool output is partial or truncated, say so explicitly.",
    ]
    if custom_system_prompt.strip():
        system_parts.append(f"User-defined system prompt:\n{custom_system_prompt.strip()}")
    if skills_context.strip():
        system_parts.append(f"Agent skills context:\n{skills_context.strip()}")
    if workspace_context_text.strip():
        system_parts.append(f"Workspace file context:\n{workspace_context_text.strip()}")

    user_parts = [
        f"Original user request:\n{original_user_content.strip() or f'Call the tool {server_name}.{tool_name} and explain the result.'}",
        f"Executed tool:\n{server_name}.{tool_name}",
        f"Tool success:\n{'true' if tool_success else 'false'}",
        f"Arguments:\n{json.dumps(arguments or {}, ensure_ascii=False, indent=2, default=str)}",
        f"Tool result:\n{_normalize_tool_result_for_summary(result)}",
    ]
    if inferred_fields:
        user_parts.append(f"Inferred argument fields:\n{', '.join(inferred_fields)}")
    if attachment_names:
        user_parts.append(f"Related attachments:\n{', '.join(attachment_names)}")
    user_parts.append(
        "Please produce a user-facing answer in the same language as the user's request when possible. "
        "Summarize what the tool found, mention any important limitation, and avoid internal implementation jargon."
    )

    payload = {
        "model": normalized_model_id,
        "messages": [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        "temperature": 0.2,
        "max_tokens": TOOL_FOLLOWUP_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **({"HTTP-Referer": "http://localhost:8000", "X-Title": "MCP Mirror"} if provider == "openrouter" else {}),
    }

    try:
        streamed_response = None
        if stream_to_client:
            streamed_response = await _stream_chat_completion_to_client(
                get_shared_http_client(),
                client_id=client_id,
                request_id=request_id,
                url=f"{api_base}/chat/completions",
                headers=headers,
                payload=payload,
                provider=provider,
                model_id=normalized_model_id,
                model_name=_resolve_model_name(normalized_model_id),
                timeout_seconds=TOOL_FOLLOWUP_API_TIMEOUT_SECONDS,
        metadata={
            "tool_summary": {
                "tool_name": tool_name,
                "server_name": server_name,
                "success": tool_success,
            },
            "skill_runtime": skill_runtime,
            "workspace_context": workspace_context_metadata,
        },
            )
        if streamed_response and streamed_response.get("content"):
            ai_response = str(streamed_response.get("content", "") or "").strip()
            context_engine.record_assistant_response(client_id, ai_response)
            return {
                "type": "response",
                "id": streamed_response.get("id"),
                "content": ai_response,
                "model_used": normalized_model_id,
                "model_name": _resolve_model_name(normalized_model_id),
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "tool_summary": {
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "success": tool_success,
                },
                "metadata": {
                    "workspace_context": workspace_context_metadata,
                },
            }

        response = await _post_chat_with_retry(
            get_shared_http_client(),
            url=f"{api_base}/chat/completions",
            headers=headers,
            payload=payload,
            provider=provider,
            timeout_seconds=TOOL_FOLLOWUP_API_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        logger.warning(f"tool follow-up model timed out: {type(exc).__name__}")
        fallback = _build_tool_followup_fallback_response(
            request_id=request_id,
            model_id=normalized_model_id,
            original_user_content=original_user_content,
            tool_name=tool_name,
            server_name=server_name,
            result=result,
            tool_success=tool_success,
            failure_reason=f"model_summary_timeout:{type(exc).__name__}",
        )
        context_engine.record_assistant_response(client_id, str(fallback.get("content", "")))
        return fallback

    if response.status_code != 200:
        error_text = response.text[:500]
        raise RuntimeError(_friendly_provider_error(provider, response.status_code, error_text))

    result_json = response.json()
    ai_response = ""
    if isinstance(result_json, dict) and "choices" in result_json:
        choices = result_json.get("choices", [])
        if choices:
            ai_response = str(choices[0].get("message", {}).get("content", "") or "")
    if not ai_response:
        ai_response = str(result_json.get("content", "") or "").strip()
    if not ai_response:
        raise RuntimeError("Tool follow-up model returned an empty response")

    context_engine.record_assistant_response(client_id, ai_response)
    return {
        "type": "response",
        "content": ai_response,
        "model_used": normalized_model_id,
        "model_name": _resolve_model_name(normalized_model_id),
        "request_id": request_id,
        "timestamp": datetime.now().isoformat(),
        "tool_summary": {
            "tool_name": tool_name,
            "server_name": server_name,
            "success": tool_success,
        },
        "metadata": {
            "workspace_context": workspace_context_metadata,
        },
    }


def _friendly_provider_error(provider: str, status_code: int, error_text: str) -> str:
    return runtime_config_service.friendly_provider_error(provider, status_code, error_text)


def _friendly_exception_message(exc: Exception) -> str:
    if isinstance(exc, httpx.ReadTimeout):
        return (
            "模型响应超时。可能是当前模型较慢、请求中包含较大附件，或上游服务暂时拥堵。"
            "请稍后重试，或切换到更快的模型。"
        )
    if isinstance(exc, httpx.TimeoutException):
        return "请求模型服务超时，请稍后重试。"
    return str(exc) or repr(exc)


def _build_model_tool_definitions(
    tools: List[Dict[str, Any]],
    *,
    allowed_tool_names: Optional[List[str]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    allowed_set = {
        str(name).strip()
        for name in (allowed_tool_names or [])
        if str(name).strip()
    }
    definitions: List[Dict[str, Any]] = []
    tool_lookup: Dict[str, Dict[str, Any]] = {}
    seen_names: set[str] = set()

    for tool in tools:
        tool_name = str(tool.get("name", "")).strip()
        server_name = str(tool.get("server", "")).strip()
        if not tool_name or not server_name:
            continue
        if allowed_set and tool_name not in allowed_set:
            continue
        model_visible_name = _build_model_visible_tool_name(server_name, tool_name)
        if model_visible_name in seen_names:
            continue
        seen_names.add(model_visible_name)

        schema = tool.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}, "additionalProperties": True}

        description = str(tool.get("description", "") or "").strip()
        if server_name and server_name not in description:
            description = f"[MCP server: {server_name}] {description}" if description else f"MCP tool from server {server_name}"
        description = (
            f"{description}\n\nUse this function when the user asks for the capability provided by "
            f"{server_name}.{tool_name}. Do not call it for ordinary conversation."
        ).strip()

        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": model_visible_name,
                    "description": description[:1200],
                    "parameters": schema,
                },
            }
        )
        tool_lookup[model_visible_name] = tool

    return definitions, tool_lookup


def _extract_assistant_message_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    choices = result.get("choices", []) if isinstance(result, dict) else []
    if not choices:
        return {}
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    return message if isinstance(message, dict) else {}


def _extract_text_content_from_message(message: Dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part.strip())
    return str(content or "")


def _extract_generated_images_from_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(message, dict):
        return []
    images: List[Dict[str, Any]] = []
    images.extend(_extract_generated_images_from_result(message.get("images")))
    images.extend(_extract_generated_images_from_result(message.get("image")))
    images.extend(_extract_generated_images_from_result(message.get("generated_images")))
    images.extend(_extract_generated_images_from_result(message.get("image_url")))
    images.extend(_extract_generated_images_from_result(message.get("output_image")))
    content = message.get("content")
    if isinstance(content, list):
        images.extend(_extract_generated_images_from_result(content))
    return _dedupe_generated_images(images)


def _safe_json_loads(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _build_model_visible_tool_name(server_name: str, tool_name: str) -> str:
    normalized_server = re.sub(r"[^a-zA-Z0-9_]+", "_", str(server_name or "").strip())
    normalized_tool = re.sub(r"[^a-zA-Z0-9_]+", "_", str(tool_name or "").strip())
    composite = f"mcp__{normalized_server}__{normalized_tool}".strip("_")
    if len(composite) <= 64:
        return composite
    digest = hashlib.sha1(f"{server_name}::{tool_name}".encode("utf-8")).hexdigest()[:10]
    trimmed_server = normalized_server[:18]
    trimmed_tool = normalized_tool[:24]
    return f"mcp__{trimmed_server}__{trimmed_tool}__{digest}"


def _rank_tools_for_model_visibility(
    query: str,
    tools: List[Dict[str, Any]],
    memory_plan: Optional[Dict[str, Any]] = None,
    *,
    max_tools: int = MODEL_TOOL_MAX_VISIBLE_TOOLS,
) -> List[Dict[str, Any]]:
    if not tools:
        return []

    routing = memory_plan.get("routing", {}) if isinstance(memory_plan, dict) else {}
    score_lookup: Dict[str, float] = {}
    if isinstance(routing, dict):
        for score_item in routing.get("scores", []) or []:
            if not isinstance(score_item, dict):
                continue
            tool_name = str(score_item.get("tool_name", "")).strip()
            if tool_name:
                score_lookup[tool_name] = float(score_item.get("final_score", 0.0) or 0.0)

    inferred_names = infer_relevant_tool_names(
        query,
        [str(tool.get("name", "")).strip() for tool in tools if str(tool.get("name", "")).strip()],
    )
    inferred_rank = {name: index for index, name in enumerate(inferred_names)}

    ranked = sorted(
        tools,
        key=lambda tool: (
            score_lookup.get(str(tool.get("name", "")).strip(), 0.0),
            -inferred_rank.get(str(tool.get("name", "")).strip(), 10_000),
            str(tool.get("server", "")).strip(),
            str(tool.get("name", "")).strip(),
        ),
        reverse=True,
    )
    return ranked[:max_tools]


async def _run_model_driven_tool_loop(
    *,
    client_id: str,
    request_id: Optional[str],
    model_id: str,
    provider: str,
    api_key: str,
    api_base: str,
    api_messages: List[Dict[str, Any]],
    available_tool_catalog: List[Dict[str, Any]],
    allowed_tool_names: List[str],
    original_user_content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    skill_ids: Optional[List[str]] = None,
    custom_system_prompt: str = "",
    workspace_context_config: Optional[Dict[str, Any]] = None,
    active_mcp_manager: Optional[Any] = None,
    memory_plan: Optional[dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    tool_definitions, model_tool_lookup = _build_model_tool_definitions(
        available_tool_catalog,
        allowed_tool_names=allowed_tool_names,
    )
    if not tool_definitions:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **({"HTTP-Referer": "http://localhost:8000", "X-Title": "MCP Mirror"} if provider == "openrouter" else {}),
    }

    conversation_messages = copy.deepcopy(api_messages)
    collected_tool_evidence: List[Dict[str, Any]] = []

    client = get_shared_http_client()
    for _step in range(MODEL_TOOL_CALL_MAX_STEPS):
        payload = {
            "model": model_id,
            "messages": conversation_messages,
            "temperature": DEFAULT_CHAT_TEMPERATURE,
            "max_tokens": DEFAULT_WS_CHAT_MAX_TOKENS,
            "tools": tool_definitions,
            "tool_choice": "auto",
        }
        response = await _post_chat_with_retry(
            client,
            url=f"{api_base}/chat/completions",
            headers=headers,
            payload=payload,
            provider=provider,
        )
        if response.status_code != 200:
            error_text = response.text[:500]
            raise RuntimeError(_friendly_provider_error(provider, response.status_code, error_text))

        result = response.json()
        assistant_message = _extract_assistant_message_from_result(result)
        assistant_content = _extract_text_content_from_message(assistant_message)
        generated_images = _extract_generated_images_from_message(assistant_message)
        tool_calls = assistant_message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            tool_calls = []

        if assistant_content.strip() and not tool_calls and _looks_like_fabricated_tool_text(assistant_content):
            logger.warning("model returned fabricated-looking tool prose without real tool_calls; suppressing plain response and falling back")
            return None

        if (assistant_content.strip() or generated_images) and not tool_calls:
            metadata: Dict[str, Any] = {}
            if generated_images:
                metadata["generated_images"] = generated_images
            if collected_tool_evidence:
                last_tool = collected_tool_evidence[-1]
                metadata.update(
                    {
                        "tool_result_available": True,
                        "tool_evidence": last_tool,
                        "tool_name": last_tool.get("tool_name"),
                        "server_name": last_tool.get("server_name"),
                        "arguments": last_tool.get("arguments"),
                        "result": last_tool.get("result"),
                        "tools_used": [
                            tool_key(
                                str(item.get("server_name", "")),
                                str(item.get("tool_name", "")),
                            )
                            for item in collected_tool_evidence
                            if str(item.get("tool_name", "")).strip()
                        ],
                    }
                )

            return {
                "type": "response",
                "content": assistant_content or "",
                "generated_images": generated_images,
                "image_paths": [
                    str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                    for item in generated_images
                    if isinstance(item, dict) and str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                ],
                "model_used": model_id,
                "model_name": _resolve_model_name(model_id),
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "memory_plane": memory_plan or {},
                "metadata": metadata,
            }

        if not tool_calls:
            return None

        conversation_messages.append(
            {
                "role": "assistant",
                "content": assistant_content or "",
                "tool_calls": tool_calls,
            }
        )

        tool_calls = tool_calls[:MODEL_TOOL_CALL_MAX_PER_STEP]
        for tool_call in tool_calls:
            function_payload = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            model_visible_name = str(function_payload.get("name", "")).strip()
            if not model_visible_name:
                continue
            tool_catalog_entry = model_tool_lookup.get(model_visible_name)
            tool_name = str(tool_catalog_entry.get("name", "")).strip() if tool_catalog_entry else ""
            server_name = str(tool_catalog_entry.get("server", "")).strip() if tool_catalog_entry else ""
            arguments = _safe_json_loads(function_payload.get("arguments"))
            if not tool_catalog_entry:
                tool_result = {
                    "success": False,
                    "error": f"Tool '{model_visible_name}' is not available in current MCP runtime.",
                    "tool_name": model_visible_name,
                }
            else:
                execution = await _execute_tool_call_internal(
                    client_id=client_id,
                    request_id=request_id,
                    tool_name=tool_name,
                    server_name=server_name,
                    arguments=arguments,
                    original_user_content=original_user_content,
                    model_id=model_id,
                    attachments=attachments if isinstance(attachments, list) else [],
                    skill_ids=skill_ids,
                    custom_system_prompt=custom_system_prompt,
                    workspace_context_config=workspace_context_config,
                    active_mcp_manager=active_mcp_manager,
                    policy_confirmed=False,
                    memory_plan_override=memory_control_plane.build_routed_tool_execution_plan(
                        client_id=client_id,
                        query=original_user_content,
                        candidate_tool_names=[tool_name],
                        tool_catalog=[tool_catalog_entry],
                        arguments=arguments,
                        context_engine=context_engine,
                        tem=tem,
                        server_name=server_name,
                        dry_run=False,
                    ),
                    auto_tool_call=True,
                    auto_tool_reason="model_tool_call",
                    auto_tool_confidence=None,
                    allow_recipe_preflight_block=True,
                    include_followup_response=False,
                )
                tool_result_payload = execution.get("tool_result_payload") or execution.get("final_payload") or {}
                tool_result = tool_result_payload.get("result")
                if tool_result is None:
                    tool_result = tool_result_payload

            tool_evidence = {
                "tool_name": tool_name,
                "server_name": server_name,
                "arguments": arguments,
                "result": tool_result,
                "run_trace": {
                    "kind": "tool_call",
                    "tool_name": tool_name,
                    "server_name": server_name,
                },
            }
            collected_tool_evidence.append(tool_evidence)
            conversation_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": _normalize_tool_result_for_summary(tool_result),
                }
            )

            if tool_catalog_entry:
                followup_payload = await _generate_tool_followup_response(
                    client_id=client_id,
                    request_id=request_id,
                    model_id=model_id,
                    original_user_content=original_user_content,
                    tool_name=tool_name,
                    server_name=server_name,
                    arguments=arguments,
                    result=tool_result,
                    attachments=attachments if isinstance(attachments, list) else [],
                    inferred_fields=tool_result_payload.get("inferred_arguments") if isinstance(tool_result_payload, dict) else None,
                    custom_system_prompt=custom_system_prompt,
                    skill_ids=skill_ids,
                    workspace_context_config=workspace_context_config,
                    stream_to_client=True,
                )
                if isinstance(followup_payload, dict):
                    tool_result_payload = execution.get("tool_result_payload") or execution.get("final_payload") or {}
                    tool_metadata = copy.deepcopy(tool_result_payload) if isinstance(tool_result_payload, dict) else {}
                    merged_metadata = {
                        **(
                            followup_payload.get("metadata", {})
                            if isinstance(followup_payload.get("metadata", {}), dict)
                            else {}
                        ),
                        "tool_name": tool_name,
                        "server_name": server_name,
                        "tool_result_available": True,
                        "tool_evidence": tool_metadata,
                        "arguments": arguments,
                        "result": tool_result,
                        "execution_time": execution.get("latency_ms", 0.0) / 1000.0 if execution.get("latency_ms") is not None else None,
                        "tools_used": [tool_key(server_name, tool_name)],
                    }
                    if followup_payload.get("id"):
                        return {
                            "streamed_to_client": True,
                            "id": followup_payload.get("id"),
                            "content": str(followup_payload.get("content", "") or "").strip(),
                        }
                    return {
                        "type": "response",
                        "id": followup_payload.get("id") or _build_assistant_message_id(request_id),
                        "content": str(followup_payload.get("content", "") or "").strip(),
                        "model_used": model_id,
                        "model_name": _resolve_model_name(model_id),
                        "request_id": request_id,
                        "timestamp": followup_payload.get("timestamp") or datetime.now().isoformat(),
                        "memory_plane": memory_plan or {},
                        "tem_event": tool_result_payload.get("tem_event") if isinstance(tool_result_payload, dict) else None,
                        "causal_trace": tool_result_payload.get("causal_trace") if isinstance(tool_result_payload, dict) else None,
                        "recipe_preflight": tool_result_payload.get("recipe_preflight") if isinstance(tool_result_payload, dict) else None,
                        "run_trace": tool_result_payload.get("run_trace") if isinstance(tool_result_payload, dict) else None,
                        "metadata": merged_metadata,
                    }

    return None


async def _post_chat_with_retry(
    client: "httpx.AsyncClient",
    *,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    provider: str,
    timeout_seconds: float = API_TIMEOUT_SECONDS,
) -> "httpx.Response":
    retries = OPENROUTER_MAX_RETRIES if provider == "openrouter" else 1
    last_response = None

    for attempt in range(1, retries + 1):
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
        last_response = response
        if response.status_code != 429:
            return response

        if attempt >= retries:
            return response

        delay = min(
            OPENROUTER_RETRY_BASE_SECONDS * (2 ** (attempt - 1)) + random.uniform(0.0, 0.4),
            OPENROUTER_RETRY_MAX_SECONDS,
        )
        logger.warning(f"OpenRouter rate limited (429), retry {attempt}/{retries} in {delay:.2f}s")
        await asyncio.sleep(delay)

    return last_response


def initialize_siliconflow():
    """Initialize SiliconFlow + OpenRouter API."""
    global siliconflow_api_key, siliconflow_base_url, openrouter_api_key, openrouter_base_url, available_models
    initialized = runtime_config_service.initialize_providers()
    siliconflow_api_key = runtime_config_service.siliconflow_api_key
    siliconflow_base_url = runtime_config_service.siliconflow_base_url
    openrouter_api_key = runtime_config_service.openrouter_api_key
    openrouter_base_url = runtime_config_service.openrouter_base_url
    available_models = runtime_config_service.available_models
    return initialized


def get_runtime_provider_state() -> dict[str, Any]:
    return runtime_config_service.get_provider_state()


def _normalize_tool_policy_action(value: Any) -> str:
    return runtime_config_service.normalize_tool_policy_action(value)


def get_runtime_tool_policy_state() -> dict[str, Any]:
    return runtime_config_service.get_tool_policy_state()


def _normalize_auto_tool_routing_mode(value: Any) -> str:
    return runtime_config_service.normalize_auto_tool_routing_mode(value)


def get_runtime_auto_tool_routing_state() -> dict[str, Any]:
    return runtime_config_service.get_auto_tool_routing_state()


def get_runtime_memory_plane_state() -> dict[str, Any]:
    return runtime_config_service.get_memory_plane_runtime_state()


def _build_mcp_tool_onboarding_audit_for_manager(
    active_manager: Optional[Any] = None,
    workspace_root: str = "",
) -> dict[str, Any]:
    return mcp_onboarding_service.build_audit_for_manager(
        active_manager=active_manager,
        workspace_root=workspace_root,
    )


def _build_mcp_tool_onboarding_audit() -> dict[str, Any]:
    return mcp_onboarding_service.build_default_audit()


def _build_tool_minimal_self_test_plan(
    *,
    tool: Dict[str, Any],
    automation_class: str,
    required_fields: List[str],
    inferred_fields: List[str],
    schema_warnings: List[str],
    project_root_str: str,
    self_test_root: str,
    readme_path: str,
    pixel_path: str,
) -> dict[str, Any]:
    return mcp_onboarding_service._build_tool_minimal_self_test_plan(
        tool=tool,
        automation_class=automation_class,
        required_fields=required_fields,
        inferred_fields=inferred_fields,
        schema_warnings=schema_warnings,
        project_root_str=project_root_str,
        self_test_root=self_test_root,
        readme_path=readme_path,
        pixel_path=pixel_path,
    )


async def _execute_tool_onboarding_self_test(
    *,
    tool: Dict[str, Any],
    plan: Dict[str, Any],
    active_manager: Optional[Any] = None,
) -> dict[str, Any]:
    return await mcp_onboarding_service.execute_tool_onboarding_self_test(
        tool=tool,
        plan=plan,
        active_manager=active_manager,
    )


def _is_high_risk_path_value(value: Any) -> bool:
    return runtime_config_service.is_high_risk_path_value(value)


def _tool_policy_requires_path_review(tool_name: str, arguments: Dict[str, Any]) -> bool:
    return runtime_config_service.tool_policy_requires_path_review(tool_name, arguments)


def evaluate_runtime_tool_policy(
    *,
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
    policy_confirmed: bool = False,
) -> Optional[dict[str, Any]]:
    return runtime_config_service.evaluate_tool_policy(
        server_name=server_name,
        tool_name=tool_name,
        arguments=arguments,
        policy_confirmed=policy_confirmed,
    )


def build_attachment_run_trace(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []
    parsed_items: list[dict[str, Any]] = []
    for attachment in attachments[:8]:
        if not isinstance(attachment, dict):
            continue
        parsed = extract_attachment_content(attachment, max_chars=800)
        parsed_items.append({
            "filename": parsed.get("filename"),
            "original_filename": parsed.get("original_filename"),
            "mime_type": parsed.get("mime_type"),
            "size": parsed.get("size"),
            "parse_status": parsed.get("parse_status"),
            "parse_mode": parsed.get("parse_mode"),
            "parser": parsed.get("parser"),
            "full_text_chars": parsed.get("full_text_chars"),
            "preview_text": parsed.get("preview_text"),
            "error": parsed.get("error"),
        })
    return parsed_items


def build_chat_run_trace(
    *,
    request_id: Optional[str],
    provider: str,
    model_id: str,
    attachments: Any,
    memory_plan: dict[str, Any],
    comp_stats: Any,
) -> dict[str, Any]:
    return {
        "kind": "chat",
        "request_id": request_id,
        "provider": provider,
        "model_id": model_id,
        "attachments": build_attachment_run_trace(attachments),
        "memory": comp_stats.to_dict() if hasattr(comp_stats, "to_dict") else {},
        "routing": (memory_plan or {}).get("routing", {}),
        "memory_plane_phase": (memory_plan or {}).get("memory_plane", {}).get("phase"),
        "timestamp": datetime.now().isoformat(),
    }


def build_tool_run_trace(
    *,
    request_id: Optional[str],
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
    memory_plan: Optional[dict[str, Any]],
    policy_block: Optional[dict[str, Any]] = None,
    latency_ms: Optional[float] = None,
    success: Optional[bool] = None,
    blocked: bool = False,
) -> dict[str, Any]:
    return runtime_config_service.build_tool_run_trace(
        request_id=request_id,
        server_name=server_name,
        tool_name=tool_name,
        arguments=arguments,
        memory_plan=memory_plan,
        policy_block=policy_block,
        latency_ms=latency_ms,
        success=success,
        blocked=blocked,
    )


async def _probe_openrouter_connectivity(
    *,
    api_key: Optional[str],
    base_url: Optional[str],
) -> dict[str, Any]:
    return await runtime_config_service.probe_openrouter_connectivity(
        api_key=api_key,
        base_url=base_url,
    )


async def _probe_siliconflow_connectivity(*, api_key: Optional[str], base_url: Optional[str] = None) -> dict[str, Any]:
    return await runtime_config_service.probe_siliconflow_connectivity(
        api_key=api_key,
        base_url=base_url,
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hooks."""
    logger.info("starting MCP Chat Interface with SiliconFlow")
    get_shared_http_client()

    _load_request_runtime_journal()

    siliconflow_ok = initialize_siliconflow()

    logger.info("initializing MCP manager...")
    mcp_ok = await initialize_mcp_manager()

    print("\n" + "=" * 60)
    print("MCP Chat Interface with SiliconFlow started")
    print("=" * 60)
    print(f"URL: http://localhost:{DEFAULT_SERVER_PORT}")
    print(f"WebSocket: ws://localhost:{DEFAULT_SERVER_PORT}/ws/{{client_id}}")
    print(f"API docs: http://localhost:{DEFAULT_SERVER_PORT}/docs")
    print(f"SiliconFlow API: {'configured' if siliconflow_api_key else 'not configured'}")
    print(f"SiliconFlow base URL: {_normalize_siliconflow_base_url(siliconflow_base_url)}")
    print(f"OpenRouter API: {'configured' if openrouter_api_key else 'not configured'}")
    print(f"Available models: {len(available_models)}")
    print(f"MCP manager: {'available' if mcp_ok else 'unavailable'}")
    print("\nPress Ctrl+C to stop\n")
    slog.info("backend_started", extra={
        "status": "ok",
        "server_name": "mcp_mirror",
        "tool_name": "",
        "latency_ms": 0,
    })

    try:
        await agent_run_scheduler.start()
        yield
    finally:
        logger.info("shutting down MCP Chat Interface")
        try:
            await agent_run_scheduler.shutdown()
        except Exception as e:
            logger.error(f"failed to stop agent run scheduler: {e}")
        global shared_http_client
        if shared_http_client is not None and not shared_http_client.is_closed:
            try:
                await shared_http_client.aclose()
            except Exception as e:
                logger.error(f"failed to close shared http client: {e}")
            finally:
                shared_http_client = None
        if mcp_manager and hasattr(mcp_manager, 'shutdown'):
            try:
                await mcp_manager.shutdown()
            except Exception as e:
                logger.error(f"failed to close MCP manager: {e}")
        logger.info("service shutdown complete")


app = FastAPI(
    title="MCP Chat Interface with SiliconFlow",
    description="支持真实MCP工具调用的聊天界面",
    version="2.0.0",
    lifespan=lifespan,
)

# 配置CORS - 允许所有来源（开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API路由
@app.get("/")
async def root():
    """根路径"""
    return {"message": "MCP Chat Interface with SiliconFlow", "status": "running"}

@app.get("/health")
async def health_check():
    """健康检查"""
    runtime_state = get_runtime_provider_state()
    servers_payload = (
        mcp_manager.get_server_status()
        if (mcp_manager and hasattr(mcp_manager, "get_server_status"))
        else {"servers": [], "total_servers": 0, "connected_servers": 0, "total_tools": 0}
    )
    tools = mcp_manager.get_all_tools() if mcp_manager else []
    connected = [s["name"] for s in (mcp_manager.servers if mcp_manager else []) if s.get("status") == "connected"]
    audit = (
        build_runtime_audit_report(
            {"mcpServers": getattr(mcp_manager, "config", {})},
            {"servers": servers_payload},
            {"tools": tools},
        )
        if mcp_manager
        else {"ok": False, "errors": ["MCP manager unavailable"]}
    )
    onboarding_audit = _build_mcp_tool_onboarding_audit()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "mcp_manager": "available" if mcp_manager else "unavailable",
        "siliconflow_api": "configured" if siliconflow_api_key else "not_configured",
        "siliconflow_base_url": _normalize_siliconflow_base_url(siliconflow_base_url),
        "openrouter_api": "configured" if openrouter_api_key else "not_configured",
        "openrouter_base_url": _normalize_openrouter_base_url(openrouter_base_url),
        "tem": tem.get_mode_state(),
        "providers": runtime_state["providers"],
        "models": runtime_state["models"],
        "mcp": {
            "connected_servers": connected,
            "servers": servers_payload,
            "tools_count": len(tools),
            "audit": audit,
            "tool_onboarding_audit": onboarding_audit,
        },
        "memory_plane": memory_control_plane.get_runtime_snapshot(),
    }

@app.get("/api/models")
async def get_models():
    """获取可用模型列表"""
    try:
        runtime_state = get_runtime_provider_state()
        return JSONResponse(
            content={
                "models": runtime_state["models"]["available"],
                "default": runtime_state["models"]["default"]
            },
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    except Exception as e:
        logger.error(f"failed to get model list: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


@app.get("/api/runtime/providers")
async def get_runtime_provider_config():
    """获取当前运行时 Provider / Model 配置状态。"""
    try:
        return get_runtime_provider_state()
    except Exception as e:
        logger.error(f"failed to get runtime provider config: {e}")
        raise HTTPException(status_code=500, detail=f"获取运行时 Provider 配置失败: {str(e)}")


@app.get("/api/mcp/tool-onboarding-audit")
async def get_mcp_tool_onboarding_audit(workspace_root: str = Query("", alias="workspace_root")):
    try:
        active_mcp_manager, workspace_mcp_metadata = await _get_effective_mcp_manager({
            "workspace_root": workspace_root,
        } if str(workspace_root or "").strip() else {})
        audit = _build_mcp_tool_onboarding_audit_for_manager(active_mcp_manager, workspace_root=workspace_root)
        audit["workspace_mcp"] = workspace_mcp_metadata
        return audit
    except Exception as e:
        logger.error(f"failed to build MCP tool onboarding audit: {e}")
        raise HTTPException(status_code=500, detail=f"生成 MCP 工具接入审计失败: {str(e)}")


@app.post("/api/mcp/tool-onboarding-audit/run")
async def run_mcp_tool_onboarding_self_tests(request: ToolOnboardingSelfTestRequest):
    """
    Run safe, read-only onboarding probes directly against the MCP runtime.

    This route intentionally bypasses TEM / Memory Plane learning hooks so
    product diagnostics do not create recipe or guard evidence.
    """
    try:
        active_mcp_manager, workspace_mcp_metadata = await _get_effective_mcp_manager({
            "workspace_root": request.workspace_root,
        } if str(request.workspace_root or "").strip() else {})
        audit = _build_mcp_tool_onboarding_audit_for_manager(active_mcp_manager, workspace_root=request.workspace_root)
        requested_keys = {
            str(item).strip().lower()
            for item in (request.tool_keys or [])
            if str(item).strip()
        }
        max_tools = max(1, min(int(request.max_tools or 50), 100))
        selected_items: list[dict[str, Any]] = []
        for item in audit.get("tools", []):
            item_key = str(item.get("tool_key", "")).strip().lower()
            self_test = item.get("self_test") if isinstance(item.get("self_test"), dict) else {}
            if requested_keys:
                if item_key not in requested_keys:
                    continue
            elif request.execute_safe_only and not bool(self_test.get("safe_to_run")):
                continue
            selected_items.append(item)
            if len(selected_items) >= max_tools:
                break

        tool_lookup = {
            tool_key(str(tool.get("server", "")), str(tool.get("name", ""))).lower(): tool
            for tool in (active_mcp_manager.get_all_tools() if active_mcp_manager else [])
        }
        results: list[dict[str, Any]] = []
        for item in selected_items:
            item_key = str(item.get("tool_key", "")).strip().lower()
            tool = tool_lookup.get(item_key)
            if not tool:
                results.append({
                    "tool_key": item.get("tool_key", ""),
                    "ok": False,
                    "status": "missing_tool",
                    "skipped": True,
                    "reason": "Tool disappeared from runtime catalog before self-test execution.",
                })
                continue
            result = await _execute_tool_onboarding_self_test(
                tool=tool,
                plan=item.get("self_test") if isinstance(item.get("self_test"), dict) else {},
                active_manager=active_mcp_manager,
            )
            results.append(result)

        total = len(results)
        passed = len([result for result in results if result.get("ok")])
        failed = len([result for result in results if not result.get("ok") and not result.get("skipped")])
        skipped = len([result for result in results if result.get("skipped")])
        gate_failed = [
            result for result in results
            if not result.get("ok")
            and not result.get("skipped")
            and bool(
                next(
                    (
                        item.get("self_test", {}).get("gate_required")
                        for item in selected_items
                        if str(item.get("tool_key", "")).strip().lower() == str(result.get("tool_key", "")).strip().lower()
                    ),
                    False,
                )
            )
        ]
        return {
            "ok": failed == 0 and len(gate_failed) == 0,
            "workspace_mcp": workspace_mcp_metadata,
            "summary": {
                "requested": len(requested_keys),
                "executed_or_skipped": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "gate_failed": len(gate_failed),
            },
            "results": results,
        }
    except Exception as e:
        logger.error(f"failed to run MCP tool onboarding self-tests: {e}")
        raise HTTPException(status_code=500, detail=f"运行 MCP 工具接入自测失败: {str(e)}")


@app.post("/api/workspace-context/preview")
async def preview_workspace_context(request: WorkspaceContextPreviewRequest):
    text, metadata = build_workspace_context_block(
        workspace_root=request.workspace_root,
        agent_name=request.agent_name,
        include_agent_profile=request.include_agent_profile,
        include_memory_file=request.include_memory_file,
        include_chatlogs=request.include_chatlogs,
    )
    agent_profile = load_workspace_agent_runtime_profile(
        workspace_root=request.workspace_root,
        agent_name=request.agent_name,
    )
    commands = load_workspace_agent_commands(
        workspace_root=request.workspace_root,
        agent_name=request.agent_name,
    )
    return {
        "ok": bool(text),
        "context_chars": len(text),
        "preview": text[:3000],
        "metadata": metadata,
        "agent_profile": agent_profile,
        "commands": commands,
    }


@app.delete("/api/runtime/providers")
async def clear_runtime_provider_config():
    """Clear runtime-only provider overrides and fall back to backend environment variables."""
    try:
        runtime_config_service.clear_provider_overrides()
        initialize_siliconflow()
        await push_runtime_status_update(event="runtime_providers_cleared", message="Runtime provider overrides cleared")
        return {
            "ok": True,
            "message": "Runtime provider overrides cleared",
            **get_runtime_provider_state(),
        }
    except Exception as e:
        logger.error(f"failed to clear runtime provider config: {e}")
        raise HTTPException(status_code=500, detail=f"????? Provider ????: {str(e)}")


@app.post("/api/runtime/providers")
async def update_runtime_provider_config(request: ProviderRuntimeConfigRequest):
    """????? Provider / Model ?????? .env??????????"""
    try:
        runtime_config_service.update_provider_overrides(
            siliconflow_api_key=request.siliconflow_api_key,
            siliconflow_base_url=request.siliconflow_base_url,
            openrouter_api_key=request.openrouter_api_key,
            openrouter_base_url=request.openrouter_base_url,
            default_model=request.default_model,
            custom_models=[model.model_dump() for model in request.custom_models],
        )
        initialize_siliconflow()
        await push_runtime_status_update(event="runtime_providers_updated", message="Runtime provider config updated")
        return {
            "ok": True,
            "message": "??? Provider ?????",
            **get_runtime_provider_state(),
        }
    except Exception as e:
        logger.error(f"failed to update runtime provider config: {e}")
        raise HTTPException(status_code=500, detail=f"????? Provider ????: {str(e)}")


@app.post("/api/runtime/providers/check")
async def check_runtime_provider_connectivity(request: ProviderConnectivityCheckRequest):
    """Probe provider reachability with the supplied or active runtime credentials."""
    provider = (request.provider or "").strip().lower()
    try:
        if provider == "openrouter":
            return await _probe_openrouter_connectivity(
                api_key=request.api_key,
                base_url=request.base_url,
            )
        if provider == "siliconflow":
            return await _probe_siliconflow_connectivity(
                api_key=request.api_key,
                base_url=request.base_url,
            )
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {request.provider}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Provider connectivity check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Provider connectivity check failed: {str(e)}")


@app.get("/api/runtime/tool-policy")
async def get_runtime_tool_policy():
    try:
        return get_runtime_tool_policy_state()
    except Exception as e:
        logger.error(f"failed to get runtime tool policy: {e}")
        raise HTTPException(status_code=500, detail=f"获取运行时工具策略失败: {str(e)}")


@app.post("/api/runtime/tool-policy")
async def update_runtime_tool_policy(request: ToolPolicyUpdateRequest):
    try:
        runtime_config_service.update_tool_policy(
            enabled=request.enabled,
            default_action=request.default_action,
            tool_actions=request.tool_actions,
            server_actions=request.server_actions,
            system_actions=request.system_actions,
            deny_risky_write_paths=request.deny_risky_write_paths,
        )
        await push_runtime_status_update(event="runtime_tool_policy_updated", message="Runtime tool policy updated")
        return {
            "ok": True,
            "message": "Runtime tool policy updated",
            **get_runtime_tool_policy_state(),
        }
    except Exception as e:
        logger.error(f"failed to update runtime tool policy: {e}")
        raise HTTPException(status_code=500, detail=f"更新运行时工具策略失败: {str(e)}")


@app.get("/api/runtime/auto-tool-routing")
async def get_runtime_auto_tool_routing():
    try:
        return get_runtime_auto_tool_routing_state()
    except Exception as e:
        logger.error(f"failed to get runtime auto tool routing state: {e}")
        raise HTTPException(status_code=500, detail=f"获取自动工具路由状态失败: {str(e)}")


@app.post("/api/runtime/auto-tool-routing")
async def update_runtime_auto_tool_routing(request: AutoToolRoutingUpdateRequest):
    try:
        runtime_config_service.update_auto_tool_routing(request.mode)
        await push_runtime_status_update(
            event="runtime_auto_tool_routing_updated",
            message="Runtime auto tool routing updated",
        )
        return {
            "ok": True,
            "message": "Runtime auto tool routing updated",
            **get_runtime_auto_tool_routing_state(),
        }
    except Exception as e:
        logger.error(f"failed to update runtime auto tool routing state: {e}")
        raise HTTPException(status_code=500, detail=f"????????????: {str(e)}")


@app.get("/api/runtime/memory-plane")
async def get_runtime_memory_plane():
    try:
        return get_runtime_memory_plane_state()
    except Exception as e:
        logger.error(f"failed to get runtime memory plane state: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Memory Plane 运行时状态失败: {str(e)}")


@app.post("/api/runtime/memory-plane")
async def update_runtime_memory_plane(request: MemoryPlaneRuntimeUpdateRequest):
    try:
        state = runtime_config_service.update_memory_plane_runtime(
            absorb_system_op_audit=bool(request.absorb_system_op_audit),
        )
        await push_runtime_status_update(
            event="runtime_memory_plane_updated",
            message="Runtime memory plane state updated",
        )
        return {
            "ok": True,
            "message": "Runtime memory plane state updated",
            **state,
        }
    except Exception as e:
        logger.error(f"failed to update runtime memory plane state: {e}")
        raise HTTPException(status_code=500, detail=f"更新 Memory Plane 运行时状态失败: {str(e)}")


def _summarize_request_result_payload(payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    payload_type = str(payload.get("type", "") or "").strip().lower()
    result = payload.get("result")
    summary: dict[str, Any] = {
        "payload_type": payload_type or "unknown",
        "runtime_status": _request_runtime_status_from_payload(payload),
        "timestamp": payload.get("timestamp"),
        "replayed": bool(payload.get("replayed_from_request_cache")),
        "replay_source": payload.get("replay_source"),
    }

    if payload_type in {"chat_response", "response"}:
        content = str(payload.get("content", "") or "")
        summary["content_preview"] = content[:200]
        summary["model_name"] = payload.get("model_name") or payload.get("model_used")
    elif payload_type in {"tool_result", "resource_result", "prompt_result"}:
        summary["success"] = False if isinstance(result, dict) and result.get("success") is False else True
        summary["result_preview"] = (
            result[:200]
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=False)[:200] if result is not None else ""
        )
    elif payload_type == "tool_blocked":
        summary["reason"] = payload.get("reason")
        summary["suggestion"] = payload.get("suggestion")
    elif payload_type == "error":
        summary["reason"] = payload.get("message")
        summary["error_type"] = payload.get("error_type")

    return summary


def _build_request_runtime_entry_view(request_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    return request_runtime_service.build_entry_view(request_id, entry)


def _estimate_duration_ms(started_at: Any, updated_at: Any) -> Optional[int]:
    return request_runtime_service.estimate_duration_ms(started_at, updated_at)


@app.get("/api/runtime/requests")
async def get_runtime_requests(limit: int = 40, client_id: Optional[str] = None):
    """Return recent request journal items for the task center."""
    try:
        safe_limit = max(1, min(int(limit), 200))
        with request_journal_lock:
            entries = list(request_runtime_journal.items())

        items: List[dict[str, Any]] = []
        for request_id, entry in reversed(entries):
            if not isinstance(entry, dict):
                continue
            view = _build_request_runtime_entry_view(request_id, entry)
            if client_id and client_id not in set(view.get("client_ids", [])):
                continue
            items.append(view)
            if len(items) >= safe_limit:
                break

        status_counts: Dict[str, int] = {}
        for item in items:
            status_key = str(item.get("status", "unknown") or "unknown")
            status_counts[status_key] = status_counts.get(status_key, 0) + 1

        return {
            "ok": True,
            "journal_path": str(REQUEST_JOURNAL_PATH),
            "count": len(items),
            "limit": safe_limit,
            "client_id": client_id,
            "status_counts": status_counts,
            "items": items,
        }
    except Exception as e:
        logger.error(f"failed to get runtime requests: {e}")
        raise HTTPException(status_code=500, detail=f"获取运行时请求账本失败: {str(e)}")


@app.get("/api/agent/capabilities")
async def get_agent_capabilities():
    try:
        return {
            "ok": True,
            "system_operation_capabilities": system_operation_harness.capability_catalog(),
            "task_runtime": agent_task_runtime.snapshot(),
            "operation_audit": operation_audit_log.snapshot(),
            "scheduler": agent_run_scheduler.snapshot(),
        }
    except Exception as e:
        logger.error(f"failed to get agent capabilities: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Agent 能力失败: {str(e)}")


@app.get("/api/agent/tasks")
async def get_agent_tasks(limit: int = 40, client_id: Optional[str] = None):
    try:
        items = agent_task_runtime.list_tasks(limit=limit, client_id=client_id)
        status_counts: Dict[str, int] = {}
        for item in items:
            status_key = str(item.get("status", "unknown") or "unknown")
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
        return {
            "ok": True,
            "count": len(items),
            "status_counts": status_counts,
            "items": items,
        }
    except Exception as e:
        logger.error(f"failed to list agent tasks: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Agent 任务失败: {str(e)}")


@app.get("/api/agent/tasks/{task_id}")
async def get_agent_task(task_id: str):
    task = agent_task_runtime.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Agent task not found: {task_id}")
    return {
        "ok": True,
        "task": task,
    }


@app.post("/api/agent/tasks")
async def create_agent_task(request: AgentTaskCreateRequest):
    try:
        goal = str(request.goal or "").strip()
        if not goal:
            raise HTTPException(status_code=400, detail="goal is required")
        workspace_context = {
            "workspace_root": str(request.workspace_root or "").strip(),
        }
        workspace_agent_profile = load_workspace_agent_runtime_profile(
            workspace_root=workspace_context["workspace_root"],
            agent_name="",
        )
        active_mcp_manager, _ = await _get_effective_mcp_manager(workspace_context)
        visible_tools = active_mcp_manager.get_all_tools() if active_mcp_manager else []
        skill_runtime = _resolve_skill_runtime_for_request(
            requested_skill_ids=[str(skill_id).strip() for skill_id in request.skill_ids if str(skill_id).strip()],
            query=goal,
            workspace_context_config=workspace_context,
            workspace_agent_profile=workspace_agent_profile,
            model_id="",
            available_tools=visible_tools,
            scopes=["agent_task", "system_op", "tool_routing"],
        )
        plan = build_agent_plan(
            user_goal=goal,
            attachments=request.attachments,
            workspace_root=request.workspace_root,
            skill_runtime=skill_runtime,
        )
        task = agent_task_runtime.create_task(
            client_id=str(request.client_id or "").strip(),
            goal=goal,
            plan=plan,
            mode=str(request.mode or "agent").strip() or "agent",
            workspace_root=str(request.workspace_root or "").strip(),
            parent_run_id=str(request.parent_run_id or "").strip(),
            run_kind=str(request.run_kind or "interactive_chat").strip() or "interactive_chat",
            scheduler_id=str(request.scheduler_id or "").strip(),
            trigger={
                "source": "chat_ui",
                "has_attachments": bool(request.attachments),
                "attachment_count": len(request.attachments or []),
            },
        )
        scheduled_for = str(request.scheduled_for or "").strip()
        if scheduled_for:
            task = agent_task_runtime.schedule_task(
                task["task_id"],
                scheduled_for=scheduled_for,
                scheduler_id=str(request.scheduler_id or "").strip(),
            )
            await agent_run_scheduler.register(task["task_id"])
        operation_audit_log.append(
            {
                "task_id": task["task_id"],
                "client_id": request.client_id,
                "event": "task_created",
                "goal": goal,
                "plan": plan,
            }
        )
        if not scheduled_for:
            try:
                await agent_task_executor.start_task(
                    task["task_id"],
                    workspace_root=request.workspace_root,
                    attachments=request.attachments,
                )
            except Exception as exc:
                logger.warning("failed to start agent task executor for %s: %s", task.get("task_id"), exc)
        return {
            "ok": True,
            "task": agent_task_runtime.get_task(task["task_id"]) or task,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"failed to create agent task: {e}")
        raise HTTPException(status_code=500, detail=f"创建 Agent 任务失败: {str(e)}")


@app.post("/api/agent/tasks/{task_id}/cancel")
async def cancel_agent_task(task_id: str):
    try:
        await agent_task_executor.cancel_task(task_id)
        task = agent_task_runtime.cancel_task(task_id, reason="Cancelled from API.")
        operation_audit_log.append(
            {
                "task_id": task_id,
                "event": "task_cancelled",
                "result_summary": task.get("result_summary", {}),
            }
        )
        return {
            "ok": True,
            "task": task,
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent task not found: {task_id}")
    except Exception as e:
        logger.error(f"failed to cancel agent task: {e}")
        raise HTTPException(status_code=500, detail=f"取消 Agent 任务失败: {str(e)}")


@app.get("/api/agent/tasks/{task_id}/replay")
async def get_agent_task_replay(task_id: str, limit: int = 200):
    try:
        replay = agent_task_runtime.get_replay(task_id, limit=limit)
        return {
            "ok": True,
            **replay,
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent task not found: {task_id}")
    except Exception as e:
        logger.error(f"failed to get agent task replay: {e}")
        raise HTTPException(status_code=500, detail=f"获取 Agent 任务回放失败: {str(e)}")


@app.get("/api/agent/operations/approvals")
async def get_agent_operation_approvals(client_id: Optional[str] = None, task_id: Optional[str] = None):
    try:
        items = agent_task_runtime.list_pending_approvals(client_id=client_id, task_id=task_id)
        return {
            "ok": True,
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        logger.error(f"failed to get pending system operation approvals: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统操作审批失败: {str(e)}")


@app.post("/api/agent/tasks/{task_id}/approvals/{approval_id}/approve")
async def approve_agent_task_operation(task_id: str, approval_id: str, request: AgentTaskApprovalDecisionRequest):
    try:
        approval = agent_task_runtime.resolve_approval(task_id, approval_id, approved=True, note=request.note)
        action_type = str(approval.get("action_type", ""))
        payload = dict(approval.get("payload", {}) or {})
        workspace_root = str(request.workspace_root or approval.get("workspace_root", "") or "")
        policy_state = get_runtime_tool_policy_state()
        decision = evaluate_system_operation_policy(
            action_type=action_type,
            payload=payload,
            policy_state=policy_state,
            workspace_root=workspace_root,
            policy_confirmed=True,
        )
        if not decision.allowed:
            task = agent_task_runtime.finish_task(
                task_id,
                status="failed",
                result_summary={"error": decision.reason, "approval_id": approval_id},
                verification={"verified": False, "reason": "approved_operation_denied_by_policy"},
            )
            return {
                "ok": False,
                "approval": approval,
                "task": task,
                "decision": decision.to_payload(),
            }
        step_id = str(approval.get("step_id", ""))
        agent_task_runtime.append_replay_event(
            task_id,
            "approved_system_op_started",
            {
                "approval_id": approval_id,
                "action_type": action_type,
                "payload": payload,
            },
            source_plane="system_op",
            step_id=step_id,
            event_kind="system_op",
        )
        result = await system_operation_harness.execute(
            action_type=action_type,
            payload=payload,
            workspace_root=workspace_root,
        )
        agent_task_runtime.add_observation(
            task_id,
            source_plane="system_op",
            action=action_type,
            observation=result,
            status="running",
            step_id=step_id,
        )
        agent_task_runtime.append_replay_event(
            task_id,
            "approved_system_op_finished",
            {
                "approval_id": approval_id,
                "action_type": action_type,
                "success": bool(result.get("success", False)),
                "result": result,
            },
            source_plane="system_op",
            step_id=step_id,
            event_kind="system_op",
        )
        audit_item = operation_audit_log.append(
            {
                "task_id": task_id,
                "client_id": request.client_id or approval.get("client_id", ""),
                "event": "system_op_executed_after_approval",
                "step_id": step_id,
                "approval_id": approval_id,
                "action_type": action_type,
                "payload": payload,
                "result": {
                    "success": bool(result.get("success", False)),
                    "action_type": result.get("action_type"),
                    "timestamp": result.get("timestamp"),
                },
                "decision": decision.to_payload(),
            }
        )
        try:
            if bool(runtime_config_service.get_memory_plane_runtime_state().get("absorb_system_op_audit", True)):
                memory_control_plane.register_system_operation_audit(
                    task_id=task_id,
                    client_id=str(request.client_id or approval.get("client_id", "")),
                    step_id=step_id,
                    action_type=action_type,
                    payload=payload,
                    result=result,
                    decision=decision.to_payload(),
                    audit=audit_item,
                )
        except Exception:
            logger.exception("failed to ingest approved system_op audit")
        if step_id:
            if bool(result.get("success", False)):
                agent_task_runtime.update_step(task_id, step_id, status="completed", result_summary=result)
            else:
                error = str(result.get("stderr") or result.get("error") or "System operation failed.")
                agent_task_runtime.update_step(task_id, step_id, status="failed", result_summary=result, error=error)
                task = agent_task_runtime.finish_task(
                    task_id,
                    status="failed",
                    result_summary={"error": error, "action_type": action_type, "result": result},
                    verification={"verified": False, "reason": "approved_system_op_failed"},
                )
                return {
                    "ok": False,
                    "approval": approval,
                    "result": result,
                    "audit": audit_item,
                    "task": task,
                }
        await agent_task_executor.resume_after_approval(
            task_id,
            workspace_root=workspace_root,
            attachments=request.attachments,
        )
        return {
            "ok": True,
            "approval": approval,
            "result": result,
            "audit": audit_item,
            "task": agent_task_runtime.get_task(task_id),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"failed to approve system operation: {e}")
        raise HTTPException(status_code=500, detail=f"审批系统操作失败: {str(e)}")


@app.post("/api/agent/tasks/{task_id}/approvals/{approval_id}/reject")
async def reject_agent_task_operation(task_id: str, approval_id: str, request: AgentTaskApprovalDecisionRequest):
    try:
        approval = agent_task_runtime.resolve_approval(task_id, approval_id, approved=False, note=request.note)
        task = agent_task_runtime.finish_task(
            task_id,
            status="cancelled",
            result_summary={
                "reason": "System operation approval rejected by user.",
                "approval_id": approval_id,
                "action_type": approval.get("action_type", ""),
            },
            verification={"verified": False, "reason": "approval_rejected"},
        )
        operation_audit_log.append(
            {
                "task_id": task_id,
                "client_id": request.client_id or approval.get("client_id", ""),
                "event": "system_op_approval_rejected",
                "approval_id": approval_id,
                "action_type": approval.get("action_type", ""),
                "payload": approval.get("payload", {}),
            }
        )
        return {
            "ok": True,
            "approval": approval,
            "task": task,
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"failed to reject system operation: {e}")
        raise HTTPException(status_code=500, detail=f"拒绝系统操作失败: {str(e)}")


@app.get("/api/agent/operations/audit")
async def get_system_operation_audit(limit: int = 50, task_id: Optional[str] = None):
    try:
        return {
            "ok": True,
            "items": operation_audit_log.recent(limit=limit, task_id=task_id),
            "snapshot": operation_audit_log.snapshot(),
        }
    except Exception as e:
        logger.error(f"failed to get system operation audit: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统操作审计失败: {str(e)}")


@app.post("/api/system-ops/execute")
async def execute_system_operation(request: SystemOperationRequest):
    try:
        policy_state = get_runtime_tool_policy_state()
        decision = evaluate_system_operation_policy(
            action_type=request.action_type,
            payload=request.payload,
            policy_state=policy_state,
            workspace_root=request.workspace_root,
            policy_confirmed=bool(request.policy_confirmed),
        )
        if not decision.allowed:
            payload = {
                "ok": False,
                "blocked": True,
                "action_type": request.action_type,
                "task_id": request.task_id,
                "decision": decision.to_payload(),
            }
            operation_audit_log.append(
                {
                    "task_id": request.task_id,
                    "client_id": request.client_id,
                    "event": "system_op_blocked",
                    "action_type": request.action_type,
                    "payload": request.payload,
                    "decision": payload["decision"],
                }
            )
            return payload

        result = await system_operation_harness.execute(
            action_type=request.action_type,
            payload=request.payload,
            workspace_root=request.workspace_root,
        )
        if request.task_id:
            agent_task_runtime.add_observation(
                request.task_id,
                source_plane="system_op",
                action=request.action_type,
                observation=result,
                status="running",
                step_id="manual-system-op",
            )
        audit_item = operation_audit_log.append(
            {
                "task_id": request.task_id,
                "client_id": request.client_id,
                "event": "system_op_executed",
                "action_type": request.action_type,
                "payload": request.payload,
                "result": {
                    "success": bool(result.get("success", False)),
                    "action_type": result.get("action_type"),
                    "timestamp": result.get("timestamp"),
                },
                "decision": decision.to_payload(),
            }
        )
        return {
            "ok": True,
            "action_type": request.action_type,
            "task_id": request.task_id,
            "decision": decision.to_payload(),
            "result": result,
            "audit": audit_item,
        }
    except Exception as e:
        logger.error(f"failed to execute system operation: {e}")
        raise HTTPException(status_code=500, detail=f"执行系统操作失败: {str(e)}")


@app.get("/api/system/bootstrap")
async def get_system_bootstrap():
    """统一返回前端启动所需的系统状态快照。"""
    try:
        runtime_state = get_runtime_provider_state()
        tools = mcp_manager.get_all_tools() if mcp_manager else []
        servers_payload = mcp_manager.get_server_status() if (mcp_manager and hasattr(mcp_manager, "get_server_status")) else {}
        connected = [s["name"] for s in (mcp_manager.servers if mcp_manager else []) if s.get("status") == "connected"]
        audit = (
            build_runtime_audit_report(
                {"mcpServers": getattr(mcp_manager, "config", {})},
                {"servers": servers_payload},
                {"tools": tools},
            )
            if mcp_manager
            else {"ok": False, "error": "MCP管理器不可用"}
        )
        onboarding_audit = _build_mcp_tool_onboarding_audit()

        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "providers": {
                **runtime_state["providers"],
            },
            "models": {
                "default": runtime_state["models"]["default"],
                "available": runtime_state["models"]["available"],
                "count": runtime_state["models"]["count"],
            },
            "agent_skills": {
                "count": len(agent_skills_registry.skills),
                "skills": agent_skills_registry.list_summaries(),
                "roots": agent_skills_registry.get_skill_roots_summary(),
                "failed": list(agent_skills_registry.failed),
            },
            "mcp": {
                "available": bool(mcp_manager),
                "servers": servers_payload,
                "connected_servers": connected,
                "tools": tools,
                "tools_count": len(tools),
                "audit": audit,
                "tool_onboarding_audit": onboarding_audit,
            },
            "tem": tem.get_mode_state(),
            "tool_policy": get_runtime_tool_policy_state(),
            "auto_tool_routing": get_runtime_auto_tool_routing_state(),
            "memory_plane": memory_control_plane.get_runtime_snapshot(),
        }
    except Exception as e:
        logger.error(f"failed to get system bootstrap: {e}")
        raise HTTPException(status_code=500, detail=f"获取系统 bootstrap 失败: {str(e)}")


@app.get("/api/agent-skills")
async def get_agent_skills():
    """Return explicit human-authored agent skills."""
    try:
        return {
            "ok": True,
            "count": len(agent_skills_registry.skills),
            "skills": agent_skills_registry.list_summaries(),
            "roots": agent_skills_registry.get_skill_roots_summary(),
            "failed": list(agent_skills_registry.failed),
        }
    except Exception as e:
        logger.error(f"failed to get agent skills: {e}")
        raise HTTPException(status_code=500, detail=f"获取 agent skills 失败: {str(e)}")


@app.post("/api/agent-skills/reload")
async def reload_agent_skills():
    """Reload skill registry from disk."""
    try:
        result = agent_skills_registry.reload()
        await push_runtime_status_update(
            event="agent_skills_reloaded",
            message=f"Agent skills reloaded: {result.get('count', 0)} available",
        )
        return {
            "ok": True,
            **result,
            "skills": agent_skills_registry.list_summaries(),
            "roots": agent_skills_registry.get_skill_roots_summary(),
        }
    except Exception as e:
        logger.error(f"failed to reload agent skills: {e}")
        raise HTTPException(status_code=500, detail=f"重载 agent skills 失败: {str(e)}")


@app.get("/api/agent-skills/external-config")
async def get_agent_skills_external_config():
    try:
        return {
            "ok": True,
            **agent_skills_registry.get_external_skill_config(),
            "roots": agent_skills_registry.get_skill_roots_summary(),
        }
    except Exception as exc:
        logger.error(f"failed to get external skill config: {exc}")
        raise HTTPException(status_code=500, detail=f"获取 external skill config 失败: {str(exc)}")


@app.post("/api/agent-skills/external-config")
async def update_agent_skills_external_config(request: AgentSkillsExternalConfigRequest):
    try:
        config = agent_skills_registry.save_external_skill_config(request.external_skill_dirs)
        result = agent_skills_registry.reload()
        await push_runtime_status_update(
            event="agent_skills_external_config_updated",
            message=f"External skill dirs updated: {len(config.get('external_skill_dirs', []))}",
        )
        return {
            "ok": True,
            **config,
            **result,
            "skills": agent_skills_registry.list_summaries(),
            "roots": agent_skills_registry.get_skill_roots_summary(),
        }
    except Exception as exc:
        logger.error(f"failed to update external skill config: {exc}")
        raise HTTPException(status_code=500, detail=f"更新 external skill config 失败: {str(exc)}")


@app.post("/api/agent-skills/runtime")
async def resolve_agent_skills_runtime(payload: Dict[str, Any]):
    """Resolve authored skill runtime overlays for the current request."""
    try:
        requested_skill_ids = [
            str(skill_id).strip()
            for skill_id in payload.get("skill_ids", [])
            if str(skill_id).strip()
        ]
        query = str(payload.get("query", "") or "")
        workspace_context = payload.get("workspace_context") if isinstance(payload.get("workspace_context"), dict) else {}
        model_id = str(payload.get("model_id", "") or "").strip()
        scopes = [
            str(scope).strip()
            for scope in payload.get("scopes", [])
            if str(scope).strip()
        ] or ["chat"]
        workspace_agent_profile = load_workspace_agent_runtime_profile(
            workspace_root=str(workspace_context.get("workspace_root", "") or ""),
            agent_name=str(workspace_context.get("agent_name", "") or ""),
        )
        workspace_agent_profile = _merge_workspace_agent_profile_with_session_overrides(
            workspace_agent_profile,
            workspace_context,
        )
        active_mcp_manager, _ = await _get_effective_mcp_manager(workspace_context)
        tools = active_mcp_manager.get_all_tools() if active_mcp_manager else []
        runtime = _resolve_skill_runtime_for_request(
            requested_skill_ids=requested_skill_ids,
            query=query,
            workspace_context_config=workspace_context,
            workspace_agent_profile=workspace_agent_profile,
            model_id=model_id,
            available_tools=tools,
            scopes=scopes,
        )
        merged_profile = _merge_workspace_profile_with_skill_runtime(workspace_agent_profile, runtime)
        return {
            "ok": True,
            "runtime": runtime,
            "workspace_agent_profile": merged_profile,
        }
    except Exception as exc:
        logger.error(f"failed to resolve agent skill runtime: {exc}")
        raise HTTPException(status_code=500, detail=f"解析 agent skill runtime 失败: {str(exc)}")

@app.get("/api/mcp/tools")
async def get_mcp_tools():
    """获取MCP工具列表"""
    if not mcp_manager:
        return {"tools": [], "error": "MCP管理器不可用"}
    
    try:
        tools = mcp_manager.get_all_tools()
        return {"tools": tools}
    except Exception as e:
        logger.error(f"failed to get MCP tools: {e}")
        return {"tools": [], "error": str(e)}

@app.get("/api/mcp/resources")
async def get_mcp_resources():
    """获取MCP资源列表"""
    if not mcp_manager:
        return {"resources": [], "error": "MCP管理器不可用"}
    
    try:
        resources = mcp_manager.get_all_resources()
        return {"resources": resources}
    except Exception as e:
        logger.error(f"failed to get MCP resources: {e}")
        return {"resources": [], "error": str(e)}

@app.get("/api/mcp/prompts")
async def get_mcp_prompts():
    """获取MCP提示词列表"""
    if not mcp_manager:
        return {"prompts": [], "error": "MCP管理器不可用"}
    
    try:
        prompts = mcp_manager.get_all_prompts()
        return {"prompts": prompts}
    except Exception as e:
        logger.error(f"failed to get MCP prompts: {e}")
        return {"prompts": [], "error": str(e)}

@app.get("/api/mcp/servers")
async def get_mcp_servers():
    """获取MCP服务器状态"""
    if not mcp_manager:
        return {"servers": {}, "error": "MCP管理器不可用"}
    
    try:
        if hasattr(mcp_manager, 'get_server_status'):
            servers = mcp_manager.get_server_status()
        else:
            servers = {}
        return {"servers": servers}
    except Exception as e:
        logger.error(f"failed to get MCP server status: {e}")
        return {"servers": {}, "error": str(e)}


@app.get("/api/mcp/config")
async def get_mcp_config():
    """Return persisted MCP server configuration for the settings UI."""
    try:
        return list_mcp_server_configs()
    except Exception as e:
        logger.error(f"failed to get MCP config: {e}")
        raise HTTPException(status_code=500, detail=f"获取MCP配置失败: {str(e)}")


@app.post("/api/mcp/config")
async def upsert_mcp_config(request: MCPServerConfigRequest):
    """Create or update a custom MCP server config, then reload runtime MCP clients."""
    try:
        saved = upsert_mcp_server_config(request)
        reload_ok = await initialize_mcp_manager()
        await push_runtime_status_update(
            event="mcp_config_updated",
            message=f"MCP server '{saved['name']}' saved",
        )
        return {
            "ok": True,
            "message": f"MCP server '{saved['name']}' saved",
            "saved": saved,
            "reload_ok": reload_ok,
            "runtime": mcp_manager.get_server_status() if mcp_manager else {},
        }
    except MCPConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"failed to save MCP config: {e}")
        raise HTTPException(status_code=500, detail=f"保存MCP配置失败: {str(e)}")


@app.delete("/api/mcp/config/{server_name}")
async def delete_mcp_config(server_name: str):
    """Delete a custom MCP server config, then reload runtime MCP clients."""
    try:
        deleted = delete_mcp_server_config(server_name)
        reload_ok = await initialize_mcp_manager()
        await push_runtime_status_update(
            event="mcp_config_deleted",
            message=f"MCP server '{deleted['name']}' deleted",
        )
        return {
            "ok": True,
            "message": f"MCP server '{deleted['name']}' deleted",
            "deleted": deleted,
            "reload_ok": reload_ok,
            "runtime": mcp_manager.get_server_status() if mcp_manager else {},
        }
    except MCPConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"failed to delete MCP config: {e}")
        raise HTTPException(status_code=500, detail=f"删除MCP配置失败: {str(e)}")


@app.get("/api/mcp/audit")
async def get_mcp_audit():
    """获取当前 MCP 运行时官方接入审计结果"""
    if not mcp_manager:
        return {"ok": False, "error": "MCP管理器不可用"}

    try:
        config = {"mcpServers": getattr(mcp_manager, "config", {})}
        runtime_servers = {"servers": mcp_manager.get_server_status()}
        runtime_tools = {"tools": mcp_manager.get_all_tools()}
        return build_runtime_audit_report(config, runtime_servers, runtime_tools)
    except Exception as e:
        logger.error(f"failed to get MCP audit report: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/memory/{client_id}")
async def get_memory_status(client_id: str):
    """获取指定客户端的上下文记忆状态"""
    return context_engine.get_memory_status(client_id)

@app.delete("/api/memory/{client_id}")
async def clear_memory(client_id: str):
    """清除指定客户端的对话记忆"""
    context_engine.remove_memory(client_id)
    return {"status": "cleared", "client_id": client_id}

@app.get("/api/memory")
async def list_all_memories():
    """列出所有活跃的对话记忆"""
    memories = {}
    for cid, mem in context_engine.memories.items():
        memories[cid] = {
            "message_count": len(mem.messages),
            "has_summary": bool(mem.summary),
            "long_term_facts": len(mem.long_term_facts),
            "estimated_tokens": mem.get_total_tokens(),
        }
    return {"active_memories": memories, "count": len(memories)}


@app.get("/api/memory-plane")
async def get_memory_plane_status():
    """获取当前 Memory Control Plane 运行时快照。"""
    return {
        "ok": True,
        "snapshot": memory_control_plane.get_runtime_snapshot(),
    }


@app.get("/api/memory-plane/traces")
async def get_memory_plane_traces(limit: int = 20):
    """读取最近的 Memory Control Plane traces。"""
    trace_path = project_root / "artifacts" / "memory" / "memory_plane_traces.jsonl"
    records = []
    if trace_path.exists():
        with open(trace_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    safe_limit = max(1, min(limit, 200))
    return {
        "ok": True,
        "trace_path": str(trace_path),
        "count": len(records),
        "items": records[-safe_limit:],
    }


@app.get("/api/memory-plane/ledger")
async def get_memory_plane_ledger(limit: int = 20):
    """Return recent governance, causal, shadow replay, and rollback ledger events."""
    ledger_snapshot = memory_control_plane.get_ledger_snapshot(limit)
    return {
        "ok": True,
        **ledger_snapshot,
    }


@app.post("/api/memory-plane/reset")
async def reset_memory_plane_state(request: MemoryPlaneResetRequest):
    """Reset router/runtime ledger state for clean internal evaluations."""
    try:
        if request.router:
            return reset_memory_plane_runtime(clear_traces=request.traces)
        return {"ok": True, "router_reset": False, "trace_reset": False}
    except Exception as e:
        logger.error(f"Memory plane reset failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory plane reset failed: {str(e)}")


@app.post("/api/regression-sandbox/begin")
async def begin_regression_sandbox(request: RegressionSandboxBeginRequest):
    """
    Capture a regression sandbox snapshot so real smoke checks can restore
    Memory/TEM/runtime artifacts after execution.
    """
    try:
        return _begin_regression_sandbox(
            label=str(request.label or "browser_runtime_smoke"),
            include_uploads=bool(request.include_uploads),
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Regression sandbox collision: {exc}")
    except Exception as exc:
        logger.error("Regression sandbox begin failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Regression sandbox begin failed: {exc}")


@app.post("/api/regression-sandbox/restore")
async def restore_regression_sandbox(request: RegressionSandboxRestoreRequest):
    """
    Restore a previously captured regression sandbox snapshot and clear any
    temporary workspace MCP overlays created during the smoke run.
    """
    return await _restore_regression_sandbox(request.sandbox_id)


@app.post("/api/memory-plane/evaluate")
async def evaluate_memory_policy(request: PolicyEvaluationRequest):
    """Evaluate memory-aware routing and governance for a query without calling the chat API."""
    try:
        filtered_tools, _ = _get_filtered_tools(request.candidate_tools)

        client_id = request.client_id or f"policy_eval_{uuid.uuid4().hex[:8]}"
        evaluation = memory_control_plane.build_policy_evaluator_view(
            client_id=client_id,
            query=request.query,
            tool_catalog=filtered_tools,
            context_engine=context_engine,
            tem=tem,
            dry_run=request.dry_run,
            feature_mask=request.feature_mask,
        )
        recommended_tools = evaluation.get("recommended_tools", [])
        expected_tool = (request.expected_tool or "").strip()
        return {
            "ok": True,
            "expected_tool": expected_tool,
            "top1_match": bool(expected_tool and recommended_tools and recommended_tools[0] == expected_tool),
            "topk_match": bool(expected_tool and expected_tool in recommended_tools),
            **evaluation,
        }
    except Exception as e:
        logger.error(f"Memory policy evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory policy evaluation failed: {str(e)}")


@app.post("/api/memory-plane/evaluate_batch")
async def evaluate_memory_policy_batch(request: PolicyEvaluationBatchRequest):
    """Evaluate a batch of routing cases with optional dry-run semantics for reproducible experiments."""
    try:
        tools = mcp_manager.get_all_tools() if mcp_manager else []
        all_tool_names = {str(tool.get("name", "")).strip() for tool in tools if str(tool.get("name", "")).strip()}
        items = []
        for index, case in enumerate(request.cases):
            filtered_tools = tools
            if case.candidate_tools:
                allowed = {name.strip() for name in case.candidate_tools if name.strip()}
                filtered_tools = [tool for tool in tools if str(tool.get("name", "")).strip() in allowed]
            client_id = case.client_id or f"policy_batch_{index}_{uuid.uuid4().hex[:6]}"
            evaluation = memory_control_plane.build_policy_evaluator_view(
                client_id=client_id,
                query=case.query,
                tool_catalog=filtered_tools,
                context_engine=context_engine,
                tem=tem,
                dry_run=request.dry_run,
                feature_mask=request.feature_mask,
            )
            expected_tool = (case.expected_tool or "").strip()
            items.append(
                _build_case_result(
                    evaluation=evaluation,
                    case_id=case.id or f"case_{index}",
                    expected_tool=expected_tool,
                    candidate_pool_size=len(case.candidate_tools or all_tool_names),
                )
            )

        feature_groups = dict(memory_control_plane.get_runtime_snapshot().get("routing", {}).get("feature_groups", {}))
        per_feature: Dict[str, Dict[str, Any]] = {}
        for feature_group in feature_groups:
            masked_request = PolicyEvaluationBatchRequest(
                cases=request.cases,
                dry_run=request.dry_run,
                feature_mask={feature_group: False},
            )
            masked_items: List[dict[str, Any]] = []
            for index, case in enumerate(masked_request.cases):
                filtered_tools = tools
                if case.candidate_tools:
                    allowed = {name.strip() for name in case.candidate_tools if name.strip()}
                    filtered_tools = [tool for tool in tools if str(tool.get("name", "")).strip() in allowed]
                client_id = case.client_id or f"policy_batch_masked_{feature_group}_{index}_{uuid.uuid4().hex[:6]}"
                evaluation = memory_control_plane.build_policy_evaluator_view(
                    client_id=client_id,
                    query=case.query,
                    tool_catalog=filtered_tools,
                    context_engine=context_engine,
                    tem=tem,
                    dry_run=masked_request.dry_run,
                    feature_mask=masked_request.feature_mask,
                )
                expected_tool = (case.expected_tool or "").strip()
                masked_items.append(
                    _build_case_result(
                        evaluation=evaluation,
                        case_id=case.id or f"case_{index}",
                        expected_tool=expected_tool,
                        candidate_pool_size=len(case.candidate_tools or all_tool_names),
                    )
                )
            full_top1 = sum(1 for item in items if item.get("top1_match"))
            masked_top1 = sum(1 for item in masked_items if item.get("top1_match"))
            full_topk = sum(1 for item in items if item.get("topk_match"))
            masked_topk = sum(1 for item in masked_items if item.get("topk_match"))
            flip_count = sum(
                1
                for base_item, masked_item in zip(items, masked_items)
                if (base_item.get("recommended_tools") or [])[:1] != (masked_item.get("recommended_tools") or [])[:1]
            )
            per_feature[feature_group] = {
                "cases": len(items),
                "masked_top1_accuracy": round(masked_top1 / len(masked_items), 4) if masked_items else 0.0,
                "masked_topk_recall": round(masked_topk / len(masked_items), 4) if masked_items else 0.0,
                "top1_gain": round((full_top1 - masked_top1) / len(items), 4) if items else 0.0,
                "topk_gain": round((full_topk - masked_topk) / len(items), 4) if items else 0.0,
                "mean_score_delta": round(
                    sum(float(base.get("top_score", 0.0)) - float(masked.get("top_score", 0.0)) for base, masked in zip(items, masked_items)) / len(items),
                    4,
                ) if items else 0.0,
                "top1_flip_rate": round(flip_count / len(items), 4) if items else 0.0,
                "mask": {feature_group: False},
            }

        return {
            "ok": True,
            "dry_run": request.dry_run,
            "feature_mask": request.feature_mask,
            "cases": items,
            "summary": _summarize_batch_items(items),
            "per_mode": _build_mode_stats(items),
            "per_feature": per_feature,
            "calibration": _build_calibration(items),
        }
    except Exception as e:
        logger.error(f"Memory policy batch evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory policy batch evaluation failed: {str(e)}")


@app.post("/api/memory-plane/shadow_replay_batch")
async def evaluate_memory_shadow_replay_batch(request: ShadowReplayBatchRequest):
    """Run full-vs-masked shadow replay over a batch and report top1 flips and score deltas."""
    try:
        tools = mcp_manager.get_all_tools() if mcp_manager else []
        items: List[dict[str, Any]] = []
        total_flip_count = 0
        for index, case in enumerate(request.cases):
            filtered_tools = tools
            if case.candidate_tools:
                allowed = {name.strip() for name in case.candidate_tools if name.strip()}
                filtered_tools = [tool for tool in tools if str(tool.get("name", "")).strip() in allowed]
            base_client_id = case.client_id or f"shadow_replay_base_{index}_{uuid.uuid4().hex[:6]}"
            masked_client_id = f"{base_client_id}_masked"
            full_eval = memory_control_plane.build_policy_evaluator_view(
                client_id=base_client_id,
                query=case.query,
                tool_catalog=filtered_tools,
                context_engine=context_engine,
                tem=tem,
                dry_run=request.dry_run,
            )
            masked_eval = memory_control_plane.build_policy_evaluator_view(
                client_id=masked_client_id,
                query=case.query,
                tool_catalog=filtered_tools,
                context_engine=context_engine,
                tem=tem,
                dry_run=request.dry_run,
                feature_mask=request.feature_mask,
            )
            full_top = (full_eval.get("recommended_tools") or [""])[0] if full_eval.get("recommended_tools") else ""
            masked_top = (masked_eval.get("recommended_tools") or [""])[0] if masked_eval.get("recommended_tools") else ""
            flip = bool(full_top != masked_top)
            total_flip_count += 1 if flip else 0
            full_top_score = float(full_eval.get("top_score", 0.0))
            masked_top_score = float(masked_eval.get("top_score", 0.0))
            shadow_replay = memory_control_plane._build_shadow_replay(
                selected_tool=full_top,
                plan={"routing": {"scores": full_eval.get("routing_scores", []), "selected_tools": full_eval.get("recommended_tools", [])}},
                counterfactual_routing={"scores": masked_eval.get("routing_scores", []), "selected_tools": masked_eval.get("recommended_tools", [])},
                feature_mask=request.feature_mask,
            )
            items.append(
                {
                    "id": case.id or f"case_{index}",
                    "query": case.query,
                    "expected_tool": case.expected_tool or "",
                    "selected_tool_full": full_top,
                    "selected_tool_masked": masked_top,
                    "top1_flip": flip,
                    "top1_flip_to_expected": bool(case.expected_tool and masked_top == case.expected_tool and full_top != case.expected_tool),
                    "full_top_score": round(full_top_score, 4),
                    "masked_top_score": round(masked_top_score, 4),
                    "top_score_delta": round(full_top_score - masked_top_score, 4),
                    "shadow_replay": shadow_replay,
                }
            )
        total = len(items)
        return {
            "ok": True,
            "dry_run": request.dry_run,
            "feature_mask": request.feature_mask,
            "cases": items,
            "summary": {
                "total": total,
                "top1_flip_rate": round(total_flip_count / total, 4) if total else 0.0,
                "mean_top_score_delta": round(sum(item["top_score_delta"] for item in items) / total, 4) if total else 0.0,
            },
        }
    except Exception as e:
        logger.error(f"Memory shadow replay batch evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory shadow replay batch evaluation failed: {str(e)}")


@app.post("/api/memory-plane/recovery_utility")
async def evaluate_memory_recovery_utility(request: RecoveryUtilityRequest):
    """Evaluate governance execution and rollback recovery utility on a controlled snapshot."""
    snapshot = memory_control_plane.snapshot_runtime_state(context_engine, tem)
    try:
        base_items: List[dict[str, Any]] = []
        governed_items: List[dict[str, Any]] = []
        rollback_items: List[dict[str, Any]] = []
        tools = mcp_manager.get_all_tools() if mcp_manager else []
        for index, case in enumerate(request.cases):
            filtered_tools = tools
            if case.candidate_tools:
                allowed = {name.strip() for name in case.candidate_tools if name.strip()}
                filtered_tools = [tool for tool in tools if str(tool.get("name", "")).strip() in allowed]

            base_client_id = f"{request.client_id_prefix}_base_{index}"
            governed_client_id = f"{request.client_id_prefix}_governed_{index}"
            rollback_client_id = f"{request.client_id_prefix}_rollback_{index}"
            expected_tool = (case.expected_tool or "").strip()

            base_eval = memory_control_plane.build_policy_evaluator_view(
                client_id=base_client_id,
                query=case.query,
                tool_catalog=filtered_tools,
                context_engine=context_engine,
                tem=tem,
                dry_run=True,
            )
            base_items.append(
                _build_case_result(
                    evaluation=base_eval,
                    case_id=case.id or f"case_{index}",
                    expected_tool=expected_tool,
                    candidate_pool_size=len(case.candidate_tools or []),
                )
            )

            governed_eval = memory_control_plane.build_policy_evaluator_view(
                client_id=governed_client_id,
                query=case.query,
                tool_catalog=filtered_tools,
                context_engine=context_engine,
                tem=tem,
                dry_run=False,
            )
            governed_items.append(
                _build_case_result(
                    evaluation=governed_eval,
                    case_id=case.id or f"case_{index}",
                    expected_tool=expected_tool,
                    candidate_pool_size=len(case.candidate_tools or []),
                )
            )

            memory_control_plane.rollback_recent_governance(tem, reason="phase4_recovery_utility")

            rollback_eval = memory_control_plane.build_policy_evaluator_view(
                client_id=rollback_client_id,
                query=case.query,
                tool_catalog=filtered_tools,
                context_engine=context_engine,
                tem=tem,
                dry_run=True,
            )
            rollback_items.append(
                _build_case_result(
                    evaluation=rollback_eval,
                    case_id=case.id or f"case_{index}",
                    expected_tool=expected_tool,
                    candidate_pool_size=len(case.candidate_tools or []),
                )
            )
        return {
            "ok": True,
            "baseline": {
                "summary": _summarize_batch_items(base_items),
                "cases": base_items,
            },
            "post_governance": {
                "summary": _summarize_batch_items(governed_items),
                "cases": governed_items,
            },
            "post_rollback": {
                "summary": _summarize_batch_items(rollback_items),
                "cases": rollback_items,
            },
            "recovery_utility": {
                "governance_top1_delta": round(
                    _summarize_batch_items(governed_items)["top1_accuracy"] - _summarize_batch_items(base_items)["top1_accuracy"],
                    4,
                ),
                "rollback_top1_delta_vs_governance": round(
                    _summarize_batch_items(rollback_items)["top1_accuracy"] - _summarize_batch_items(governed_items)["top1_accuracy"],
                    4,
                ),
                "rollback_restoration_gap_vs_baseline": round(
                    _summarize_batch_items(rollback_items)["top1_accuracy"] - _summarize_batch_items(base_items)["top1_accuracy"],
                    4,
                ),
            },
        }
    except Exception as e:
        logger.error(f"Memory recovery utility evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory recovery utility evaluation failed: {str(e)}")
    finally:
        if request.restore_state_after_run:
            memory_control_plane.restore_runtime_state(snapshot, context_engine, tem)


@app.post("/api/memory-plane/guard_tradeoff")
async def evaluate_memory_guard_tradeoff(request: GuardTradeoffRequest):
    """Evaluate avoided-failure vs false-block tradeoff using labeled guard replay cases."""
    snapshot = memory_control_plane.snapshot_runtime_state(context_engine, tem)
    try:
        if request.reset_tem_before_run:
            tem.reset_memory(recipes=False, guards=True, traces=True, pending=True)
        tem.set_mode(request.tem_mode)

        def run_case(case: GuardTradeoffCase, case_index: int) -> dict[str, Any]:
            blocked_calls = 0
            false_blocks = 0
            avoided_failures = 0
            missed_failures = 0
            successful_steps = 0
            step_records: List[dict[str, Any]] = []
            for step_index, step in enumerate(case.steps):
                client_id = f"guard_tradeoff_{case_index}_{step_index}"
                preflight = tem.before_tool_call(
                    step.tool,
                    step.arguments,
                    step.server,
                    task_description=case.task,
                )
                if preflight:
                    blocked_calls += 1
                    if step.should_succeed:
                        false_blocks += 1
                    else:
                        avoided_failures += 1
                    step_records.append(
                        {
                            "tool": step.tool,
                            "server": step.server,
                            "blocked": True,
                            "expected_success": step.should_succeed,
                            "block_source": preflight.get("block_source", ""),
                            "guard_id": preflight.get("guard_id", ""),
                        }
                    )
                    continue

                if step.should_succeed:
                    result_payload: Any = {"success": True, "content": step.arguments}
                    tem.after_tool_call(
                        client_id=client_id,
                        tool_name=step.tool,
                        arguments=step.arguments,
                        result=result_payload,
                        success=True,
                        server_name=step.server,
                        task_description=case.task,
                    )
                    successful_steps += 1
                    step_records.append(
                        {
                            "tool": step.tool,
                            "server": step.server,
                            "blocked": False,
                            "expected_success": True,
                            "actual_success": True,
                        }
                    )
                else:
                    result_payload = {
                        "success": False,
                        "error_type": step.error_type or "ToolError",
                        "error": step.error_message or "",
                    }
                    tem.after_tool_call(
                        client_id=client_id,
                        tool_name=step.tool,
                        arguments=step.arguments,
                        result=result_payload,
                        success=False,
                        error_type=step.error_type or "ToolError",
                        error_message=step.error_message or "",
                        server_name=step.server,
                        task_description=case.task,
                    )
                    missed_failures += 1
                    step_records.append(
                        {
                            "tool": step.tool,
                            "server": step.server,
                            "blocked": False,
                            "expected_success": False,
                            "actual_success": False,
                            "error_type": step.error_type or "ToolError",
                        }
                    )
            return {
                "id": case.id or f"case_{case_index}",
                "task": case.task,
                "category": case.category or "",
                "expected_success": case.expected_success,
                "blocked_calls": blocked_calls,
                "false_blocks": false_blocks,
                "avoided_failures": avoided_failures,
                "missed_failures": missed_failures,
                "successful_steps": successful_steps,
                "step_records": step_records,
            }

        warmup_results = [run_case(case, index) for index, case in enumerate(request.warmup_cases)]
        eval_results = [run_case(case, index + len(warmup_results)) for index, case in enumerate(request.evaluation_cases)]
        total = len(eval_results)
        total_false_blocks = sum(item["false_blocks"] for item in eval_results)
        total_avoided_failures = sum(item["avoided_failures"] for item in eval_results)
        total_missed_failures = sum(item["missed_failures"] for item in eval_results)
        expected_success_cases = sum(1 for case in request.evaluation_cases if case.expected_success)
        expected_failure_cases = sum(1 for case in request.evaluation_cases if not case.expected_success)
        return {
            "ok": True,
            "tem_mode": request.tem_mode,
            "warmup_cases": warmup_results,
            "evaluation_cases": eval_results,
            "summary": {
                "total_cases": total,
                "avoided_failure_count": total_avoided_failures,
                "false_block_count": total_false_blocks,
                "missed_failure_count": total_missed_failures,
                "avoided_failure_rate": round(total_avoided_failures / max(expected_failure_cases, 1), 4),
                "false_block_rate": round(total_false_blocks / max(expected_success_cases, 1), 4),
                "guard_precision_proxy": round(total_avoided_failures / max(total_avoided_failures + total_false_blocks, 1), 4),
            },
        }
    except Exception as e:
        logger.error(f"Memory guard tradeoff evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory guard tradeoff evaluation failed: {str(e)}")
    finally:
        if request.restore_state_after_run:
            memory_control_plane.restore_runtime_state(snapshot, context_engine, tem)


@app.post("/api/memory-plane/autonomous_trajectory")
async def evaluate_memory_autonomous_trajectory(request: AutonomousTrajectoryRequest):
    """
    Evaluate multi-step autonomous tool selection with real MCP execution.

    Important:
    - the router selects a tool for each step from the provided candidate set
    - the selected tool is actually executed when `execute_selected_tool=true`
    - argument policy can be `gold`, `controlled`, `controlled_with_fallback`,
      `memory_conditioned`, or `memory_conditioned_with_fallback`
    - controlled mode is benchmark-template-grounded
    - memory_conditioned mode is still benchmark-grounded, but it reuses explicit
      per-case argument state accumulated across prior steps
    """
    snapshot = memory_control_plane.snapshot_runtime_state(context_engine, tem)
    try:
        argument_policy_mode = normalize_argument_policy_mode(request.argument_policy_mode)
        if request.reset_tem_before_run:
            tem.reset_memory(recipes=False, guards=False, traces=True, pending=True)
        tem.set_mode(request.tem_mode)

        all_tools = mcp_manager.get_all_tools() if mcp_manager else []
        all_tool_by_name = {
            str(tool.get("name", "")).strip(): dict(tool)
            for tool in all_tools
            if str(tool.get("name", "")).strip()
        }
        rows: List[dict[str, Any]] = []

        for case_index, case in enumerate(request.cases):
            candidate_names = _resolve_candidate_tools_for_case(case)
            tool_catalog = [all_tool_by_name[name] for name in candidate_names if name in all_tool_by_name]
            client_id = case.client_id or f"autonomous_case_{case_index}_{uuid.uuid4().hex[:6]}"
            argument_state = build_initial_argument_state(
                case_id=case.id or f"case_{case_index}",
                category=case.category or "",
                task=case.task,
                expected_success=bool(case.expected_success),
            )
            routed_steps = 0
            route_hits = 0
            executed_steps = 0
            successful_calls = 0
            failed_calls = 0
            blocked_calls = 0
            verified_steps = 0
            misroute_count = 0
            wasted_calls = 0
            step_records: List[dict[str, Any]] = []
            actual_success = True
            last_selected_tool = ""

            for step_index, step in enumerate(case.steps[: max(1, request.max_steps_per_case)]):
                expected_tool = str(step.tool).strip()
                expected_server = str(step.server or "").strip()
                routing_query_parts = [str(case.task or "").strip()]
                if step_index > 0:
                    routing_query_parts.append(f"step {step_index + 1}")
                if case.memory_focus:
                    routing_query_parts.append(" ".join(str(item) for item in case.memory_focus if str(item).strip()))
                if case.category:
                    routing_query_parts.append(str(case.category))
                if last_selected_tool:
                    routing_query_parts.append(f"previous_tool {last_selected_tool}")
                routing_query = " | ".join(part for part in routing_query_parts if part)

                routing_probe = memory_control_plane.build_routed_tool_execution_plan(
                    client_id=client_id,
                    query=routing_query,
                    candidate_tool_names=candidate_names,
                    tool_catalog=tool_catalog,
                    arguments={},
                    context_engine=context_engine,
                    tem=tem,
                    server_name=expected_server,
                    dry_run=False,
                    feature_mask=request.feature_mask,
                )
                recommended_tools = list(routing_probe.get("routing", {}).get("selected_tools", []))
                routed_tool = str(recommended_tools[0]).strip() if recommended_tools else ""
                selected_tool = expected_tool if request.teacher_force_tools else routed_tool
                selected_server = str(expected_server if request.teacher_force_tools else (routing_probe.get("server_name", "") or expected_server)).strip()
                route_hit = bool(routed_tool and routed_tool == expected_tool)
                routed_steps += 1
                route_hits += 1 if route_hit else 0
                misroute_count += 0 if route_hit else 1
                last_selected_tool = selected_tool or last_selected_tool

                gold_arguments = dict(step.arguments or {})
                argument_state_before = copy.deepcopy(argument_state)
                argument_policy = {
                    "mode": argument_policy_mode,
                    "source": "gold",
                    "template_name": "",
                    "supported": True,
                    "fallback_used": False,
                    "schema_match": True,
                    "exact_match": True,
                    "reason": "",
                    "derivation_path": ["gold_arguments"],
                }
                execution_arguments = dict(gold_arguments)
                if argument_policy_mode in {"controlled", "controlled_with_fallback"}:
                    generated_policy = generate_controlled_arguments(
                        case_id=case.id or f"case_{case_index}",
                        category=case.category or "",
                        task=case.task,
                        expected_success=bool(case.expected_success),
                        step_index=step_index,
                        selected_tool=selected_tool,
                        gold_arguments=gold_arguments,
                    )
                elif argument_policy_mode in {"memory_conditioned", "memory_conditioned_with_fallback"}:
                    generated_policy = generate_memory_conditioned_arguments(
                        state=argument_state_before,
                        case_id=case.id or f"case_{case_index}",
                        category=case.category or "",
                        task=case.task,
                        expected_success=bool(case.expected_success),
                        step_index=step_index,
                        selected_tool=selected_tool,
                        gold_arguments=gold_arguments,
                    )
                else:
                    generated_policy = None

                if generated_policy is not None:
                    argument_policy.update(
                        {
                            "source": str(generated_policy.get("source", "unsupported")),
                            "template_name": str(generated_policy.get("template_name", "")),
                            "supported": bool(generated_policy.get("supported", False)),
                            "schema_match": bool(generated_policy.get("schema_match", False)),
                            "exact_match": bool(generated_policy.get("exact_match", False)),
                            "reason": str(generated_policy.get("reason", "")),
                            "derivation_path": list(generated_policy.get("derivation_path", [])),
                        }
                    )
                    if generated_policy.get("supported", False):
                        execution_arguments = dict(generated_policy.get("arguments", {}))
                    elif argument_policy_mode in {"controlled_with_fallback", "memory_conditioned_with_fallback"}:
                        execution_arguments = dict(gold_arguments)
                        argument_policy["fallback_used"] = True
                        argument_policy["source"] = "gold_fallback"
                        argument_policy["derivation_path"] = list(argument_policy.get("derivation_path", [])) + ["fallback.gold_arguments"]
                    else:
                        actual_success = False
                        record = {
                            "step_index": step_index,
                            "routing_query": routing_query,
                            "expected_tool": expected_tool,
                            "expected_server": expected_server,
                            "selected_tool": selected_tool,
                            "routed_tool": routed_tool,
                            "selected_server": selected_server,
                            "route_hit": route_hit,
                            "candidate_tools": candidate_names,
                            "recommended_tools": recommended_tools,
                            "routing_scores": routing_probe.get("routing", {}).get("scores", []),
                            "memory_plan": routing_probe,
                            "executed": False,
                            "misroute": False,
                            "blocked": False,
                            "verified": False,
                            "reason": "controlled_argument_policy_unsupported",
                            "gold_arguments": gold_arguments,
                            "execution_arguments": {},
                            "argument_policy": argument_policy,
                            "argument_state_before": argument_state_before,
                            "argument_state_after": copy.deepcopy(argument_state_before),
                        }
                        step_records.append(record)
                        if request.stop_on_failure:
                            break
                        continue

                memory_plan = memory_control_plane.build_routed_tool_execution_plan(
                    client_id=client_id,
                    query=routing_query,
                    candidate_tool_names=candidate_names,
                    tool_catalog=tool_catalog,
                    arguments=execution_arguments,
                    context_engine=context_engine,
                    tem=tem,
                    server_name=selected_server,
                    dry_run=False,
                    feature_mask=request.feature_mask,
                )

                record: dict[str, Any] = {
                    "step_index": step_index,
                    "routing_query": routing_query,
                    "expected_tool": expected_tool,
                    "expected_server": expected_server,
                    "selected_tool": selected_tool,
                    "routed_tool": routed_tool,
                    "selected_server": selected_server,
                    "route_hit": route_hit,
                    "candidate_tools": candidate_names,
                    "recommended_tools": recommended_tools,
                    "routing_scores": routing_probe.get("routing", {}).get("scores", []),
                    "memory_plan": memory_plan,
                    "gold_arguments": gold_arguments,
                    "execution_arguments": execution_arguments,
                    "argument_policy": argument_policy,
                    "argument_state_before": argument_state_before,
                }

                if not route_hit and not request.teacher_force_tools:
                    actual_success = False
                    argument_state = update_argument_state(
                        state=argument_state_before,
                        step_index=step_index,
                        selected_tool=selected_tool,
                        arguments=execution_arguments,
                        result={"success": False, "reason": "router_selected_wrong_tool"},
                        blocked=False,
                        success=False,
                    )
                    record.update(
                        {
                            "executed": False,
                            "misroute": True,
                            "blocked": False,
                            "verified": False,
                            "reason": "router_selected_wrong_tool",
                            "argument_state_after": copy.deepcopy(argument_state),
                        }
                    )
                    step_records.append(record)
                    if request.stop_on_misroute:
                        break
                    continue

                if not request.execute_selected_tool:
                    argument_state = update_argument_state(
                        state=argument_state_before,
                        step_index=step_index,
                        selected_tool=selected_tool,
                        arguments=execution_arguments,
                        result={"success": True, "reason": "execution_disabled"},
                        blocked=False,
                        success=True,
                    )
                    record.update(
                        {
                            "executed": False,
                            "misroute": False,
                            "blocked": False,
                            "verified": False,
                            "reason": "execution_disabled",
                            "argument_state_after": copy.deepcopy(argument_state),
                        }
                    )
                    step_records.append(record)
                    continue

                executed_steps += 1
                execution_arguments = _normalize_tool_arguments_runtime(
                    selected_tool,
                    selected_server,
                    execution_arguments,
                )
                recipe_preflight = memory_plan.get("execution_policy", {}).get("recipe_preflight", {})
                block_info = tem.before_tool_call(
                    selected_tool,
                    execution_arguments,
                    selected_server,
                    task_description=routing_query,
                )
                if block_info:
                    blocked_calls += 1
                    actual_success = False
                    argument_state = update_argument_state(
                        state=argument_state_before,
                        step_index=step_index,
                        selected_tool=selected_tool,
                        arguments=execution_arguments,
                        result={
                            "success": False,
                            "blocked": True,
                            "reason": block_info.get("reason", ""),
                            "suggestion": block_info.get("suggestion", ""),
                        },
                        blocked=True,
                        success=False,
                    )
                    causal_trace = memory_control_plane.register_tool_outcome(
                        selected_tool=selected_tool,
                        plan=memory_plan,
                        success=False,
                        blocked=True,
                        guard_id=block_info.get("guard_id", ""),
                        counterfactual=block_info.get("suggestion", ""),
                        tem=tem,
                    )
                    verify_expected = _normalize_step_expectation_for_verification(step)
                    verify_expected["expect_contains"] = []
                    verify_expected["expect_not_contains"] = []
                    verify = verify_step_response(
                        verify_expected,
                        {
                            "success": False,
                            "blocked": True,
                            "reason": block_info.get("reason", ""),
                            "suggestion": block_info.get("suggestion", ""),
                        },
                        200,
                    )
                    verified_steps += 1 if verify["verified"] else 0
                    record.update(
                        {
                            "executed": False,
                            "misroute": False,
                            "blocked": True,
                            "verified": verify["verified"],
                            "verify": verify,
                            "guard_id": block_info.get("guard_id", ""),
                            "block_source": block_info.get("block_source", "guard"),
                            "recipe_preflight": block_info.get("recipe_preflight", recipe_preflight),
                            "causal_trace": causal_trace,
                            "result": {
                                "success": False,
                                "blocked": True,
                                "reason": block_info.get("reason", ""),
                                "suggestion": block_info.get("suggestion", ""),
                            },
                            "argument_state_after": copy.deepcopy(argument_state),
                        }
                    )
                    step_records.append(record)
                    if request.stop_on_failure:
                        break
                    continue

                call_started = time.time()
                result = await mcp_manager.call_tool(selected_tool, execution_arguments, selected_server)
                latency_ms = round((time.time() - call_started) * 1000, 1)
                success = bool(isinstance(result, dict) and result.get("success", False))
                if success:
                    successful_calls += 1
                else:
                    failed_calls += 1
                    wasted_calls += 1
                    actual_success = False
                error_type = ""
                error_message = ""
                if not success and isinstance(result, dict):
                    error_type = str(result.get("error_type", "ToolCallError"))
                    error_message = str(result.get("error", result.get("message", "")))
                tem_event = tem.after_tool_call(
                    client_id=client_id,
                    tool_name=selected_tool,
                    arguments=execution_arguments,
                    result=result,
                    success=success,
                    error_type=error_type,
                    error_message=error_message,
                    latency_ms=latency_ms,
                    server_name=selected_server,
                    task_description=routing_query,
                )
                causal_trace = memory_control_plane.register_tool_outcome(
                    selected_tool=selected_tool,
                    plan=memory_plan,
                    success=success,
                    blocked=False,
                    tem=tem,
                )
                verify = verify_step_response(
                    _normalize_step_expectation_for_verification(step),
                    result if isinstance(result, dict) else {"success": False, "result": result},
                    200,
                )
                verified_steps += 1 if verify["verified"] else 0
                if not verify["verified"]:
                    actual_success = False
                argument_state = update_argument_state(
                    state=argument_state_before,
                    step_index=step_index,
                    selected_tool=selected_tool,
                    arguments=execution_arguments,
                    result=result,
                    blocked=False,
                    success=success,
                )
                record.update(
                    {
                        "executed": True,
                        "misroute": False,
                        "blocked": False,
                        "verified": verify["verified"],
                        "verify": verify,
                        "latency_ms": latency_ms,
                        "protocol_success": bool(isinstance(result, dict) and result.get("protocol_success", False)),
                        "recipe_preflight": recipe_preflight,
                        "result": result,
                        "tem_event": tem_event,
                        "causal_trace": causal_trace,
                        "argument_state_after": copy.deepcopy(argument_state),
                    }
                )
                step_records.append(record)
                if request.stop_on_failure and (not success or not verify["verified"]):
                    break

            expectation_matched = actual_success == bool(case.expected_success)
            rows.append(
                {
                    "id": case.id or f"case_{case_index}",
                    "client_id": client_id,
                    "category": case.category or "",
                    "difficulty": case.difficulty or "",
                    "memory_focus": list(case.memory_focus or []),
                    "expected_success": bool(case.expected_success),
                    "actual_success": actual_success,
                    "expectation_matched": expectation_matched,
                    "steps_total": len(case.steps[: max(1, request.max_steps_per_case)]),
                    "routed_steps": routed_steps,
                    "route_hits": route_hits,
                    "executed_steps": executed_steps,
                    "successful_calls": successful_calls,
                    "failed_calls": failed_calls,
                    "blocked_calls": blocked_calls,
                    "verified_steps": verified_steps,
                    "misroute_count": misroute_count,
                    "wasted_calls": wasted_calls,
                    "step_records": step_records,
                }
            )
            tem.clear_pending_steps(client_id)

        return {
            "ok": True,
            "tem_mode": request.tem_mode,
            "feature_mask": request.feature_mask,
            "summary": _summarize_autonomous_rows(rows),
            "cases": rows,
        }
    except Exception as e:
        logger.error(f"Memory autonomous trajectory evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory autonomous trajectory evaluation failed: {str(e)}")
    finally:
        if request.restore_state_after_run:
            memory_control_plane.restore_runtime_state(snapshot, context_engine, tem)


@app.post("/api/memory-plane/rollback")
async def rollback_memory_governance(request: GovernanceRollbackRequest):
    """Rollback recent executable forgetting/governance actions for recovery-utility evaluation."""
    try:
        return memory_control_plane.rollback_recent_governance(tem, reason=request.reason)
    except Exception as e:
        logger.error(f"Memory governance rollback failed: {e}")
        raise HTTPException(status_code=500, detail=f"Memory governance rollback failed: {str(e)}")

@app.get("/api/tem/stats")
async def get_tem_stats():
    """获取 Tool Execution Memory 全局统计"""
    return tem.get_stats()

@app.get("/api/tem/mode")
async def get_tem_mode():
    """Get current TEM runtime mode and feature flags."""
    return tem.get_mode_state()


@app.post("/api/tem/mode")
async def set_tem_mode(request: TEMModeRequest):
    """Set current TEM runtime mode for live evaluation or debugging."""
    try:
        result = tem.set_mode(request.mode)
        await push_runtime_status_update(event="tem_mode_changed", message=f"TEM mode switched to {result.get('mode', request.mode)}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/tem/recipes")
async def get_tem_recipes():
    """获取所有已学习的工具配方"""
    return {"recipes": tem.recipes.get_all()}

@app.get("/api/tem/guards")
async def get_tem_guards():
    """获取所有失败拦截规则"""
    return {"guards": tem.guards.get_all()}


@app.get("/api/tem/decisions")
async def get_tem_decisions(limit: int = 20):
    """Get recent TEM decision traces."""
    safe_limit = max(1, min(limit, 200))
    decisions = tem.get_recent_decisions(safe_limit)
    stats = tem.get_stats()
    return {
        "decision_trace_path": stats.get("decision_trace_path", ""),
        "decisions": decisions,
        "count": len(decisions),
    }


@app.post("/api/tem/guards/reset")
async def reset_tem_guards():
    """
    Reset all TEM failure guards.
    Intended for strict reproducible live experiment runs.
    """
    removed = tem.guards.reset_all()
    return {"ok": True, "removed": removed}


@app.post("/api/tem/reset")
async def reset_tem_state(request: TEMResetRequest):
    """
    Reset TEM artifacts for reproducible experiments.
    Supports selective cleanup of recipes, guards, traces, and pending state.
    """
    return tem.reset_memory(
        recipes=request.recipes,
        guards=request.guards,
        traces=request.traces,
        pending=request.pending,
    )

@app.post("/api/tem/benchmark")
async def run_tem_benchmark():
    """运行 TEM 评测并返回报告（POST：有计算副作用，不适合 GET）"""
    from tem_benchmark import run_benchmark
    return run_benchmark()


@app.get("/api/params/learning_status")
async def get_param_learning_status():
    """获取在线参数学习状态。"""
    return parameter_learner.get_status()


@app.post("/api/params/recommend_next")
async def recommend_next_params():
    """基于当前学习状态给出下一组参数建议。"""
    return parameter_learner.recommend_next_params()


@app.post("/api/params/apply_recommendation")
async def apply_param_recommendation():
    """
    生成并应用参数建议到 algorithm_params.json。
    参数应用后会立即热重载生效。
    """
    rec = parameter_learner.recommend_next_params()
    applied = parameter_learner.apply_recommendation(rec)
    tem_reload = reload_tem_parameters()
    ctx_reload = reload_context_engine_parameters()
    memory_plane_reload = reload_memory_plane_parameters()
    return {
        "recommendation": rec,
        "apply_result": applied,
        "reload": {
            "tool_execution_memory": tem_reload,
            "context_engine": ctx_reload,
            "memory_control_plane": memory_plane_reload,
        },
        "note": "参数已写入并热重载，当前进程已生效。",
    }


@app.post("/api/params/reload")
async def reload_runtime_params():
    """从 algorithm_params.json 手动热重载参数。"""
    tem_reload = reload_tem_parameters()
    ctx_reload = reload_context_engine_parameters()
    memory_plane_reload = reload_memory_plane_parameters()
    return {
        "ok": True,
        "tool_execution_memory": tem_reload,
        "context_engine": ctx_reload,
        "memory_control_plane": memory_plane_reload,
    }

@app.post("/api/mcp/call_tool")
async def call_mcp_tool(request: ToolCallRequest):
    """调用MCP工具"""
    if not mcp_manager:
        raise HTTPException(status_code=503, detail="MCP管理器不可用")
    
    t0 = time.time()
    try:
        workspace_root = str(request.workspace_context.get("workspace_root", "") or "") if isinstance(request.workspace_context, dict) else ""
        effective_http_manager, workspace_mcp_metadata = await _get_effective_mcp_manager(
            request.workspace_context if isinstance(request.workspace_context, dict) else {}
        )
        harness_prepared = mcp_harness_engine.prepare_tool_call(
            manager=effective_http_manager,
            tool_name=request.tool_name,
            server_name=request.server_name or "",
            arguments=request.arguments,
            content=request.content or "",
            attachments=request.attachments,
            workspace_root=workspace_root,
            source="http_tool_call",
        )
        if not harness_prepared.get("ok"):
            return {
                "success": False,
                "blocked": True,
                "tool_name": request.tool_name,
                "reason": harness_prepared.get("error", "Harness preparation failed."),
                "block_source": "harness_prepare",
                "workspace_mcp": workspace_mcp_metadata,
                "harness": {
                    "action": harness_prepared.get("action", {}),
                    "capability_snapshot": harness_prepared.get("capability_snapshot", {}),
                },
            }
        harness_contract = harness_prepared.get("contract", {})
        harness_compiler = harness_prepared.get("compiler", {})
        harness_precheck = harness_prepared.get("precheck", {})
        resource_refs = build_resource_references(
            content=request.content or "",
            attachments=request.attachments,
            workspace_root=workspace_root,
            project_root=project_root,
        )
        if harness_precheck.get("blocking"):
            return {
                "success": False,
                "blocked": True,
                "tool_name": request.tool_name,
                "reason": harness_precheck.get("reason") or "Harness precheck blocked the tool call.",
                "suggestion": harness_precheck.get("suggestion") or "",
                "block_source": "harness_precheck",
                "workspace_mcp": workspace_mcp_metadata,
                "resource_refs": resource_refs,
                "harness": {
                    "action": harness_prepared.get("action", {}),
                    "contract": harness_contract,
                    "compiler": harness_compiler,
                    "precheck": harness_precheck,
                    "capability_snapshot": harness_prepared.get("capability_snapshot", {}),
                },
            }
        resolved_arguments = dict(harness_compiler.get("arguments", {}) or {})
        inferred_fields = list(harness_compiler.get("inferred_fields", []) or [])
        http_client_id = f"http_{id(request)}"
        memory_plan = memory_control_plane.build_tool_memory_plan(
            client_id=http_client_id,
            tool_name=request.tool_name,
            arguments=resolved_arguments,
            server_name=request.server_name or "",
            task_description=request.content or request.tool_name,
            tem=tem,
            allow_recipe_preflight_block=False,
        )
        recipe_preflight = memory_plan.get("execution_policy", {}).get("recipe_preflight", {})
        policy_block = evaluate_runtime_tool_policy(
            server_name=request.server_name or "",
            tool_name=request.tool_name,
            arguments=resolved_arguments,
            policy_confirmed=bool(request.policy_confirmed),
        )
        if policy_block:
            return {
                "success": False,
                "blocked": True,
                "tool_name": request.tool_name,
                "reason": policy_block["reason"],
                "suggestion": policy_block["suggestion"],
                "block_source": policy_block.get("block_source", "policy"),
                "policy_action": policy_block.get("policy_action"),
                "policy_reason": policy_block.get("policy_reason"),
                "inferred_arguments": inferred_fields,
                "recipe_preflight": recipe_preflight,
                "memory_plane": memory_plan,
                "run_trace": build_tool_run_trace(
                    request_id=None,
                    server_name=request.server_name or "",
                    tool_name=request.tool_name,
                    arguments=resolved_arguments,
                    memory_plan=memory_plan,
                    policy_block=policy_block,
                    blocked=True,
                    success=False,
                ),
            }

        # TEM 调用前拦截（HTTP 路径）
        block_info = tem.before_tool_call(
            request.tool_name,
            resolved_arguments,
            request.server_name or "",
            task_description=request.content or request.tool_name,
            enforce_recipe_preflight_block=False,
            enforce_guard_block=False,
        )
        if block_info:
            causal_trace = memory_control_plane.register_tool_outcome(
                selected_tool=request.tool_name,
                plan=memory_plan,
                success=False,
                blocked=True,
                guard_id=block_info.get("guard_id", ""),
                counterfactual=block_info.get("suggestion", ""),
                tem=tem,
            )
            try:
                parameter_learner.record_tool_feedback(
                    success=False,
                    blocked=True,
                    latency_ms=round((time.time() - t0) * 1000, 1),
                )
            except Exception as learn_err:
                logger.warning(f"parameter learning record failed (blocked): {learn_err}")
            return {
                "success": False,
                "blocked": True,
                "tool_name": request.tool_name,
                "reason": block_info["reason"],
                "suggestion": block_info["suggestion"],
                "guard_id": block_info.get("guard_id", ""),
                "block_source": block_info.get("block_source", "guard"),
                "guard_evidence": block_info.get("guard_evidence"),
                "recipe_preflight": block_info.get("recipe_preflight", recipe_preflight),
                "inferred_arguments": inferred_fields,
                "memory_plane": memory_plan,
                "causal_trace": causal_trace,
                "run_trace": build_tool_run_trace(
                    request_id=None,
                    server_name=request.server_name or "",
                    tool_name=request.tool_name,
                    arguments=resolved_arguments,
                    memory_plan=memory_plan,
                    blocked=True,
                    success=False,
                ),
            }

        # 检查管理器是否有call_tool方法
        if hasattr(effective_http_manager, 'call_tool'):
            result = await effective_http_manager.call_tool(
                request.tool_name,
                resolved_arguments,
                request.server_name,
            )
        else:
            result = {
                "success": False,
                "error": "MCP管理器不支持工具调用",
                "message": "当前 MCP 管理器无 call_tool 方法"
            }
        result = _with_friendly_tool_error(result)

        success = bool(isinstance(result, dict) and result.get("success", False))
        error_type = ""
        error_message = ""
        if not success and isinstance(result, dict):
            error_type = result.get("error_type", "ToolCallError")
            error_message = str(result.get("error", result.get("message", "")))

        tem_event = tem.after_tool_call(
            client_id=http_client_id,
            tool_name=request.tool_name,
            arguments=resolved_arguments,
            result=result,
            success=success,
            error_type=error_type,
            error_message=error_message,
            latency_ms=round((time.time() - t0) * 1000, 1),
            server_name=request.server_name or "",
            task_description=f"HTTP API 调用: {request.tool_name}",
        )
        causal_trace = memory_control_plane.register_tool_outcome(
            selected_tool=request.tool_name,
            plan=memory_plan,
            success=success,
            blocked=False,
            tem=tem,
        )
        try:
            parameter_learner.record_tool_feedback(
                success=success,
                blocked=False,
                latency_ms=round((time.time() - t0) * 1000, 1),
            )
        except Exception as learn_err:
            logger.warning(f"parameter learning record failed (http tool): {learn_err}")
        enriched_result = (
            {
                **result,
                "tem_event": tem_event,
                "memory_plane": memory_plan,
                "causal_trace": causal_trace,
                "recipe_preflight": recipe_preflight,
                "inferred_arguments": inferred_fields,
                "workspace_mcp": workspace_mcp_metadata,
                "resource_refs": resource_refs,
                "harness": {
                    "action": harness_prepared.get("action", {}),
                    "contract": harness_contract,
                    "compiler": harness_compiler,
                    "precheck": harness_precheck,
                    "postcheck": mcp_harness_engine.finalize_tool_call(contract=harness_contract, result=result),
                    "capability_snapshot": harness_prepared.get("capability_snapshot", {}),
                },
                "run_trace": build_tool_run_trace(
                    request_id=None,
                    server_name=request.server_name or "",
                    tool_name=request.tool_name,
                    arguments=resolved_arguments,
                    memory_plan=memory_plan,
                    latency_ms=round((time.time() - t0) * 1000, 1),
                    success=success,
                ),
            }
            if isinstance(result, dict)
            else {
                "success": success,
                "result": result,
                "tem_event": tem_event,
                "memory_plane": memory_plan,
                "causal_trace": causal_trace,
                "recipe_preflight": recipe_preflight,
                "inferred_arguments": inferred_fields,
                "workspace_mcp": workspace_mcp_metadata,
                "resource_refs": resource_refs,
                "harness": {
                    "action": harness_prepared.get("action", {}),
                    "contract": harness_contract,
                    "compiler": harness_compiler,
                    "precheck": harness_precheck,
                    "postcheck": mcp_harness_engine.finalize_tool_call(contract=harness_contract, result=result),
                    "capability_snapshot": harness_prepared.get("capability_snapshot", {}),
                },
                "run_trace": build_tool_run_trace(
                    request_id=None,
                    server_name=request.server_name or "",
                    tool_name=request.tool_name,
                    arguments=resolved_arguments,
                    memory_plan=memory_plan,
                    latency_ms=round((time.time() - t0) * 1000, 1),
                    success=success,
                ),
            }
        )
        return enriched_result
    except Exception as e:
        logger.error(f"failed to call MCP tool: {e}")
        logger.error(traceback.format_exc())
        http_err_id = f"http_err_{id(request)}"
        fallback_arguments = locals().get("resolved_arguments", request.arguments)
        tem.after_tool_call(
            client_id=http_err_id,
            tool_name=request.tool_name,
            arguments=fallback_arguments,
            result=None,
            success=False,
            error_type=type(e).__name__,
            error_message=str(e),
            latency_ms=round((time.time() - t0) * 1000, 1),
            server_name=request.server_name or "",
            task_description=f"HTTP API 调用异常: {request.tool_name}",
        )
        tem.clear_pending_steps(http_err_id)
        try:
            parameter_learner.record_tool_feedback(
                success=False,
                blocked=False,
                latency_ms=round((time.time() - t0) * 1000, 1),
            )
        except Exception as learn_err:
            logger.warning(f"parameter learning record failed (http exception): {learn_err}")
        raise HTTPException(status_code=500, detail=f"工具调用失败: {str(e)}")

@app.post("/api/mcp/read_resource")
async def read_mcp_resource(request: ResourceRequest):
    """读取MCP资源"""
    if not mcp_manager:
        raise HTTPException(status_code=503, detail="MCP管理器不可用")
    
    try:
        # 检查管理器是否有read_resource方法
        if hasattr(mcp_manager, 'read_resource'):
            result = await mcp_manager.read_resource(request.uri)
        else:
            result = {
                "success": False,
                "error": "MCP管理器不支持资源读取",
                "message": "请使用支持资源读取的MCP管理器"
            }
        
        return result
    except Exception as e:
        logger.error(f"failed to read MCP resource: {e}")
        raise HTTPException(status_code=500, detail=f"资源读取失败: {str(e)}")

@app.post("/api/mcp/get_prompt")
async def get_mcp_prompt(request: PromptRequest):
    """获取MCP提示词"""
    if not mcp_manager:
        raise HTTPException(status_code=503, detail="MCP管理器不可用")
    
    try:
        # 检查管理器是否有get_prompt方法
        if hasattr(mcp_manager, 'get_prompt'):
            result = await mcp_manager.get_prompt(request.name, request.arguments)
        else:
            result = {
                "success": False,
                "error": "MCP管理器不支持提示词获取",
                "message": "请使用支持提示词获取的MCP管理器"
            }
        
        return result
    except Exception as e:
        logger.error(f"failed to get MCP prompt: {e}")
        raise HTTPException(status_code=500, detail=f"提示词获取失败: {str(e)}")

@app.post("/api/chat")
async def chat_completion(request: ChatRequest):
    """Proxy chat completion API."""
    provider = resolve_provider_for_model(request.model)
    api_key, api_base = get_provider_runtime(provider)
    if not api_key:
        raise HTTPException(status_code=503, detail=f"{provider} API unavailable")

    try:
        import httpx

        # build request payload
        messages = []
        for msg in request.messages:
            message_dict: Dict[str, Any] = {
                "role": msg.role,
                "content": msg.content
            }
            if msg.tool_calls:
                message_dict["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                message_dict["tool_call_id"] = msg.tool_call_id
            messages.append(message_dict)

        payload = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": request.stream
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:8000"
            headers["X-Title"] = "MCP Mirror"

        response = await _post_chat_with_retry(
            get_shared_http_client(),
            url=f"{api_base}/chat/completions",
            headers=headers,
            payload=payload,
            provider=provider,
        )

        if response.status_code == 200:
            return response.json()
        logger.error(f"{provider} API error: {response.status_code} - {response.text}")
        raise HTTPException(
            status_code=response.status_code,
            detail=_friendly_provider_error(provider, response.status_code, response.text),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat request failed: {e}")
        raise HTTPException(status_code=500, detail=f"Chat request failed: {str(e)}")

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """文件上传"""
    try:
        # 创建上传目录
        UPLOAD_DIR.mkdir(exist_ok=True)
        
        # 生成唯一文件名
        filename = file.filename or "unknown"
        file_extension = Path(filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = UPLOAD_DIR / unique_filename
        
        # 保存文件
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        parsed_attachment = extract_attachment_content(
            {
                "filename": unique_filename,
                "original_filename": file.filename,
                "file_path": str(file_path.resolve()),
                "size": len(content),
                "mime_type": file.content_type,
                "content_type": file.content_type,
            },
        )

        return {
            "success": True,
            "filename": unique_filename,
            "original_filename": file.filename,
            "file_path": str(file_path.resolve()),
            "size": len(content),
            "mime_type": file.content_type,
            "content_type": file.content_type,
            "parse_status": parsed_attachment.get("parse_status"),
            "parse_mode": parsed_attachment.get("parse_mode"),
            "parser": parsed_attachment.get("parser"),
            "preview_text": parsed_attachment.get("preview_text"),
            "full_text_chars": parsed_attachment.get("full_text_chars"),
            "visible_text_chars": parsed_attachment.get("visible_text_chars"),
            "preview_truncated": parsed_attachment.get("preview_truncated"),
            "parse_error": parsed_attachment.get("error"),
        }
        
    except Exception as e:
        logger.error(f"file upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@app.get("/api/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """获取上传的文件"""
    file_path = UPLOAD_DIR / filename
    if file_path.exists():
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=404, detail="文件不存在")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket端点"""
    await manager.connect(websocket, client_id)
    try:
        await manager.send_to_websocket(websocket, build_runtime_connection_payload(client_id))
        if manager.is_current_connection(client_id, websocket):
            await push_runtime_status_update(event="websocket_connected", client_id=client_id, message="Runtime status ready")
    except Exception as e:
        if manager.is_current_connection(client_id, websocket) and manager.is_active_connection(websocket):
            logger.warning(f"websocket initial send failed for {client_id}: {e}")
            manager.disconnect(client_id, websocket)
        elif manager.is_current_connection(client_id, websocket):
            logger.debug(f"websocket initial send skipped for closed connection: {client_id}")
            manager.disconnect(client_id, websocket)
        else:
            logger.debug(f"stale websocket skipped during initial send: {client_id}")
        return
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            request_id = message.get("request_id")
            
            # 处理不同类型的消息
            if message.get("type") == "ping":
                await manager.send_personal_message({"type": "pong"}, client_id)
                
            elif message.get("type") == "chat":
                if await _replay_cached_request_to_client(client_id, request_id):
                    continue
                if _register_inflight_request(request_id, client_id):
                    await send_request_delivery(client_id, request_id, "processing", message="Request already in progress; subscribed to existing run")
                    continue
                _remember_request_inflight(request_id, message, client_id)
                # 处理聊天消息
                await send_request_delivery(client_id, request_id, "received", message="Chat request received")
                await handle_chat_message(message, client_id)
                
            elif message.get("type") == "model_select":
                # 处理模型选择
                model_id = message.get("model_id")
                model_name = model_id
                active_models = _get_active_available_models()
                if any(model["id"] == model_id for model in active_models):
                    for model in active_models:
                        if model["id"] == model_id:
                            model_name = model["name"]
                            break
                    await manager.send_personal_message({
                        "type": "model_selected",
                        "model_id": model_id,
                        "model_name": model_name,
                        "message": f"已切换到模型: {model_name}"
                    }, client_id)
                else:
                    await manager.send_personal_message({
                        "type": "error",
                        "message": f"模型 {model_id} 不可用"
                    }, client_id)
                    
            elif message.get("type") == "tool_call":
                if await _replay_cached_request_to_client(client_id, request_id):
                    continue
                if _register_inflight_request(request_id, client_id):
                    await send_request_delivery(client_id, request_id, "processing", message="Request already in progress; subscribed to existing run")
                    continue
                _remember_request_inflight(request_id, message, client_id)
                # 处理工具调用
                await send_request_delivery(client_id, request_id, "received", message="Tool call request received")
                await handle_tool_call(message, client_id)
                
            elif message.get("type") == "resource_read":
                if await _replay_cached_request_to_client(client_id, request_id):
                    continue
                if _register_inflight_request(request_id, client_id):
                    await send_request_delivery(client_id, request_id, "processing", message="Request already in progress; subscribed to existing run")
                    continue
                _remember_request_inflight(request_id, message, client_id)
                # 处理资源读取
                await send_request_delivery(client_id, request_id, "received", message="Resource read request received")
                await handle_resource_read(message, client_id)
                
            elif message.get("type") == "prompt_get":
                if await _replay_cached_request_to_client(client_id, request_id):
                    continue
                if _register_inflight_request(request_id, client_id):
                    await send_request_delivery(client_id, request_id, "processing", message="Request already in progress; subscribed to existing run")
                    continue
                _remember_request_inflight(request_id, message, client_id)
                # 处理提示词获取
                await send_request_delivery(client_id, request_id, "received", message="Prompt request received")
                await handle_prompt_get(message, client_id)
                
            elif message.get("type") == "get_mcp_status":
                workspace_context_config = (
                    message.get("workspace_context")
                    if isinstance(message.get("workspace_context"), dict)
                    else {}
                )
                await handle_mcp_status_request(client_id, workspace_context_config)
                await push_runtime_status_update(event="mcp_status_requested", client_id=client_id, message="MCP status refreshed")

            elif message.get("type") == "get_memory_status":
                mem_status = context_engine.get_memory_status(client_id)
                await manager.send_personal_message({
                    "type": "memory_status",
                    "memory": mem_status,
                    "timestamp": datetime.now().isoformat()
                }, client_id)
                await push_runtime_status_update(event="memory_status_requested", client_id=client_id, message="Memory status refreshed")

            elif message.get("type") == "clear_memory":
                context_engine.remove_memory(client_id)
                await manager.send_personal_message({
                    "type": "memory_cleared",
                    "message": "对话记忆已清除",
                    "timestamp": datetime.now().isoformat()
                }, client_id)
                await push_runtime_status_update(event="memory_cleared", client_id=client_id, message="Conversation memory cleared")

            elif message.get("type") == "get_tem_status":
                stats = tem.get_stats()
                await manager.send_personal_message({
                    "type": "tem_status",
                    "stats": stats,
                    "timestamp": datetime.now().isoformat()
                }, client_id)
                await push_runtime_status_update(event="tem_status_requested", client_id=client_id, message="TEM status refreshed")

            elif message.get("type") == "get_recipes":
                await manager.send_personal_message({
                    "type": "recipes_list",
                    "recipes": tem.recipes.get_all(),
                    "timestamp": datetime.now().isoformat()
                }, client_id)

            elif message.get("type") == "get_guards":
                await manager.send_personal_message({
                    "type": "guards_list",
                    "guards": tem.guards.get_all(),
                    "timestamp": datetime.now().isoformat()
                }, client_id)

    except WebSocketDisconnect:
        if manager.is_current_connection(client_id, websocket):
            tem.clear_pending_steps(client_id)
            context_engine.remove_memory(client_id)
            manager.disconnect(client_id, websocket)
        else:
            logger.debug(f"stale websocket disconnected: {client_id}")
    except Exception as e:
        if manager.is_current_connection(client_id, websocket):
            logger.error(f"websocket error: {e}")
            tem.clear_pending_steps(client_id)
            context_engine.remove_memory(client_id)
            manager.disconnect(client_id, websocket)
        else:
            logger.debug(f"stale websocket closed after replacement: {client_id}")

async def handle_chat_message(message: dict, client_id: str):
    """处理聊天消息（多轮记忆 + 智能上下文压缩）"""
    trace = ExecutionTrace(task="chat_message", client_id=client_id)
    request_id = message.get("request_id")
    try:
        if not isinstance(message, dict):
            raise ValueError(f"消息格式错误，期望dict，得到{type(message)}")
        if not client_id:
            raise ValueError("client_id不能为空")

        content = message.get("content", "")
        image_data = message.get("image_data")
        image_data_list = message.get("image_data_list", [])
        web_search_enabled = bool(message.get("web_search_enabled", False))
        attachments = message.get("attachments", [])
        attachment_plan = message.get("attachment_plan", {})
        model_id = message.get("model_id") or DEFAULT_MODEL_ID
        workspace_agent_command_name = str(message.get("workspace_agent_command", "") or "").strip()
        skill_ids = [
            str(skill_id).strip()
            for skill_id in message.get("skill_ids", [])
            if str(skill_id).strip()
        ]
        custom_system_prompt = str(message.get("custom_system_prompt", "") or "").strip()
        workspace_context_config = (
            message.get("workspace_context")
            if isinstance(message.get("workspace_context"), dict)
            else {}
        )
        workspace_agent_profile = load_workspace_agent_runtime_profile(
            workspace_root=str(workspace_context_config.get("workspace_root", "") or ""),
            agent_name=str(workspace_context_config.get("agent_name", "") or ""),
        )
        workspace_agent_profile = _merge_workspace_agent_profile_with_session_overrides(
            workspace_agent_profile,
            workspace_context_config,
        )
        active_mcp_manager, workspace_mcp_metadata = await _get_effective_mcp_manager(workspace_context_config)
        trace.step(
            "receive",
            content_len=len(content),
            model=model_id,
            has_image=bool(image_data or image_data_list),
            web_search_enabled=web_search_enabled,
            attachment_count=len(attachments) if isinstance(attachments, list) else 0,
            skill_count=len(skill_ids),
            custom_system_prompt=bool(custom_system_prompt),
            workspace_context=bool(workspace_context_config),
            workspace_agent_profile=bool(workspace_agent_profile),
            workspace_mcp=bool(workspace_mcp_metadata.get("workspace_enabled")),
        )

        if not _is_model_available_for_runtime(model_id):
            model_id = _resolve_runtime_default_model()

        await manager.send_personal_message({
            "type": "status",
            "status": "processing",
            "message": f"正在使用 {model_id} 处理您的消息...",
            "request_id": request_id,
        }, client_id)
        await send_request_delivery(client_id, request_id, "processing", message=f"Calling model {model_id}")

        provider = resolve_provider_for_model(model_id)
        api_key, api_base = get_provider_runtime(provider)
        if not api_key:
            error_payload = {
                "type": "error",
                "message": f"Model provider not configured: {provider}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            }
            await manager.send_personal_message(error_payload, client_id)
            _remember_request_result(request_id, error_payload)
            await send_request_delivery(
                client_id,
                request_id,
                "failed",
                message=f"Model provider not configured: {provider}",
            )
            trace.finish(status="provider_not_configured")
            return

        # ---- TEM: 生成技能/拦截上下文注入 LLM ----
        tools = active_mcp_manager.get_all_tools() if active_mcp_manager else []
        skill_runtime = _resolve_skill_runtime_for_request(
            requested_skill_ids=skill_ids,
            query=content,
            workspace_context_config=workspace_context_config,
            workspace_agent_profile=workspace_agent_profile,
            model_id=model_id,
            available_tools=tools,
            scopes=["chat", "tool_routing"],
        )
        workspace_agent_profile = _merge_workspace_profile_with_skill_runtime(
            workspace_agent_profile,
            skill_runtime,
        )
        tools = _filter_tools_by_workspace_agent_profile(tools, workspace_agent_profile)
        suppress_tool_calls_for_visual_request = _should_suppress_tools_for_multimodal_image_request(
            query=content,
            model_id=model_id,
            attachments=attachments if isinstance(attachments, list) else [],
            attachment_plan=attachment_plan if isinstance(attachment_plan, dict) else {},
            image_data=image_data,
            image_data_list=image_data_list if isinstance(image_data_list, list) else [],
            workspace_root=str(workspace_context_config.get("workspace_root", "") or "") if isinstance(workspace_context_config, dict) else "",
        )
        if suppress_tool_calls_for_visual_request:
            tools = []
        model_tool_catalog = [
            tool
            for tool in tools
            if str(tool.get("name", "")).strip() and str(tool.get("server", "")).strip()
        ]
        tool_names = [str(t.get("name", "")).strip() for t in model_tool_catalog if str(t.get("name", "")).strip()]
        relevant_tool_names = infer_relevant_tool_names(content, tool_names)
        context_tool_names = relevant_tool_names or tool_names
        model_allowed_tool_names = list(tool_names)
        memory_plan = memory_control_plane.build_chat_memory_plan(
            client_id=client_id,
            query=content,
            tool_names=tool_names,
            tool_catalog=model_tool_catalog,
            context_engine=context_engine,
            tem=tem,
        )
        memory_control_plane.register_chat_context(memory_plan, tem)
        if memory_plan.get("routing", {}).get("relevant_tools"):
            context_tool_names = memory_plan["routing"]["relevant_tools"]
        should_attempt_auto_tool = (
            not suppress_tool_calls_for_visual_request
            and _should_attempt_auto_tool(
                query=content,
                attachments=attachments if isinstance(attachments, list) else [],
                attachment_plan=attachment_plan if isinstance(attachment_plan, dict) else {},
                workspace_root=str(workspace_context_config.get("workspace_root", "") or "") if isinstance(workspace_context_config, dict) else "",
                web_search_enabled=web_search_enabled,
            )
        )
        auto_tool_candidate = None
        if should_attempt_auto_tool:
            model_tool_catalog_for_chat = _rank_tools_for_model_visibility(
                content,
                model_tool_catalog,
                memory_plan,
            )
            model_allowed_tool_names = [
                str(tool.get("name", "")).strip()
                for tool in model_tool_catalog_for_chat
                if str(tool.get("name", "")).strip()
            ]
            auto_tool_candidate = _select_auto_tool_candidate(
                client_id=client_id,
                query=content,
                attachments=attachments if isinstance(attachments, list) else [],
                allowed_tools=model_tool_catalog,
                workspace_root=str(workspace_context_config.get("workspace_root", "") or "") if isinstance(workspace_context_config, dict) else "",
                active_mcp_manager=active_mcp_manager,
                web_search_enabled=web_search_enabled,
            )
        else:
            model_tool_catalog_for_chat = []
            model_allowed_tool_names = []
        prefer_multimodal_model = bool(
            (image_data or image_data_list or _has_image_attachment(attachments))
            and _is_multimodal_model(model_id)
        )
        tem_context = tem.get_recipes_for_context(content, context_tool_names)
        guard_context = tem.get_guards_for_context(context_tool_names)
        if guard_context:
            tem_context = f"{tem_context}\n{guard_context}" if tem_context else guard_context
        skills_context = str(skill_runtime.get("prompt_context", "") or "")
        workspace_agent_command = load_workspace_agent_command(
            workspace_root=str(workspace_context_config.get("workspace_root", "") or ""),
            agent_name=str(workspace_context_config.get("agent_name", "") or ""),
            command_name=workspace_agent_command_name,
        )
        workspace_agent_command_context = render_workspace_agent_command_context(
            workspace_agent_command,
            user_input=str(content or ""),
        )
        if workspace_agent_command_context:
            skills_context = (
                f"{skills_context}\n\n{workspace_agent_command_context}"
                if skills_context else workspace_agent_command_context
            )
        workspace_context_text, workspace_context_metadata = build_workspace_context_block(
            workspace_root=str(workspace_context_config.get("workspace_root", "") or ""),
            agent_name=str(workspace_context_config.get("agent_name", "") or ""),
            include_agent_profile=bool(workspace_context_config.get("include_agent_profile", True)),
            include_memory_file=bool(workspace_context_config.get("include_memory_file", True)),
            include_chatlogs=bool(workspace_context_config.get("include_chatlogs", False)),
        )

        # ---- 上下文引擎：构建带记忆的消息列表 ----
        api_messages, comp_stats = await context_engine.build_api_messages(
            client_id=client_id,
            new_content=content,
            image_data=image_data,
            image_data_list=image_data_list,
            attachments=attachments,
            api_key=api_key,
            api_base_url=api_base,
            model_id=model_id,
            tem_context=tem_context,
            memory_policy=memory_plan,
            custom_system_prompt=custom_system_prompt,
            skills_context=skills_context,
            workspace_context=workspace_context_text,
        )
        trace.step("context_built",
                    messages_sent=comp_stats.messages_sent_to_api,
                    original_tokens=comp_stats.original_tokens,
                    compressed_tokens=comp_stats.compressed_tokens,
                    compression_ratio=comp_stats.compression_ratio)
        run_trace = build_chat_run_trace(
            request_id=request_id,
            provider=provider,
            model_id=model_id,
            attachments=attachments,
            memory_plan=memory_plan,
            comp_stats=comp_stats,
        )

        # 推送压缩状态给前端
        await manager.send_personal_message({
            "type": "context_status",
            "memory": comp_stats.to_dict(),
            "memory_plane": memory_plan,
            "skill_runtime": skill_runtime,
            "workspace_context": workspace_context_metadata,
            "workspace_agent_profile": workspace_agent_profile,
            "workspace_mcp": workspace_mcp_metadata,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }, client_id)

        # ---- 调用 LLM API ----
        trace.step("call_api", model=model_id)
        payload = {
            "model": model_id,
            "messages": api_messages,
            "temperature": DEFAULT_CHAT_TEMPERATURE,
            "max_tokens": DEFAULT_WS_CHAT_MAX_TOKENS
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **({"HTTP-Referer": "http://localhost:8000", "X-Title": "MCP Mirror"} if provider == "openrouter" else {})
        }
        client = get_shared_http_client()
        model_driven_tool_result = None
        should_try_model_tool_loop = (
            should_attempt_auto_tool
            and model_allowed_tool_names
            and not _should_bypass_model_tool_loop_for_candidate(auto_tool_candidate)
        )
        if should_try_model_tool_loop and model_allowed_tool_names:
            try:
                model_driven_tool_result = await _run_model_driven_tool_loop(
                    client_id=client_id,
                    request_id=request_id,
                    model_id=model_id,
                    provider=provider,
                    api_key=api_key,
                    api_base=api_base,
                    api_messages=api_messages,
                    available_tool_catalog=model_tool_catalog_for_chat,
                    allowed_tool_names=model_allowed_tool_names,
                    original_user_content=content,
                    attachments=attachments if isinstance(attachments, list) else [],
                    skill_ids=skill_ids,
                    custom_system_prompt=custom_system_prompt,
                    workspace_context_config=workspace_context_config,
                    active_mcp_manager=active_mcp_manager,
                    memory_plan=memory_plan,
                )
            except Exception as tool_loop_error:
                logger.warning(f"model-driven tool loop failed, falling back to plain chat: {tool_loop_error}")

        if model_driven_tool_result:
            ai_response = str(model_driven_tool_result.get("content", "") or "").strip()
            context_engine.record_assistant_response(client_id, ai_response)
            if not model_driven_tool_result.get("streamed_to_client"):
                await manager.send_personal_message(model_driven_tool_result, client_id)
            _remember_request_result(request_id, model_driven_tool_result)
            await send_request_delivery(
                client_id,
                request_id,
                "completed",
                message="Chat response delivered after model-driven MCP tool use",
                details={"model_id": model_id, "model_name": _resolve_model_name(model_id)},
            )
            try:
                parameter_learner.record_context_feedback(
                    response_ok=bool(ai_response),
                    compression_ratio=comp_stats.compression_ratio,
                    compressed_tokens=comp_stats.compressed_tokens,
                    original_tokens=comp_stats.original_tokens,
                )
            except Exception as learn_err:
                logger.warning(f"parameter learning record failed (model-driven tool success): {learn_err}")
            trace.step("send_response", response_len=len(ai_response), mode="model_driven_tool_call")
            trace.finish(status="success")
            return

        if auto_tool_candidate:
            selected_tool = auto_tool_candidate["tool"]
            selected_tool_name = str(selected_tool.get("name", "")).strip()
            selected_server_name = str(selected_tool.get("server", "")).strip()
            inferred_auto_arguments, _ = _infer_tool_arguments_from_context(
                tool_name=selected_tool_name,
                server_name=selected_server_name,
                arguments={},
                content=content,
                attachments=attachments if isinstance(attachments, list) else [],
                active_mcp_manager=active_mcp_manager,
                workspace_root=str(workspace_context_config.get("workspace_root", "") or "") if isinstance(workspace_context_config, dict) else "",
                web_search_enabled=web_search_enabled,
            )
            inferred_auto_arguments = _normalize_tool_arguments_runtime(
                selected_tool_name,
                selected_server_name,
                inferred_auto_arguments,
                active_mcp_manager=active_mcp_manager,
            )
            if arguments_ready_for_auto_execution(
                selected_tool,
                inferred_auto_arguments,
                content=content,
                resolve_schema_type=(
                    active_mcp_manager._resolve_schema_type
                    if active_mcp_manager and hasattr(active_mcp_manager, "_resolve_schema_type")
                    else None
                ),
            ):
                candidate_reason = str(auto_tool_candidate.get("reason", "memory_plane_auto_route"))
                if candidate_reason == "memory_plane_auto_route":
                    routed_memory_plan = memory_control_plane.build_routed_tool_execution_plan(
                        client_id=client_id,
                        query=content,
                        candidate_tool_names=auto_tool_candidate.get("candidate_tool_names", [selected_tool_name]),
                        tool_catalog=auto_tool_candidate.get("candidate_tools", [selected_tool]),
                        arguments=inferred_auto_arguments,
                        context_engine=context_engine,
                        tem=tem,
                        server_name=selected_server_name,
                        dry_run=False,
                    )
                else:
                    routed_memory_plan = copy.deepcopy(auto_tool_candidate.get("memory_plan") or {})
                    routed_memory_plan["phase"] = "policy_routed_tool_call"
                    routed_memory_plan["tool_name"] = selected_tool_name
                    routed_memory_plan["server_name"] = selected_server_name
                    routed_memory_plan["query"] = content
                    retention = routed_memory_plan.setdefault("retention", {})
                    retention["arguments_schema_keys"] = sorted(inferred_auto_arguments.keys())
                    execution_policy = routed_memory_plan.setdefault("execution_policy", {})
                    execution_policy["recipe_preflight"] = tem.get_recipe_preflight(
                        tool_name=selected_tool_name,
                        arguments=inferred_auto_arguments,
                        server_name=selected_server_name,
                        task_description=content,
                    )
                    execution_policy["recommended_action"] = (
                        "blocked"
                        if execution_policy["recipe_preflight"].get("decision") == "block"
                        else execution_policy["recipe_preflight"].get("decision", "proceed")
                    )
                    execution_policy["candidate_tool_count"] = 1
                    execution_policy["fallback_reason"] = candidate_reason
                    routing = routed_memory_plan.setdefault("routing", {})
                    routing["selected_tools"] = [selected_tool_name]
                    routing["context_tool_names"] = [selected_tool_name]
                    routing["relevant_tools"] = [selected_tool_name]
                    routing["scores"] = [
                        {
                            "tool_name": selected_tool_name,
                            "final_score": 1.0,
                            "reason": candidate_reason,
                        }
                    ]
                    routing["reason"] = candidate_reason

                await manager.send_personal_message({
                    "type": "status",
                    "status": "processing",
                    "message": f"正在自动选择工具 {selected_server_name}.{selected_tool_name} ...",
                    "request_id": request_id,
                }, client_id)
                auto_execution = await _execute_tool_call_internal(
                    client_id=client_id,
                    request_id=request_id,
                    tool_name=selected_tool_name,
                    server_name=selected_server_name,
                    arguments=inferred_auto_arguments,
                    original_user_content=content,
                    model_id=model_id,
                    attachments=attachments if isinstance(attachments, list) else [],
                    skill_ids=skill_ids,
                    custom_system_prompt=custom_system_prompt,
                    policy_confirmed=False,
                    memory_plan_override=routed_memory_plan,
                    auto_tool_call=True,
                    auto_tool_reason=candidate_reason,
                    auto_tool_confidence=float(auto_tool_candidate.get("score", {}).get("final_score", 0.0) or 0.0),
                    allow_recipe_preflight_block=True,
                )
                _remember_request_result(request_id, auto_execution["final_payload"])
                await send_request_delivery(
                    client_id,
                    request_id,
                    auto_execution["delivery_status"],
                    message=auto_execution["delivery_message"],
                    details={
                        "tool_name": selected_tool_name,
                        "server_name": selected_server_name,
                        "auto_tool_call": True,
                        "fallback_after_model_tool_choice": True,
                    },
                )
                trace.step(
                    "auto_tool_fallback_executed",
                    tool=selected_tool_name,
                    server=selected_server_name,
                    confidence=auto_tool_candidate.get("score", {}).get("final_score", 0.0),
                )
                trace.finish(status="auto_tool_success" if auto_execution["success"] else "auto_tool_failed")
                return

        response = await _post_chat_with_retry(
            client,
            url=f"{api_base}/chat/completions",
            headers=headers,
            payload=payload,
            provider=provider,
        )

        if response.status_code == 200:
            result = response.json()
            ai_response = ""
            generated_images = _extract_generated_images_from_result(result)
            if isinstance(result, dict) and "choices" in result:
                choices = result.get("choices", [])
                if choices:
                    assistant_message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                    if isinstance(assistant_message, dict):
                        ai_response = _extract_text_content_from_message(assistant_message)
                        generated_images = _dedupe_generated_images(
                            generated_images + _extract_generated_images_from_message(assistant_message)
                        )
            if not ai_response and not generated_images:
                ai_response = result.get("content", "") or "AI????"
            if prefer_multimodal_model and str(ai_response).strip() == "AI响应为空":
                ai_response = (
                    "图像请求已发送到多模态模型，但模型没有返回可用文本结果。"
                    "请重试，或切换到另一个 VL 模型。"
                )
            if _looks_like_fabricated_tool_text(ai_response):
                ai_response = (
                    "我当前没有拿到真实的工具执行结果，因此不会伪造工具调用。"
                    "如果这个问题需要附件读取、网页访问或图像分析，我会在真实工具执行后再基于结果回答。"
                )
            if _requires_grounded_tool_result(
                query=content,
                attachments=attachments if isinstance(attachments, list) else [],
                attachment_plan=attachment_plan if isinstance(attachment_plan, dict) else {},
                model_id=model_id,
                image_data=image_data,
                image_data_list=image_data_list if isinstance(image_data_list, list) else [],
                workspace_root=str(workspace_context_config.get("workspace_root", "") or "") if isinstance(workspace_context_config, dict) else "",
            ):
                logger.warning(
                    "suppressing plain-text response for tool-grounded request without real tool events; query=%s",
                    content[:160],
                )
                ai_response = (
                    "这个问题需要真实工具执行结果才能可靠回答。"
                    "我不会用正文假装调用工具。"
                    "请稍候重试；系统会优先通过真实 MCP 工具获取结果后再回答。"
                )

            context_engine.record_assistant_response(client_id, ai_response)

            model_name = model_id
            for m in available_models:
                if m["id"] == model_id:
                    model_name = m["name"]
                    break

            await manager.send_personal_message({
                "type": "response",
                "content": ai_response,
                "generated_images": generated_images,
                "image_paths": [
                    str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                    for item in generated_images
                    if isinstance(item, dict) and str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                ],
                "model_used": model_id,
                "model_name": model_name,
                "memory": comp_stats.to_dict(),
                "memory_plane": memory_plan,
                "run_trace": run_trace,
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
                "metadata": {
                    "generated_images": generated_images,
                } if generated_images else {},
            }, client_id)
            _remember_request_result(
                request_id,
                {
                    "type": "response",
                    "content": ai_response,
                    "generated_images": generated_images,
                    "image_paths": [
                        str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                        for item in generated_images
                        if isinstance(item, dict) and str(item.get("url", "") or item.get("data_url", "") or item.get("path", "")).strip()
                    ],
                    "model_used": model_id,
                    "model_name": model_name,
                    "memory": comp_stats.to_dict(),
                    "memory_plane": memory_plan,
                    "run_trace": run_trace,
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat(),
                    "metadata": {
                        "generated_images": generated_images,
                    } if generated_images else {},
                },
            )
            await send_request_delivery(
                client_id,
                request_id,
                "completed",
                message="Chat response delivered",
                details={"model_id": model_id, "model_name": model_name},
            )
            try:
                parameter_learner.record_context_feedback(
                    response_ok=bool(ai_response and ai_response.strip()),
                    compression_ratio=comp_stats.compression_ratio,
                    compressed_tokens=comp_stats.compressed_tokens,
                    original_tokens=comp_stats.original_tokens,
                )
            except Exception as learn_err:
                logger.warning(f"parameter learning record failed (chat success): {learn_err}")
            trace.step("send_response", response_len=len(ai_response))
            trace.finish(status="success")
        else:
            error_text = response.text[:500]
            logger.error(f"API error: {response.status_code} - {error_text}")
            await manager.send_personal_message({
                "type": "error",
                "message": f"AI模型调用失败: {response.status_code} - {error_text}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }, client_id)
            _remember_request_result(
                request_id,
                {
                    "type": "error",
                    "message": f"AI模型调用失败: {response.status_code} - {error_text}",
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            await send_request_delivery(
                client_id,
                request_id,
                "failed",
                message=_friendly_provider_error(provider, response.status_code, error_text),
                details={"status_code": response.status_code},
            )
            try:
                parameter_learner.record_context_feedback(
                    response_ok=False,
                    compression_ratio=comp_stats.compression_ratio,
                    compressed_tokens=comp_stats.compressed_tokens,
                    original_tokens=comp_stats.original_tokens,
                )
            except Exception as learn_err:
                logger.warning(f"parameter learning record failed (chat api error): {learn_err}")
            trace.finish(status="api_error")

    except Exception as e:
        error_type = type(e).__name__
        error_msg = _friendly_exception_message(e)
        logger.error(f"failed to handle chat message - {error_type}: {error_msg}")
        logger.error(traceback.format_exc())
        trace.step("error", error_type=error_type, error_msg=error_msg)
        trace.finish(status="error")
        try:
            await manager.send_personal_message({
                "type": "error",
                "message": f"处理消息时出错: {error_msg}",
                "error_type": error_type,
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }, client_id)
            _remember_request_result(
                request_id,
                {
                    "type": "error",
                    "message": f"处理消息时出错: {error_msg}",
                    "error_type": error_type,
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            await send_request_delivery(
                client_id,
                request_id,
                "failed",
                message=f"Chat handling failed: {error_msg}",
                details={"error_type": error_type},
            )
        except Exception as notify_err:
            logger.warning(f"failed to send chat error response: {notify_err}")
        try:
            parameter_learner.record_context_feedback(
                response_ok=False,
                compression_ratio=1.0,
                compressed_tokens=1,
                original_tokens=1,
            )
        except Exception as learn_err:
            logger.warning(f"parameter learning record failed (chat exception): {learn_err}")
    finally:
        await _replay_cached_result_to_watchers(request_id)

async def handle_tool_call(message: dict, client_id: str):
    """处理工具调用（集成 TEM：调用前拦截 + 调用后学习）"""
    trace = ExecutionTrace(task="tool_call", client_id=client_id)
    request_id = message.get("request_id")
    try:
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        server_name = message.get("server_name", "")
        original_user_content = str(message.get("content", "") or "").strip()
        model_id = str(message.get("model_id") or "").strip() or _resolve_runtime_default_model()
        policy_confirmed = bool(message.get("policy_confirmed", False))
        attachments = message.get("attachments", [])
        skill_ids = [
            str(skill_id).strip()
            for skill_id in message.get("skill_ids", [])
            if str(skill_id).strip()
        ]
        custom_system_prompt = str(message.get("custom_system_prompt", "") or "").strip()
        workspace_context_config = (
            message.get("workspace_context")
            if isinstance(message.get("workspace_context"), dict)
            else {}
        )
        workspace_agent_profile = load_workspace_agent_runtime_profile(
            workspace_root=str(workspace_context_config.get("workspace_root", "") or ""),
            agent_name=str(workspace_context_config.get("agent_name", "") or ""),
        )
        workspace_agent_profile = _merge_workspace_agent_profile_with_session_overrides(
            workspace_agent_profile,
            workspace_context_config,
        )
        active_mcp_manager, workspace_mcp_metadata = await _get_effective_mcp_manager(workspace_context_config)
        trace.step("receive", tool=tool_name, server=server_name)

        if not tool_name:
            error_payload = {
                "type": "error",
                "message": "工具名称不能为空",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            }
            await manager.send_personal_message(error_payload, client_id)
            _remember_request_result(request_id, error_payload)
            await send_request_delivery(client_id, request_id, "failed", message="Tool name is required")
            trace.finish(status="error")
            return

        visible_tools = active_mcp_manager.get_all_tools() if active_mcp_manager else []
        skill_runtime = _resolve_skill_runtime_for_request(
            requested_skill_ids=skill_ids,
            query=original_user_content or f"{server_name}.{tool_name}",
            workspace_context_config=workspace_context_config,
            workspace_agent_profile=workspace_agent_profile,
            model_id=model_id,
            available_tools=visible_tools,
            scopes=["tool_call", "tool_routing"],
        )
        workspace_agent_profile = _merge_workspace_profile_with_skill_runtime(
            workspace_agent_profile,
            skill_runtime,
        )
        visible_tools = _filter_tools_by_workspace_agent_profile(visible_tools, workspace_agent_profile)
        visible_tool_keys = {
            (
                str(tool.get("server", "")).strip().lower(),
                str(tool.get("name", "")).strip().lower(),
            )
            for tool in visible_tools
        }
        requested_tool_key = (
            str(server_name or "").strip().lower(),
            str(tool_name or "").strip().lower(),
        )
        if visible_tool_keys and requested_tool_key not in visible_tool_keys:
            error_payload = {
                "type": "error",
                "message": f"Tool not visible in current session: {server_name}.{tool_name}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            }
            await manager.send_personal_message(error_payload, client_id)
            _remember_request_result(request_id, error_payload)
            await send_request_delivery(
                client_id,
                request_id,
                "blocked",
                message=f"Tool not visible in current session: {server_name}.{tool_name}",
            )
            trace.finish(status="tool_not_visible")
            return

        execution = await _execute_tool_call_internal(
            client_id=client_id,
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
            server_name=server_name,
            original_user_content=original_user_content,
            model_id=model_id,
            attachments=attachments if isinstance(attachments, list) else [],
            skill_ids=skill_ids,
            custom_system_prompt=custom_system_prompt,
            workspace_context_config=workspace_context_config,
            active_mcp_manager=active_mcp_manager,
            policy_confirmed=policy_confirmed,
            allow_recipe_preflight_block=False,
        )
        _remember_request_result(request_id, execution["final_payload"])
        await send_request_delivery(
            client_id,
            request_id,
            execution["delivery_status"],
            message=execution["delivery_message"],
            details={"tool_name": tool_name, "server_name": server_name, "success": execution["success"]},
        )
        if workspace_mcp_metadata.get("workspace_enabled"):
            trace.step("workspace_mcp", workspace_root=workspace_mcp_metadata.get("workspace_root", ""))
        try:
            parameter_learner.record_tool_feedback(
                success=execution["success"],
                blocked=False,
                latency_ms=float(execution.get("latency_ms", 0.0) or 0.0),
            )
        except Exception as learn_err:
            logger.warning(f"parameter learning record failed (ws tool): {learn_err}")
        trace.finish(status="success" if execution["success"] else "tool_error")

    except Exception as e:
        logger.error(f"failed to handle tool call: {e}")
        trace.step("error", error=str(e))
        trace.finish(status="error")
        tem.after_tool_call(
            client_id=client_id,
            tool_name=message.get("tool_name", "unknown"),
            arguments=message.get("arguments", {}),
            result=None,
            success=False,
            error_type=type(e).__name__,
            error_message=str(e),
            server_name=message.get("server_name", ""),
            task_description=f"WebSocket tool call exception: {message.get('tool_name', 'unknown')}",
        )
        tem.clear_pending_steps(client_id)
        await manager.send_personal_message({
            "type": "error",
            "message": f"工具调用失败: {str(e)}",
            "request_id": request_id,
        }, client_id)
        _remember_request_result(
            request_id,
            {
                "type": "error",
                "message": f"工具调用失败: {str(e)}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await send_request_delivery(
            client_id,
            request_id,
            "failed",
            message=f"Tool call failed: {str(e)}",
            details={"tool_name": message.get("tool_name", "unknown")},
        )
        try:
            parameter_learner.record_tool_feedback(
                success=False,
                blocked=False,
                latency_ms=0.0,
            )
        except Exception as learn_err:
            logger.warning(f"parameter learning record failed (ws exception): {learn_err}")
    finally:
        await _replay_cached_result_to_watchers(request_id)

async def handle_resource_read(message: dict, client_id: str):
    """处理资源读取"""
    request_id = message.get("request_id")
    try:
        uri = message.get("uri")
        server_name = message.get("server_name")
        
        if not uri:
            error_payload = {
                "type": "error",
                "message": "资源URI不能为空",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            }
            await manager.send_personal_message(error_payload, client_id)
            _remember_request_result(request_id, error_payload)
            await send_request_delivery(client_id, request_id, "failed", message="Resource URI is required")
            return
        
        if mcp_manager and hasattr(mcp_manager, 'read_resource'):
            result = await mcp_manager.read_resource(uri)
        else:
            result = {
                "success": False,
                "error": "MCP管理器不支持资源读取",
                "message": "请使用支持资源读取的MCP管理器"
            }
        
        await manager.send_personal_message({
            "type": "resource_result",
            "uri": uri,
            "server_name": server_name,
            "result": result,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }, client_id)
        _remember_request_result(
            request_id,
            {
                "type": "resource_result",
                "uri": uri,
                "server_name": server_name,
                "result": result,
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await send_request_delivery(
            client_id,
            request_id,
            "completed" if bool(result.get("success", False)) else "failed",
            message="Resource read completed" if bool(result.get("success", False)) else str(result.get("error") or result.get("message") or "Resource read failed"),
            details={"uri": uri, "server_name": server_name},
        )
        
    except Exception as e:
        logger.error(f"failed to handle resource read: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": f"处理资源读取时出错: {str(e)}",
            "request_id": request_id,
        }, client_id)
        _remember_request_result(
            request_id,
            {
                "type": "error",
                "message": f"处理资源读取时出错: {str(e)}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await send_request_delivery(client_id, request_id, "failed", message=f"Resource read failed: {str(e)}")
    finally:
        await _replay_cached_result_to_watchers(request_id)

async def handle_prompt_get(message: dict, client_id: str):
    """处理提示词获取"""
    request_id = message.get("request_id")
    try:
        prompt_name = message.get("prompt_name")
        arguments = message.get("arguments", {})
        server_name = message.get("server_name")
        
        if not prompt_name:
            error_payload = {
                "type": "error",
                "message": "提示词名称不能为空",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            }
            await manager.send_personal_message(error_payload, client_id)
            _remember_request_result(request_id, error_payload)
            await send_request_delivery(client_id, request_id, "failed", message="Prompt name is required")
            return
        
        if mcp_manager and hasattr(mcp_manager, 'get_prompt'):
            result = await mcp_manager.get_prompt(prompt_name, arguments)
        else:
            result = {
                "success": False,
                "error": "MCP管理器不支持提示词获取",
                "message": "请使用支持提示词获取的MCP管理器"
            }
        
        await manager.send_personal_message({
            "type": "prompt_result",
            "prompt_name": prompt_name,
            "arguments": arguments,
            "server_name": server_name,
            "result": result,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }, client_id)
        _remember_request_result(
            request_id,
            {
                "type": "prompt_result",
                "prompt_name": prompt_name,
                "arguments": arguments,
                "server_name": server_name,
                "result": result,
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await send_request_delivery(
            client_id,
            request_id,
            "completed" if bool(result.get("success", False)) else "failed",
            message="Prompt request completed" if bool(result.get("success", False)) else str(result.get("error") or result.get("message") or "Prompt request failed"),
            details={"prompt_name": prompt_name, "server_name": server_name},
        )
        
    except Exception as e:
        logger.error(f"failed to handle prompt retrieval: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": f"处理提示词获取时出错: {str(e)}",
            "request_id": request_id,
        }, client_id)
        _remember_request_result(
            request_id,
            {
                "type": "error",
                "message": f"处理提示词获取时出错: {str(e)}",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
        )
        await send_request_delivery(client_id, request_id, "failed", message=f"Prompt request failed: {str(e)}")
    finally:
        await _replay_cached_result_to_watchers(request_id)

async def handle_mcp_status_request(client_id: str, workspace_context_config: Optional[Dict[str, Any]] = None):
    """处理MCP状态请求"""
    try:
        active_mcp_manager, workspace_mcp_metadata = await _get_effective_mcp_manager(workspace_context_config)
        if active_mcp_manager and hasattr(active_mcp_manager, 'get_server_status'):
            result = active_mcp_manager.get_server_status()
        else:
            result = {}
        
        workspace_agent_profile = load_workspace_agent_runtime_profile(
            workspace_root=str(workspace_context_config.get("workspace_root", "") or ""),
            agent_name=str(workspace_context_config.get("agent_name", "") or ""),
        )
        workspace_agent_profile = _merge_workspace_agent_profile_with_session_overrides(
            workspace_agent_profile,
            workspace_context_config,
        )
        tools = active_mcp_manager.get_all_tools() if active_mcp_manager else []
        tools = _filter_tools_by_workspace_agent_profile(tools, workspace_agent_profile)
        connected = [s["name"] for s in (active_mcp_manager.servers if active_mcp_manager else []) if s.get("status") == "connected"]

        await manager.send_personal_message({
            "type": "mcp_status_update",
            "result": result,
            "mcp_servers_available": len(connected) > 0,
            "connected_servers": connected,
            "available_tools": [{"server": t.get("server", ""), "name": t["name"], "display_name": t.get("display_name", t["name"])} for t in tools],
            "providers_ready": bool(siliconflow_api_key or openrouter_api_key),
            "workspace_agent_profile": workspace_agent_profile,
            "workspace_mcp": workspace_mcp_metadata,
            "timestamp": datetime.now().isoformat(),
        }, client_id)
        
    except Exception as e:
        logger.error(f"failed to handle MCP status request: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": f"处理MCP状态请求时出错: {str(e)}"
        }, client_id)

# 静态文件服务
frontend_dist = Path(__file__).parent.parent / "frontend" / "build"
if frontend_dist.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dist / "static")), name="static")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """服务前端文件"""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API路径不存在")
        
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        else:
            # 返回index.html用于SPA路由
            return FileResponse(frontend_dist / "index.html")

# 主函数
def main():
    """主函数"""
    try:
        # 检查端口
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("localhost", DEFAULT_SERVER_PORT))
        sock.close()
        
        if result == 0:
            logger.warning(f"port {DEFAULT_SERVER_PORT} is in use, trying fallback port {FALLBACK_SERVER_PORT}")
            port = FALLBACK_SERVER_PORT
        else:
            port = DEFAULT_SERVER_PORT
        
        # 启动服务器
        uvicorn.run(
            "app:app",
            host="0.0.0.0",
            port=port,
            reload=False,
            log_level="info"
        )
        
    except KeyboardInterrupt:
        logger.info("interrupt received, exiting...")
    except Exception as e:
        logger.error(f"startup failed: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main() 
 
