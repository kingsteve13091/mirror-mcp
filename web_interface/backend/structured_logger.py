"""
结构化日志 + 执行轨迹记录器
提供 JSON 格式日志和每次任务的可回放执行轨迹。
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)


class JSONFormatter(logging.Formatter):
    """将日志输出为单行 JSON，便于机器解析和 Agent 消费。"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            entry["request_id"] = record.request_id
        if hasattr(record, "task_id"):
            entry["task_id"] = record.task_id
        if hasattr(record, "server_name"):
            entry["server_name"] = record.server_name
        if hasattr(record, "tool_name"):
            entry["tool_name"] = record.tool_name
        if hasattr(record, "latency_ms"):
            entry["latency_ms"] = record.latency_ms
        if hasattr(record, "status"):
            entry["status"] = record.status
        if record.exc_info and record.exc_info[1]:
            entry["error"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False)


def setup_structured_logging(name: str = "mcp_mirror") -> logging.Logger:
    """配置结构化日志，同时输出到控制台（人类可读）和文件（JSON）。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    logger.addHandler(console)

    json_file = ARTIFACTS_DIR / "backend.jsonl"
    fh = logging.FileHandler(str(json_file), encoding="utf-8")
    fh.setFormatter(JSONFormatter())
    logger.addHandler(fh)

    return logger


class ExecutionTrace:
    """
    单次任务的执行轨迹记录器。
    用法：
        trace = ExecutionTrace(task="chat_message", client_id="abc")
        trace.step("receive_message", input={"content": "hello"})
        trace.step("call_tool", tool="analyze", status="ok", latency_ms=120)
        trace.finish(status="success")
    完成后自动写入 artifacts/{trace_id}.json
    """

    def __init__(self, task: str, client_id: str = "", metadata: Optional[dict] = None):
        self.trace_id = str(uuid.uuid4())[:12]
        self.task = task
        self.client_id = client_id
        self.start_time = time.time()
        self.steps: list[dict[str, Any]] = []
        self.metadata = metadata or {}
        self._finished = False

    def step(self, name: str, **kwargs):
        """记录一个执行步骤。"""
        entry = {
            "name": name,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "elapsed_ms": round((time.time() - self.start_time) * 1000, 1),
        }
        entry.update(kwargs)
        self.steps.append(entry)

    def finish(self, status: str = "success", result: Any = None):
        """结束轨迹并持久化到 artifacts/ 目录。"""
        if self._finished:
            return
        self._finished = True
        total_ms = round((time.time() - self.start_time) * 1000, 1)

        trace_data = {
            "trace_id": self.trace_id,
            "task": self.task,
            "client_id": self.client_id,
            "started_at": datetime.fromtimestamp(
                self.start_time, tz=timezone.utc
            ).isoformat(),
            "total_ms": total_ms,
            "status": status,
            "steps": self.steps,
            "metadata": self.metadata,
        }
        if result is not None:
            trace_data["result"] = result

        out_path = ARTIFACTS_DIR / f"{self.trace_id}.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(trace_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to persist execution trace %s: %s", self.trace_id, e)

    def __del__(self):
        if not self._finished:
            self.finish(status="abandoned")
