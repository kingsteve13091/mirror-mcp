#!/usr/bin/env python3
"""Targeted browser probe for the natural tool execution chain.

This probe intentionally splits the natural auto-tool flow into three
independent checks so timeouts can be isolated:

1. Natural prompt -> real tool execution evidence reaches the browser.
2. Tool result -> frontend renders the compact tool bubble.
3. Model summary -> assistant continues after the tool result.

The probe reuses the existing browser smoke helpers and keeps the normal
runtime path intact, including Memory Plane / TEM behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

from browser_runtime_smoke import (
    BACKEND_AUTO_TOOL_ROUTING_URL,
    BACKEND_HEALTH_URL,
    CDP_DEFAULT_TIMEOUT_SECONDS,
    CDP_LONG_TIMEOUT_SECONDS,
    CDP_MODEL_TIMEOUT_SECONDS,
    DevToolsSession,
    FRONTEND_URL,
    SMOKE_CHAT_MODEL_ID,
    _begin_regression_sandbox,
    _full_frontend_reset_script,
    _get_page_ws_url,
    _navigate_reset_and_wait,
    _post_json,
    _restore_regression_sandbox,
    _start_browser,
    _wait_for_url_json,
)

TOOL_URL = "http://127.0.0.1:8000/health"
SUMMARY_PREFIX = "Endpoint summary:"
TOOL_SERVER = "fetch"
TOOL_NAME = "fetch"


def _configure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

WS_PROBE_SOURCE = r"""
(() => {
  if (window.__MCP_WS_PROBE_INSTALLED__) {
    return;
  }
  window.__MCP_WS_PROBE_INSTALLED__ = true;
  window.__MCP_WS_EVENTS__ = [];

  const NativeWebSocket = window.WebSocket;
  const safeClone = (value) => {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return value;
    }
  };

  const record = (direction, raw) => {
    let payload = raw;
    if (typeof raw === 'string') {
      try {
        payload = JSON.parse(raw);
      } catch (error) {
        payload = raw;
      }
    }
    const entry = {
      direction,
      timestamp: new Date().toISOString(),
      payload: safeClone(payload),
      type: payload && typeof payload === 'object' ? payload.type || '' : '',
      request_id: payload && typeof payload === 'object' ? payload.request_id || '' : '',
      server_name: payload && typeof payload === 'object' ? payload.server_name || '' : '',
      tool_name: payload && typeof payload === 'object' ? payload.tool_name || '' : '',
      run_trace_kind: payload && typeof payload === 'object' && payload.run_trace && typeof payload.run_trace === 'object'
        ? payload.run_trace.kind || ''
        : '',
      content: payload && typeof payload === 'object' && typeof payload.content === 'string'
        ? payload.content
        : '',
      delta: payload && typeof payload === 'object' && typeof payload.delta === 'string'
        ? payload.delta
        : '',
    };
    window.__MCP_WS_EVENTS__.push(entry);
    if (window.__MCP_WS_EVENTS__.length > 400) {
      window.__MCP_WS_EVENTS__ = window.__MCP_WS_EVENTS__.slice(-400);
    }
  };

  class ProbeWebSocket extends NativeWebSocket {
    constructor(...args) {
      super(...args);
      this.addEventListener('message', (event) => {
        record('in', event.data);
      });
    }

    send(data) {
      record('out', data);
      return super.send(data);
    }
  }

  Object.defineProperty(ProbeWebSocket, 'CONNECTING', { value: NativeWebSocket.CONNECTING });
  Object.defineProperty(ProbeWebSocket, 'OPEN', { value: NativeWebSocket.OPEN });
  Object.defineProperty(ProbeWebSocket, 'CLOSING', { value: NativeWebSocket.CLOSING });
  Object.defineProperty(ProbeWebSocket, 'CLOSED', { value: NativeWebSocket.CLOSED });

  window.WebSocket = ProbeWebSocket;
})();
"""


@dataclass
class ProbeStageResult:
    stage: str
    ok: bool
    details: dict[str, Any]


def _delivery_badge_script() -> str:
    return r"""
(() => {
  const candidates = Array.from(document.querySelectorAll('span,div,button'))
    .map((element) => (element.innerText || '').trim())
    .filter(Boolean);
  return candidates.find((text) => text === 'sent' || text === 'failed' || text === 'blocked' || text === 'processing') || '';
})()
"""


def _send_prompt_expression(prompt: str) -> str:
    return r"""
(() => {
  const textarea = document.querySelector('textarea');
  if (!textarea) {
    return {
      ok: false,
      reason: 'textarea missing',
      bodySample: document.body.innerText.slice(0, 1800),
    };
  }
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
  if (setter) {
    setter.call(textarea, __PROMPT_JSON__);
  } else {
    textarea.value = __PROMPT_JSON__;
  }
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  const buttons = Array.from(document.querySelectorAll('button'));
  const sendButton = buttons[buttons.length - 1];
  if (!sendButton || sendButton.disabled) {
    return {
      ok: false,
      reason: 'send button unavailable',
      buttonCount: buttons.length,
      bodySample: document.body.innerText.slice(0, 1800),
    };
  }
  sendButton.click();
  return {
    ok: true,
    queuedEvents: Array.isArray(window.__MCP_WS_EVENTS__) ? window.__MCP_WS_EVENTS__.length : -1,
    bodySample: document.body.innerText.slice(0, 1200),
  };
})()
""".replace("__PROMPT_JSON__", json.dumps(prompt, ensure_ascii=True))


async def _install_websocket_probe(session: DevToolsSession) -> None:
    await session.call(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": WS_PROBE_SOURCE},
        timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
    )


async def _clear_probe_events(session: DevToolsSession) -> None:
    await session.eval(
        r"""
(() => {
  window.__MCP_WS_EVENTS__ = [];
  return true;
})()
""",
        timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
    )


async def _get_probe_events(session: DevToolsSession) -> list[dict[str, Any]]:
    result = await session.eval(
        r"""
(() => Array.isArray(window.__MCP_WS_EVENTS__) ? window.__MCP_WS_EVENTS__ : [])()
""",
        timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
    )
    return result if isinstance(result, list) else []


async def _get_body_text(session: DevToolsSession, max_chars: int = 3000) -> str:
    result = await session.eval(
        r"""
(() => document.body ? (document.body.innerText || '').slice(0, __MAX_CHARS__) : '')()
""".replace("__MAX_CHARS__", str(max_chars)),
        timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
    )
    return str(result or "")


async def _get_delivery_badge(session: DevToolsSession) -> str:
    result = await session.eval(_delivery_badge_script(), timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS)
    return str(result or "")


async def _prepare_stage(session: DevToolsSession) -> None:
    await _navigate_reset_and_wait(session, _full_frontend_reset_script(SMOKE_CHAT_MODEL_ID), settle_seconds=2.0)
    await _clear_probe_events(session)


def _find_request_id(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("direction") == "out" and str(event.get("type", "")) == "chat":
            request_id = str(event.get("request_id", "")).strip()
            if request_id:
                return request_id
    return ""


def _find_tool_result_event(events: list[dict[str, Any]], request_id: str) -> Optional[dict[str, Any]]:
    for event in events:
        if event.get("direction") != "in":
            continue
        if str(event.get("type", "")) != "tool_result":
            continue
        if request_id and str(event.get("request_id", "")) != request_id:
            continue
        if str(event.get("run_trace_kind", "")) != "tool_call":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            run_trace = payload.get("run_trace")
            if isinstance(run_trace, dict) and str(run_trace.get("kind", "")) == "tool_call":
                return event
        return event
    return None


def _find_response_event(events: list[dict[str, Any]], request_id: str) -> Optional[dict[str, Any]]:
    for event in reversed(events):
        if event.get("direction") != "in":
            continue
        event_type = str(event.get("type", ""))
        if event_type not in {"response_done", "response", "chat_response"}:
            continue
        if request_id and str(event.get("request_id", "")) != request_id:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            content = str(payload.get("content", "") or "")
            if SUMMARY_PREFIX in content:
                return event
        if SUMMARY_PREFIX in str(event.get("content", "")):
            return event
    return None


async def _send_stage_prompt(session: DevToolsSession, prompt: str) -> dict[str, Any]:
    response = await session.eval(
        _send_prompt_expression(prompt),
        timeout_seconds=CDP_LONG_TIMEOUT_SECONDS,
    )
    if not isinstance(response, dict):
        return {"ok": False, "reason": "unexpected prompt send response", "raw": response}
    return response


async def _run_stage_tool_call_event(session: DevToolsSession) -> ProbeStageResult:
    prompt = f"Please open {TOOL_URL} with the appropriate tool."
    await _prepare_stage(session)
    send_result = await _send_stage_prompt(session, prompt)
    if not send_result.get("ok"):
        return ProbeStageResult("tool_call_event", False, send_result)

    started = time.perf_counter()
    request_id = ""
    last_body = ""
    last_badge = ""
    last_events: list[dict[str, Any]] = []

    while time.perf_counter() - started < 75:
        await asyncio.sleep(1.0)
        last_events = await _get_probe_events(session)
        request_id = request_id or _find_request_id(last_events)
        tool_event = _find_tool_result_event(last_events, request_id)
        last_badge = await _get_delivery_badge(session)
        last_body = await _get_body_text(session, max_chars=2400)
        if tool_event:
            payload = tool_event.get("payload") if isinstance(tool_event.get("payload"), dict) else {}
            return ProbeStageResult(
                "tool_call_event",
                True,
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                    "has_real_tool_call_event": True,
                    "event_type": tool_event.get("type"),
                    "run_trace_kind": tool_event.get("run_trace_kind"),
                    "server_name": tool_event.get("server_name") or (payload.get("server_name") if isinstance(payload, dict) else ""),
                    "tool_name": tool_event.get("tool_name") or (payload.get("tool_name") if isinstance(payload, dict) else ""),
                    "delivery_badge": last_badge,
                    "body_sample": last_body,
                },
            )
        error_event = next(
            (
                event for event in reversed(last_events)
                if event.get("direction") == "in"
                and str(event.get("type", "")) == "error"
                and (not request_id or str(event.get("request_id", "")) == request_id)
            ),
            None,
        )
        if error_event:
            return ProbeStageResult(
                "tool_call_event",
                False,
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                    "reason": "received error event before real tool evidence",
                    "delivery_badge": last_badge,
                    "error_event": error_event,
                    "body_sample": last_body,
                },
            )

    return ProbeStageResult(
        "tool_call_event",
        False,
        {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "request_id": request_id,
            "reason": "timed out waiting for real tool execution evidence",
            "delivery_badge": last_badge,
            "ws_event_count": len(last_events),
            "last_ws_events": last_events[-8:],
            "body_sample": last_body,
        },
    )


async def _run_stage_tool_result_bubble(session: DevToolsSession) -> ProbeStageResult:
    prompt = f"Please open {TOOL_URL} with the appropriate tool."
    await _prepare_stage(session)
    send_result = await _send_stage_prompt(session, prompt)
    if not send_result.get("ok"):
        return ProbeStageResult("tool_result_bubble", False, send_result)

    started = time.perf_counter()
    request_id = ""
    last_events: list[dict[str, Any]] = []
    last_body = ""
    last_badge = ""

    while time.perf_counter() - started < 90:
        await asyncio.sleep(1.0)
        last_events = await _get_probe_events(session)
        request_id = request_id or _find_request_id(last_events)
        bubble = await session.eval(
            r"""
(() => {
  const cards = Array.from(document.querySelectorAll('[data-testid="tool-result-card"]'));
  const match = cards.find((card) => {
    const text = card.innerText || '';
    return text.includes('Tool call') && text.includes(__TOOL_LABEL__);
  });
  if (!match) {
    return null;
  }
  return {
    text: (match.innerText || '').slice(0, 1200),
    detailsButtonLabel: (() => {
      const button = match.querySelector('[data-testid="toggle-tool-result-card"]');
      return button ? (button.innerText || '').trim() : '';
    })(),
  };
})()
""".replace("__TOOL_LABEL__", json.dumps(f"{TOOL_SERVER}.{TOOL_NAME}", ensure_ascii=True)),
            timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
        )
        last_badge = await _get_delivery_badge(session)
        last_body = await _get_body_text(session, max_chars=2600)
        tool_event = _find_tool_result_event(last_events, request_id)
        if isinstance(bubble, dict):
            return ProbeStageResult(
                "tool_result_bubble",
                True,
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                    "has_real_tool_call_event": bool(tool_event),
                    "has_tool_result_bubble": True,
                    "delivery_badge": last_badge,
                    "bubble_preview": bubble.get("text", ""),
                    "details_button": bubble.get("detailsButtonLabel", ""),
                    "body_sample": last_body,
                },
            )
        error_event = next(
            (
                event for event in reversed(last_events)
                if event.get("direction") == "in"
                and str(event.get("type", "")) == "error"
                and (not request_id or str(event.get("request_id", "")) == request_id)
            ),
            None,
        )
        if error_event:
            return ProbeStageResult(
                "tool_result_bubble",
                False,
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                    "reason": "received error event before tool bubble rendered",
                    "has_real_tool_call_event": bool(tool_event),
                    "delivery_badge": last_badge,
                    "error_event": error_event,
                    "body_sample": last_body,
                },
            )

    return ProbeStageResult(
        "tool_result_bubble",
        False,
        {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "request_id": request_id,
            "reason": "timed out waiting for frontend tool bubble",
            "has_real_tool_call_event": bool(_find_tool_result_event(last_events, request_id)),
            "delivery_badge": last_badge,
            "ws_event_count": len(last_events),
            "last_ws_events": last_events[-8:],
            "body_sample": last_body,
        },
    )


async def _run_stage_model_summary(session: DevToolsSession) -> ProbeStageResult:
    prompt = (
        f"Please open {TOOL_URL} with the appropriate tool. "
        f"After using the tool, answer in one sentence starting with \"{SUMMARY_PREFIX}\"."
    )
    await _prepare_stage(session)
    send_result = await _send_stage_prompt(session, prompt)
    if not send_result.get("ok"):
        return ProbeStageResult("model_summary", False, send_result)

    started = time.perf_counter()
    request_id = ""
    last_events: list[dict[str, Any]] = []
    last_body = ""
    last_badge = ""

    while time.perf_counter() - started < 130:
        await asyncio.sleep(1.0)
        last_events = await _get_probe_events(session)
        request_id = request_id or _find_request_id(last_events)
        tool_event = _find_tool_result_event(last_events, request_id)
        response_event = _find_response_event(last_events, request_id)
        summary_state = await session.eval(
            r"""
(() => {
  const body = document.body ? (document.body.innerText || '') : '';
  const index = body.lastIndexOf(__SUMMARY_PREFIX__);
  return {
    hasSummaryInDom: index >= 0,
    summarySnippet: index >= 0 ? body.slice(index, index + 280) : '',
  };
})()
""".replace("__SUMMARY_PREFIX__", json.dumps(SUMMARY_PREFIX, ensure_ascii=True)),
            timeout_seconds=CDP_DEFAULT_TIMEOUT_SECONDS,
        )
        last_badge = await _get_delivery_badge(session)
        last_body = await _get_body_text(session, max_chars=3000)
        if tool_event and response_event and isinstance(summary_state, dict) and summary_state.get("hasSummaryInDom"):
            payload = response_event.get("payload") if isinstance(response_event.get("payload"), dict) else {}
            content_preview = str(payload.get("content", "") or "")[:280] if isinstance(payload, dict) else ""
            return ProbeStageResult(
                "model_summary",
                True,
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                    "has_real_tool_call_event": True,
                    "has_summary_response_event": True,
                    "has_summary_in_dom": True,
                    "delivery_badge": last_badge,
                    "response_event_type": response_event.get("type"),
                    "summary_snippet": summary_state.get("summarySnippet", ""),
                    "response_preview": content_preview,
                    "body_sample": last_body,
                },
            )
        error_event = next(
            (
                event for event in reversed(last_events)
                if event.get("direction") == "in"
                and str(event.get("type", "")) == "error"
                and (not request_id or str(event.get("request_id", "")) == request_id)
            ),
            None,
        )
        if error_event:
            return ProbeStageResult(
                "model_summary",
                False,
                {
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "request_id": request_id,
                    "reason": "received error event before summary completed",
                    "has_real_tool_call_event": bool(tool_event),
                    "has_summary_response_event": bool(response_event),
                    "delivery_badge": last_badge,
                    "error_event": error_event,
                    "body_sample": last_body,
                },
            )

    return ProbeStageResult(
        "model_summary",
        False,
        {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "request_id": request_id,
            "reason": "timed out waiting for model summary after tool result",
            "has_real_tool_call_event": bool(_find_tool_result_event(last_events, request_id)),
            "has_summary_response_event": bool(_find_response_event(last_events, request_id)),
            "delivery_badge": last_badge,
            "ws_event_count": len(last_events),
            "last_ws_events": last_events[-10:],
            "body_sample": last_body,
        },
    )


async def _run_probe(stages: list[str]) -> list[ProbeStageResult]:
    ws_url = _get_page_ws_url()
    async with DevToolsSession(ws_url) as session:
        await _install_websocket_probe(session)
        results: list[ProbeStageResult] = []
        stage_map = {
            "tool_call_event": _run_stage_tool_call_event,
            "tool_result_bubble": _run_stage_tool_result_bubble,
            "model_summary": _run_stage_model_summary,
        }
        for stage_name in stages:
            results.append(await stage_map[stage_name](session))
        return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the natural tool execution chain in three isolated stages.")
    parser.add_argument(
        "--stage",
        action="append",
        choices=["tool_call_event", "tool_result_bubble", "model_summary"],
        help="Run only the named stage. Can be supplied multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    _configure_utf8_stdio()
    args = _parse_args()
    stages = args.stage or ["tool_call_event", "tool_result_bubble", "model_summary"]

    _wait_for_url_json(BACKEND_HEALTH_URL, timeout_seconds=20.0)
    auto_tool_routing = _post_json(BACKEND_AUTO_TOOL_ROUTING_URL, {"mode": "memory_plane_plus_fallback"})
    if str(auto_tool_routing.get("mode")) != "memory_plane_plus_fallback":
        raise RuntimeError(
            "Failed to set backend auto tool routing to memory_plane_plus_fallback: "
            + json.dumps(auto_tool_routing, ensure_ascii=True)
        )

    sandbox = _begin_regression_sandbox()
    sandbox_id = str(sandbox.get("sandbox_id", "")).strip()
    if not sandbox_id:
        raise RuntimeError(f"Failed to create regression sandbox: {json.dumps(sandbox, ensure_ascii=True)}")

    process = _start_browser()
    try:
        results = asyncio.run(_run_probe(stages))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
        _restore_regression_sandbox(sandbox_id)

    all_ok = True
    print("=" * 68)
    print("MCP Mirror Browser Tool Chain Probe")
    print("=" * 68)
    print(json.dumps({"sandbox_id": sandbox_id, "stages": stages}, ensure_ascii=False, indent=2))
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.stage}")
        print(json.dumps(result.details, ensure_ascii=False, indent=2))
        if not result.ok:
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
