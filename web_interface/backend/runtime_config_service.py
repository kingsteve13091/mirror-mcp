# -*- coding: utf-8 -*-

"""Runtime provider, model, and tool policy services for the backend."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import httpx


logger = logging.getLogger(__name__)


class RuntimeConfigService:
    """Own runtime-only provider configuration and execution policy state."""

    def __init__(
        self,
        *,
        build_available_models: Callable[[str, List[Dict[str, Any]]], List[Dict[str, Any]]],
        default_model_id: str,
        openrouter_default_model_id: str,
        siliconflow_base_url_default: str,
        openrouter_base_url_default: str,
        get_shared_http_client: Callable[[], httpx.AsyncClient],
    ) -> None:
        self.build_available_models = build_available_models
        self.default_model_id = default_model_id
        self.openrouter_default_model_id = openrouter_default_model_id
        self.siliconflow_base_url_default = siliconflow_base_url_default
        self.openrouter_base_url_default = openrouter_base_url_default
        self.get_shared_http_client = get_shared_http_client

        self.siliconflow_api_key: Optional[str] = None
        self.siliconflow_base_url: Optional[str] = None
        self.openrouter_api_key: Optional[str] = None
        self.openrouter_base_url: Optional[str] = None
        self.available_models: List[Dict[str, Any]] = []

        self.provider_overrides: Dict[str, Any] = {
            "siliconflow_api_key": None,
            "siliconflow_base_url": None,
            "openrouter_api_key": None,
            "openrouter_base_url": None,
            "default_model": None,
            "custom_models": [],
        }
        self.tool_policy: Dict[str, Any] = {
            "enabled": True,
            "default_action": "allow",
            "tool_actions": {},
            "server_actions": {},
            "system_actions": {
                "terminal_command": "confirm",
                "process_control": "confirm",
                "test_runner": "allow",
                "log_read": "allow",
                "browser_smoke": "allow",
                "workspace_file_op": "confirm",
            },
            "deny_risky_write_paths": True,
        }
        self.auto_tool_routing: Dict[str, Any] = {
            "mode": "memory_plane_plus_fallback",
        }
        self.memory_plane_runtime: Dict[str, Any] = {
            "absorb_system_op_audit": True,
        }

    def normalize_openrouter_base_url(self, value: Optional[str]) -> str:
        base = (value or self.openrouter_base_url_default).strip().rstrip("/")
        if not base:
            return self.openrouter_base_url_default
        if base.endswith("/v1"):
            return base
        return f"{base}/v1"

    def normalize_siliconflow_base_url(self, value: Optional[str]) -> str:
        base = (value or self.siliconflow_base_url_default).strip().rstrip("/")
        if not base:
            return self.siliconflow_base_url_default
        if base.endswith("/v1"):
            return base
        return f"{base}/v1"

    def get_available_provider_names(self) -> set[str]:
        providers: set[str] = set()
        if self.siliconflow_api_key:
            providers.add("siliconflow")
        if self.openrouter_api_key:
            providers.add("openrouter")
        return providers

    def get_active_available_models(self) -> List[Dict[str, Any]]:
        configured_providers = self.get_available_provider_names()
        if not configured_providers:
            return list(self.available_models)
        filtered_models = [
            model
            for model in self.available_models
            if str(model.get("provider", "")).strip().lower() in configured_providers
        ]
        return filtered_models or list(self.available_models)

    def resolve_runtime_default_model(self) -> str:
        active_models = self.get_active_available_models()
        if not active_models:
            return ""

        active_ids = {str(model.get("id", "")) for model in active_models}
        requested_default = str(self.provider_overrides.get("default_model") or "").strip()
        if requested_default and requested_default in active_ids:
            return requested_default

        if self.openrouter_api_key and self.openrouter_default_model_id in active_ids:
            return self.openrouter_default_model_id

        if self.siliconflow_api_key and self.default_model_id in active_ids:
            return self.default_model_id

        return str(active_models[0].get("id", "")).strip()

    def is_model_available_for_runtime(self, model_id: str) -> bool:
        normalized_model_id = str(model_id or "").strip()
        if not normalized_model_id:
            return False
        return any(
            str(model.get("id", "")).strip() == normalized_model_id
            for model in self.get_active_available_models()
        )

    def build_model_catalog_with_runtime_status(
        self,
        models: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        configured_providers = self.get_available_provider_names()
        enriched_models: List[Dict[str, Any]] = []
        for model in models:
            provider = str(model.get("provider", "")).strip().lower()
            enriched_models.append(
                {
                    **model,
                    "available": provider in configured_providers if configured_providers else True,
                    "provider_configured": provider in configured_providers if configured_providers else True,
                }
            )
        return enriched_models

    def resolve_provider_for_model(self, model_id: str) -> str:
        if model_id.startswith("google/") or model_id.endswith(":free"):
            return "openrouter"
        for model in self.available_models:
            if model.get("id") == model_id:
                provider = model.get("provider", "")
                if provider:
                    return str(provider)
        return "siliconflow"

    def get_provider_runtime(self, provider: str) -> tuple[Optional[str], str]:
        if provider == "openrouter":
            return self.openrouter_api_key, self.normalize_openrouter_base_url(self.openrouter_base_url)
        return self.siliconflow_api_key, self.normalize_siliconflow_base_url(self.siliconflow_base_url)

    def resolve_model_name(self, model_id: str) -> str:
        for model in self.available_models:
            if model.get("id") == model_id:
                return str(model.get("name") or model_id)
        return model_id

    def friendly_provider_error(self, provider: str, status_code: int, error_text: str) -> str:
        if provider == "openrouter" and status_code == 429:
            return (
                "当前 OpenRouter 免费线路触发限流（429）。"
                "请稍后重试，或临时切换到其他模型。"
            )
        return f"{provider} API error: {status_code} - {error_text[:300]}"

    def initialize_providers(self) -> bool:
        """Initialize runtime provider credentials and model catalog from overrides/env."""
        silicon_env_key = self.provider_overrides.get("siliconflow_api_key") or os.getenv("SILICONFLOW_API_KEY")
        self.siliconflow_base_url = self.normalize_siliconflow_base_url(
            self.provider_overrides.get("siliconflow_base_url")
            or os.getenv("SILICONFLOW_BASE_URL", os.getenv("SILICONFLOW_API_BASE", self.siliconflow_base_url_default))
        )
        openrouter_env_key = self.provider_overrides.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY")
        self.openrouter_base_url = self.normalize_openrouter_base_url(
            self.provider_overrides.get("openrouter_base_url")
            or os.getenv("OPENROUTER_BASE_URL", os.getenv("OPENROUTER_API_BASE", self.openrouter_base_url_default))
        )

        has_siliconflow = bool(silicon_env_key)
        has_openrouter = bool(openrouter_env_key)

        if silicon_env_key:
            self.siliconflow_api_key = str(silicon_env_key)
            logger.info("Using SILICONFLOW_API_KEY from environment")
        else:
            self.siliconflow_api_key = None
            logger.warning("SILICONFLOW_API_KEY not found, SiliconFlow channel disabled")

        if openrouter_env_key:
            self.openrouter_api_key = str(openrouter_env_key)
            logger.info("Using OPENROUTER_API_KEY from environment")
        else:
            self.openrouter_api_key = None
            logger.warning("OPENROUTER_API_KEY not found, OpenRouter channel disabled")

        self.available_models = self.build_available_models(
            self.openrouter_default_model_id,
            self.provider_overrides.get("custom_models") or [],
        )

        if has_siliconflow:
            logger.info("SiliconFlow API configured, base_url=%s", self.siliconflow_base_url)
        else:
            logger.info("SiliconFlow API not configured, model list only")

        if has_openrouter:
            logger.info("OpenRouter API configured, base_url=%s", self.openrouter_base_url)
        else:
            logger.info("OpenRouter API not configured, model list only")

        logger.info("Available models total: %s", len(self.available_models))
        return has_siliconflow or has_openrouter

    def get_provider_state(self) -> dict[str, Any]:
        active_models = self.get_active_available_models()
        default_model = self.resolve_runtime_default_model()
        full_model_catalog = self.build_model_catalog_with_runtime_status(self.available_models)

        return {
            "providers": {
                "siliconflow": {
                    "configured": self.siliconflow_api_key is not None,
                    "runtime_override": bool(self.provider_overrides.get("siliconflow_api_key")),
                    "base_url": self.normalize_siliconflow_base_url(self.siliconflow_base_url),
                },
                "openrouter": {
                    "configured": self.openrouter_api_key is not None,
                    "runtime_override": bool(self.provider_overrides.get("openrouter_api_key")),
                    "base_url": self.normalize_openrouter_base_url(self.openrouter_base_url),
                },
            },
            "models": {
                "default": default_model,
                "available": full_model_catalog,
                "count": len(full_model_catalog),
                "active_count": len(active_models),
                "custom_count": len(self.provider_overrides.get("custom_models") or []),
            },
            "runtime_overrides": {
                "has_siliconflow_key": bool(self.provider_overrides.get("siliconflow_api_key")),
                "siliconflow_base_url": self.provider_overrides.get("siliconflow_base_url"),
                "has_openrouter_key": bool(self.provider_overrides.get("openrouter_api_key")),
                "openrouter_base_url": self.provider_overrides.get("openrouter_base_url"),
                "default_model": self.provider_overrides.get("default_model"),
                "custom_models": self.provider_overrides.get("custom_models") or [],
            },
        }

    def clear_provider_overrides(self) -> None:
        self.provider_overrides["siliconflow_api_key"] = None
        self.provider_overrides["siliconflow_base_url"] = None
        self.provider_overrides["openrouter_api_key"] = None
        self.provider_overrides["openrouter_base_url"] = None
        self.provider_overrides["default_model"] = None
        self.provider_overrides["custom_models"] = []

    def update_provider_overrides(
        self,
        *,
        siliconflow_api_key: Optional[str],
        siliconflow_base_url: Optional[str],
        openrouter_api_key: Optional[str],
        openrouter_base_url: Optional[str],
        default_model: Optional[str],
        custom_models: List[Dict[str, Any]],
    ) -> None:
        self.provider_overrides["siliconflow_api_key"] = (siliconflow_api_key or "").strip() or None
        self.provider_overrides["siliconflow_base_url"] = (siliconflow_base_url or "").strip() or None
        self.provider_overrides["openrouter_api_key"] = (openrouter_api_key or "").strip() or None
        self.provider_overrides["openrouter_base_url"] = (openrouter_base_url or "").strip() or None
        self.provider_overrides["default_model"] = (default_model or "").strip() or None
        self.provider_overrides["custom_models"] = list(custom_models or [])

    def normalize_tool_policy_action(self, value: Any) -> str:
        action = str(value or "allow").strip().lower()
        if action not in {"allow", "confirm", "deny"}:
            return "allow"
        return action

    def get_tool_policy_state(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.tool_policy.get("enabled", True)),
            "default_action": self.normalize_tool_policy_action(self.tool_policy.get("default_action", "allow")),
            "tool_actions": {
                str(key): self.normalize_tool_policy_action(value)
                for key, value in (self.tool_policy.get("tool_actions") or {}).items()
                if str(key).strip()
            },
            "server_actions": {
                str(key): self.normalize_tool_policy_action(value)
                for key, value in (self.tool_policy.get("server_actions") or {}).items()
                if str(key).strip()
            },
            "system_actions": {
                str(key): self.normalize_tool_policy_action(value)
                for key, value in (self.tool_policy.get("system_actions") or {}).items()
                if str(key).strip()
            },
            "deny_risky_write_paths": bool(self.tool_policy.get("deny_risky_write_paths", True)),
        }

    def get_memory_plane_runtime_state(self) -> dict[str, Any]:
        return {
            "absorb_system_op_audit": bool(self.memory_plane_runtime.get("absorb_system_op_audit", True)),
        }

    def update_memory_plane_runtime(self, *, absorb_system_op_audit: bool) -> dict[str, Any]:
        self.memory_plane_runtime["absorb_system_op_audit"] = bool(absorb_system_op_audit)
        return self.get_memory_plane_runtime_state()

    def update_tool_policy(
        self,
        *,
        enabled: bool,
        default_action: Any,
        tool_actions: Dict[str, Any],
        server_actions: Dict[str, Any],
        system_actions: Optional[Dict[str, Any]] = None,
        deny_risky_write_paths: bool,
    ) -> None:
        self.tool_policy["enabled"] = bool(enabled)
        self.tool_policy["default_action"] = self.normalize_tool_policy_action(default_action)
        self.tool_policy["tool_actions"] = {
            str(key).strip(): self.normalize_tool_policy_action(value)
            for key, value in (tool_actions or {}).items()
            if str(key).strip()
        }
        self.tool_policy["server_actions"] = {
            str(key).strip(): self.normalize_tool_policy_action(value)
            for key, value in (server_actions or {}).items()
            if str(key).strip()
        }
        if system_actions is not None:
            self.tool_policy["system_actions"] = {
                str(key).strip(): self.normalize_tool_policy_action(value)
                for key, value in (system_actions or {}).items()
                if str(key).strip()
            }
        self.tool_policy["deny_risky_write_paths"] = bool(deny_risky_write_paths)

    def normalize_auto_tool_routing_mode(self, value: Any) -> str:
        mode = str(value or "memory_plane_plus_fallback").strip().lower()
        if mode not in {"memory_plane_only", "memory_plane_plus_fallback"}:
            return "memory_plane_plus_fallback"
        return mode

    def get_auto_tool_routing_state(self) -> dict[str, Any]:
        mode = self.normalize_auto_tool_routing_mode(self.auto_tool_routing.get("mode"))
        return {
            "mode": mode,
            "fallback_enabled": mode == "memory_plane_plus_fallback",
            "file_path_fallback_enabled": mode == "memory_plane_plus_fallback",
            "url_fetch_fallback_enabled": mode == "memory_plane_plus_fallback",
            "available_modes": [
                {
                    "id": "memory_plane_only",
                    "label": "Memory Plane only",
                    "description": "Only execute tools selected by the research Memory Plane router.",
                },
                {
                    "id": "memory_plane_plus_fallback",
                    "label": "Memory Plane + product fallback",
                    "description": "Use Memory Plane first, then narrow explicit file/URL fallbacks for product usability.",
                },
            ],
        }

    def update_auto_tool_routing(self, mode: Any) -> None:
        self.auto_tool_routing["mode"] = self.normalize_auto_tool_routing_mode(mode)

    def is_high_risk_path_value(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.replace("/", "\\").lower()
        return (
            normalized.startswith("c:\\")
            or normalized.startswith("d:\\")
            or "..\\" in normalized
            or normalized.startswith("\\\\")
            or normalized.startswith("/etc/")
            or normalized.startswith("/usr/")
            or normalized.startswith("/var/")
            or normalized.startswith("/home/")
        )

    def tool_policy_requires_path_review(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        normalized_tool_name = str(tool_name or "").strip().lower()
        write_like = {"write_file", "edit_file", "create_directory", "move_file", "delete_file", "remove_file"}
        if normalized_tool_name not in write_like:
            return False
        for key, value in (arguments or {}).items():
            if (
                str(key).lower() in {"path", "target_path", "source_path", "destination", "destination_path"}
                and self.is_high_risk_path_value(value)
            ):
                return True
        return False

    def evaluate_tool_policy(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        policy_confirmed: bool = False,
    ) -> Optional[dict[str, Any]]:
        policy = self.get_tool_policy_state()
        if not policy["enabled"]:
            return None

        resolved_tool_key = f"{server_name}.{tool_name}" if server_name else tool_name
        action = policy["tool_actions"].get(resolved_tool_key)
        reason = ""
        if not action and server_name:
            action = policy["server_actions"].get(server_name)
        if not action:
            action = policy["default_action"]
            reason = "default_policy"
        elif resolved_tool_key in policy["tool_actions"]:
            reason = "tool_policy"
        else:
            reason = "server_policy"

        if policy["deny_risky_write_paths"] and self.tool_policy_requires_path_review(tool_name, arguments):
            if action == "allow":
                action = "confirm"
                reason = "risky_write_path"

        if action == "confirm" and policy_confirmed:
            return None

        if action == "allow":
            return None

        suggestion = (
            "Review the tool arguments and retry after explicit confirmation."
            if action == "confirm"
            else "Choose a safer tool or update the runtime tool policy before retrying."
        )
        return {
            "reason": f"Runtime tool policy marked {resolved_tool_key} as {action}.",
            "suggestion": suggestion,
            "block_source": "policy",
            "policy_action": action,
            "policy_reason": reason,
            "tool_key": resolved_tool_key,
        }

    def build_tool_run_trace(
        self,
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
        policy_state = self.get_tool_policy_state()
        resolved_tool_key = f"{server_name}.{tool_name}" if server_name else tool_name
        return {
            "kind": "tool_call",
            "request_id": request_id,
            "server_name": server_name,
            "tool_name": tool_name,
            "tool_key": resolved_tool_key,
            "argument_keys": sorted((arguments or {}).keys()),
            "tool_policy": {
                "enabled": policy_state["enabled"],
                "default_action": policy_state["default_action"],
                "blocked": bool(policy_block),
                "policy_action": (policy_block or {}).get("policy_action", "allow"),
                "policy_reason": (policy_block or {}).get("policy_reason", ""),
                "reason": (policy_block or {}).get("reason", ""),
            },
            "routing": (memory_plan or {}).get("routing", {}),
            "execution_policy": (memory_plan or {}).get("execution_policy", {}),
            "blocked": blocked,
            "success": success,
            "latency_ms": latency_ms,
            "timestamp": datetime.now().isoformat(),
        }

    async def probe_openrouter_connectivity(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> dict[str, Any]:
        resolved_api_key = (api_key or self.openrouter_api_key or "").strip()
        resolved_base_url = self.normalize_openrouter_base_url(base_url or self.openrouter_base_url)
        endpoint = f"{resolved_base_url}/models"

        if not resolved_api_key:
            return {
                "ok": False,
                "provider": "openrouter",
                "reachable": False,
                "authenticated": False,
                "endpoint": endpoint,
                "status_code": None,
                "message": "OpenRouter API key is missing.",
                "reason": "missing_api_key",
            }

        try:
            response = await self.get_shared_http_client().get(
                endpoint,
                headers={
                    "Authorization": f"Bearer {resolved_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "provider": "openrouter",
                "reachable": False,
                "authenticated": False,
                "endpoint": endpoint,
                "status_code": None,
                "message": "OpenRouter connectivity check timed out.",
                "reason": "timeout",
            }
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "provider": "openrouter",
                "reachable": False,
                "authenticated": False,
                "endpoint": endpoint,
                "status_code": None,
                "message": f"OpenRouter connectivity check failed: {exc}",
                "reason": "request_error",
            }

        try:
            payload = response.json()
        except Exception:
            payload = {}

        if response.status_code == 200:
            models = payload.get("data", []) if isinstance(payload, dict) else []
            model_count = len(models) if isinstance(models, list) else 0
            return {
                "ok": True,
                "provider": "openrouter",
                "reachable": True,
                "authenticated": True,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "model_count": model_count,
                "message": f"OpenRouter reachable. Retrieved {model_count} models.",
            }

        error_text = response.text[:300]
        return {
            "ok": False,
            "provider": "openrouter",
            "reachable": True,
            "authenticated": response.status_code not in (401, 403),
            "endpoint": endpoint,
            "status_code": response.status_code,
            "message": self.friendly_provider_error("openrouter", response.status_code, error_text),
            "error_text": error_text,
        }

    async def probe_siliconflow_connectivity(
        self,
        *,
        api_key: Optional[str],
        base_url: Optional[str] = None,
    ) -> dict[str, Any]:
        resolved_api_key = (api_key or self.siliconflow_api_key or "").strip()
        endpoint = f"{self.normalize_siliconflow_base_url(base_url or self.siliconflow_base_url)}/models"

        if not resolved_api_key:
            return {
                "ok": False,
                "provider": "siliconflow",
                "reachable": False,
                "authenticated": False,
                "endpoint": endpoint,
                "status_code": None,
                "message": "SiliconFlow API key is missing.",
                "reason": "missing_api_key",
            }

        try:
            response = await self.get_shared_http_client().get(
                endpoint,
                headers={
                    "Authorization": f"Bearer {resolved_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "provider": "siliconflow",
                "reachable": False,
                "authenticated": False,
                "endpoint": endpoint,
                "status_code": None,
                "message": "SiliconFlow connectivity check timed out.",
                "reason": "timeout",
            }
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "provider": "siliconflow",
                "reachable": False,
                "authenticated": False,
                "endpoint": endpoint,
                "status_code": None,
                "message": f"SiliconFlow connectivity check failed: {exc}",
                "reason": "request_error",
            }

        try:
            payload = response.json()
        except Exception:
            payload = {}

        if response.status_code == 200:
            models = payload.get("data", []) if isinstance(payload, dict) else []
            model_count = len(models) if isinstance(models, list) else 0
            return {
                "ok": True,
                "provider": "siliconflow",
                "reachable": True,
                "authenticated": True,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "model_count": model_count,
                "message": f"SiliconFlow reachable. Retrieved {model_count} models.",
            }

        error_text = response.text[:300]
        return {
            "ok": False,
            "provider": "siliconflow",
            "reachable": True,
            "authenticated": response.status_code not in (401, 403),
            "endpoint": endpoint,
            "status_code": response.status_code,
            "message": f"siliconflow API error: {response.status_code} - {error_text}",
            "error_text": error_text,
        }
