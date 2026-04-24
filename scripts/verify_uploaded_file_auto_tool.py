#!/usr/bin/env python3
"""Verify uploaded-file auto tool flow through the real backend.

Checks:
- upload a file outside the workspace via /api/upload
- send a normal chat message with that uploaded attachment over WebSocket
- observe automatic filesystem read_file/read_text_file execution
- observe a model summary response that mentions the file marker
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import websockets


BACKEND = "http://127.0.0.1:8000"
WS_BACKEND = "ws://127.0.0.1:8000"
SUMMARY_TOKEN = "UploadSummary:"
MARKER = "FINAL_MARKER: outside-upload-verification-success"


def http_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def upload_file(path: Path) -> dict[str, Any]:
    boundary = f"----mcp-mirror-{uuid.uuid4().hex}"
    file_bytes = path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                'Content-Disposition: form-data; name="file"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: text/plain\r\n\r\n",
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    request = urllib.request.Request(
        f"{BACKEND}/api/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def make_outside_file() -> Path:
    outside_dir = Path(tempfile.gettempdir()) / "mcp_mirror_outside_upload"
    outside_dir.mkdir(parents=True, exist_ok=True)
    path = outside_dir / "resume_summary_test.txt"
    lines = [f"Noise line {index:03d}: filler text for truncation." for index in range(160)]
    lines.extend(
        [
            "Candidate name: Alice Chen",
            "Research focus: multimodal reasoning and memory-governed MCP systems.",
            "Key contribution: built MCP Mirror with Tool Execution Memory and Guard.",
            MARKER,
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def verify_flow() -> dict[str, Any]:
    health = http_json(f"{BACKEND}/health")
    auto_tool = post_json(
        f"{BACKEND}/api/runtime/auto-tool-routing",
        {"mode": "memory_plane_plus_fallback"},
    )
    outside_path = make_outside_file()
    upload = upload_file(outside_path)

    attachment = {
        "filename": upload.get("filename"),
        "original_filename": upload.get("original_filename"),
        "file_path": upload.get("file_path"),
        "url": f"{BACKEND}/api/uploads/{upload.get('filename')}",
        "size": upload.get("size"),
        "mime_type": upload.get("mime_type"),
        "is_image": False,
        "parse_status": upload.get("parse_status"),
        "parse_mode": upload.get("parse_mode"),
        "parser": upload.get("parser"),
        "preview_text": upload.get("preview_text"),
        "full_text_chars": upload.get("full_text_chars"),
        "visible_text_chars": upload.get("visible_text_chars"),
        "preview_truncated": upload.get("preview_truncated"),
        "parse_error": upload.get("parse_error"),
    }

    client_id = f"verify-upload-{uuid.uuid4().hex[:8]}"
    request_id = f"verify-{uuid.uuid4().hex[:8]}"
    payload = {
        "type": "chat",
        "request_id": request_id,
        "content": (
            "Please inspect the uploaded file and tell me the exact FINAL_MARKER line. "
            "Use the appropriate filesystem reading tool automatically if needed. "
            f'Reply in one sentence starting with "{SUMMARY_TOKEN}".'
        ),
        "model_id": "Qwen/Qwen3-8B",
        "attachments": [attachment],
        "skill_ids": [],
        "custom_system_prompt": "",
    }

    observed: list[dict[str, Any]] = []
    timeout_count = 0
    async with websockets.connect(f"{WS_BACKEND}/ws/{client_id}", max_size=20_000_000) as websocket:
        await websocket.recv()  # runtime_connection
        await websocket.send(json.dumps(payload, ensure_ascii=False))
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                raw_message = await asyncio.wait_for(websocket.recv(), timeout=20)
            except TimeoutError:
                timeout_count += 1
                if timeout_count >= 3:
                    break
                continue
            message = json.loads(raw_message)
            observed.append(message)
            if message.get("type") == "response" and SUMMARY_TOKEN in str(message.get("content", "")):
                break

    tool_results = [item for item in observed if item.get("type") == "tool_result"]
    responses = [item for item in observed if item.get("type") == "response"]
    read_tool_results = [
        item
        for item in tool_results
        if item.get("server_name") == "filesystem"
        and item.get("tool_name") in {"read_file", "read_text_file"}
    ]
    latest_response = responses[-1] if responses else {}
    response_content = str(latest_response.get("content", ""))

    return {
        "ok": bool(read_tool_results) and SUMMARY_TOKEN in response_content and MARKER in response_content,
        "health": {
            "status": health.get("status"),
            "connected_servers": health.get("mcp", {}).get("connected_servers", []),
        },
        "auto_tool_routing": auto_tool,
        "outside_path": str(outside_path),
        "uploaded_path": upload.get("file_path"),
        "upload_parse_status": upload.get("parse_status"),
        "upload_preview_truncated": upload.get("preview_truncated"),
        "tool_results": [
            {
                "server_name": item.get("server_name"),
                "tool_name": item.get("tool_name"),
                "success": item.get("result", {}).get("success")
                if isinstance(item.get("result"), dict)
                else None,
                "arguments": item.get("arguments"),
            }
            for item in tool_results
        ],
        "response_content": response_content,
        "message_types": [item.get("type") for item in observed],
        "observed_messages": observed,
    }


def main() -> int:
    result = asyncio.run(verify_flow())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
