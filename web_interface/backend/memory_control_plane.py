# -*- coding: utf-8 -*-

"""
Memory Control Plane.

This module coordinates multiple memory subsystems:
- episodic/context memory
- procedural tool memory
- safety/failure memory

Research intent:
- recipe != skill
- routing, retention, forgetting, and attribution remain explicit
- runtime decisions are logged as auditable events
- learning signals are persisted for reproducible evaluation
"""

from __future__ import annotations

import json
import logging
import math
import hashlib
import copy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from probabilistic_params import load_required_params

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
MEMORY_DIR = ARTIFACTS_DIR / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

MEMORY_PLANE_TRACE_PATH = MEMORY_DIR / "memory_plane_traces.jsonl"
MEMORY_POLICY_LEDGER_PATH = MEMORY_DIR / "memory_policy_ledger.json"
MEMORY_PLANE_SCHEMA_VERSION = "memory_plane_governance_v1"

_MEMORY_PLANE_PARAM_KEYS = [
    "ROUTING_TOP_K_TOOLS",
    "ROUTING_MIN_TOOL_SCORE",
    "ROUTING_MIN_QUERY_LENGTH",
    "ROUTING_LEXICAL_WEIGHT",
    "ROUTING_NGRAM_WEIGHT",
    "ROUTING_RECIPE_WEIGHT",
    "ROUTING_GUARD_PENALTY_WEIGHT",
    "ROUTING_EXACT_MATCH_BOOST",
    "ROUTING_GLOBAL_RELIABILITY_WEIGHT",
    "ROUTING_INTENT_RELIABILITY_WEIGHT",
    "ROUTING_PROTOTYPE_WEIGHT",
    "ROUTING_TRANSITION_WEIGHT",
    "ROUTING_LEARNED_SCORE_WEIGHT",
    "ROUTING_COMPATIBILITY_SCORE_WEIGHT",
    "ROUTING_ONLINE_LEARNING_RATE",
    "ROUTING_ONLINE_L2",
    "ROUTING_NGRAM_SIZE",
    "ROUTING_INTENT_MAX_TOKENS",
    "ROUTING_SIGMOID_CLIP",
    "ROUTING_PROTOTYPE_LEARNING_RATE",
    "ROUTING_PROTOTYPE_EPSILON",
    "ROUTING_MAX_SHADOW_REPLAY_ITEMS",
    "ROUTING_EPISODIC_DECAY",
    "ROUTING_MAX_EPISODIC_EXAMPLES",
    "ROUTING_EPISODIC_SUCCESS_WEIGHT",
    "ROUTING_EPISODIC_FAILURE_WEIGHT",
    "ROUTING_TOOL_PROTOTYPE_WEIGHT",
    "ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT",
    "ROUTING_RELIABILITY_BANDIT_WEIGHT",
    "ROUTING_PAIRWISE_PREFERENCE_WEIGHT",
    "ROUTING_LISTWISE_CONTEXT_WEIGHT",
    "ROUTING_RERANK_TOP_CANDIDATES",
    "ROUTING_LISTWISE_TEMPERATURE",
    "ROUTING_PAIRWISE_PRIOR_ALPHA",
    "ROUTING_PAIRWISE_PRIOR_BETA",
    "RETENTION_MAX_CONTEXT_SUMMARIES",
    "RETENTION_MAX_FACTS",
    "RETENTION_MAX_TRACE_ITEMS",
    "FORGETTING_DECAY_DAYS",
    "FORGETTING_MIN_KEEP_DAYS",
    "FORGETTING_SUMMARY_MIN_FRESHNESS",
    "FORGETTING_FACT_MIN_SCORE",
    "FORGETTING_RECIPE_MIN_QUALITY",
    "FORGETTING_RECIPE_RETIRE_QUALITY",
    "FORGETTING_GUARD_MIN_FAILURE_PROB",
    "FORGETTING_GUARD_RETIRE_FAILURE_PROB",
    "FORGETTING_RECIPE_QUALITY_WEIGHT",
    "FORGETTING_RECIPE_VERIFICATION_WEIGHT",
    "FORGETTING_RECIPE_FRESHNESS_WEIGHT",
    "FORGETTING_RECIPE_CONTAMINATION_PENALTY",
    "FORGETTING_GUARD_FAILURE_WEIGHT",
    "FORGETTING_GUARD_FRESHNESS_WEIGHT",
    "FORGETTING_GUARD_AVOIDED_WEIGHT",
    "FORGETTING_GUARD_BLOCK_WEIGHT",
    "FORGETTING_GUARD_AVOIDED_CAP",
    "FORGETTING_GUARD_BLOCK_CAP",
    "FORGETTING_ROLLBACK_MAX_ITEMS",
    "CAUSAL_SIGNIFICANT_DELTA",
    "MEMORY_DECISION_ID_LEN",
    "ATTRIBUTION_MAX_ITEMS",
]

ROUTING_FEATURE_KEYS = [
    "bias",
    "lexical_score",
    "ngram_score",
    "recipe_support",
    "guard_penalty",
    "exact_match_boost",
    "global_reliability",
    "intent_reliability",
    "prototype_similarity",
    "tool_prototype_similarity",
    "intent_tool_prototype_similarity",
    "transition_prior",
    "episodic_success_support",
    "episodic_failure_penalty",
    "reliability_bandit_score",
    "pairwise_preference_support",
    "listwise_context_support",
]

ROUTING_WEIGHT_KEY_MAP = {
    "lexical_score": "ROUTING_LEXICAL_WEIGHT",
    "ngram_score": "ROUTING_NGRAM_WEIGHT",
    "recipe_support": "ROUTING_RECIPE_WEIGHT",
    "guard_penalty": "ROUTING_GUARD_PENALTY_WEIGHT",
    "exact_match_boost": "ROUTING_EXACT_MATCH_BOOST",
    "global_reliability": "ROUTING_GLOBAL_RELIABILITY_WEIGHT",
    "intent_reliability": "ROUTING_INTENT_RELIABILITY_WEIGHT",
    "prototype_similarity": "ROUTING_PROTOTYPE_WEIGHT",
    "tool_prototype_similarity": "ROUTING_TOOL_PROTOTYPE_WEIGHT",
    "intent_tool_prototype_similarity": "ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT",
    "transition_prior": "ROUTING_TRANSITION_WEIGHT",
    "episodic_success_support": "ROUTING_EPISODIC_SUCCESS_WEIGHT",
    "episodic_failure_penalty": "ROUTING_EPISODIC_FAILURE_WEIGHT",
    "reliability_bandit_score": "ROUTING_RELIABILITY_BANDIT_WEIGHT",
    "pairwise_preference_support": "ROUTING_PAIRWISE_PREFERENCE_WEIGHT",
    "listwise_context_support": "ROUTING_LISTWISE_CONTEXT_WEIGHT",
}

ROUTING_FEATURE_GROUPS = {
    "lexical": ["lexical_score", "ngram_score", "exact_match_boost"],
    "recipe": ["recipe_support"],
    "guard": ["guard_penalty"],
    "reliability": ["global_reliability", "intent_reliability"],
    "prototype": ["prototype_similarity", "tool_prototype_similarity", "intent_tool_prototype_similarity"],
    "transition": ["transition_prior"],
    "episodic": ["episodic_success_support", "episodic_failure_penalty"],
    "bandit": ["reliability_bandit_score"],
    "pairwise": ["pairwise_preference_support"],
    "listwise": ["listwise_context_support"],
}


def _apply_memory_plane_params(params: dict[str, Any]) -> None:
    global ROUTING_TOP_K_TOOLS
    global ROUTING_MIN_TOOL_SCORE
    global ROUTING_MIN_QUERY_LENGTH
    global ROUTING_LEXICAL_WEIGHT
    global ROUTING_NGRAM_WEIGHT
    global ROUTING_RECIPE_WEIGHT
    global ROUTING_GUARD_PENALTY_WEIGHT
    global ROUTING_EXACT_MATCH_BOOST
    global ROUTING_GLOBAL_RELIABILITY_WEIGHT
    global ROUTING_INTENT_RELIABILITY_WEIGHT
    global ROUTING_PROTOTYPE_WEIGHT
    global ROUTING_TRANSITION_WEIGHT
    global ROUTING_LEARNED_SCORE_WEIGHT
    global ROUTING_COMPATIBILITY_SCORE_WEIGHT
    global ROUTING_ONLINE_LEARNING_RATE
    global ROUTING_ONLINE_L2
    global ROUTING_NGRAM_SIZE
    global ROUTING_INTENT_MAX_TOKENS
    global ROUTING_SIGMOID_CLIP
    global ROUTING_PROTOTYPE_LEARNING_RATE
    global ROUTING_PROTOTYPE_EPSILON
    global ROUTING_MAX_SHADOW_REPLAY_ITEMS
    global ROUTING_EPISODIC_DECAY
    global ROUTING_MAX_EPISODIC_EXAMPLES
    global ROUTING_EPISODIC_SUCCESS_WEIGHT
    global ROUTING_EPISODIC_FAILURE_WEIGHT
    global ROUTING_TOOL_PROTOTYPE_WEIGHT
    global ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT
    global ROUTING_RELIABILITY_BANDIT_WEIGHT
    global ROUTING_PAIRWISE_PREFERENCE_WEIGHT
    global ROUTING_LISTWISE_CONTEXT_WEIGHT
    global ROUTING_RERANK_TOP_CANDIDATES
    global ROUTING_LISTWISE_TEMPERATURE
    global ROUTING_PAIRWISE_PRIOR_ALPHA
    global ROUTING_PAIRWISE_PRIOR_BETA
    global RETENTION_MAX_CONTEXT_SUMMARIES
    global RETENTION_MAX_FACTS
    global RETENTION_MAX_TRACE_ITEMS
    global FORGETTING_DECAY_DAYS
    global FORGETTING_MIN_KEEP_DAYS
    global FORGETTING_SUMMARY_MIN_FRESHNESS
    global FORGETTING_FACT_MIN_SCORE
    global FORGETTING_RECIPE_MIN_QUALITY
    global FORGETTING_RECIPE_RETIRE_QUALITY
    global FORGETTING_GUARD_MIN_FAILURE_PROB
    global FORGETTING_GUARD_RETIRE_FAILURE_PROB
    global FORGETTING_RECIPE_QUALITY_WEIGHT
    global FORGETTING_RECIPE_VERIFICATION_WEIGHT
    global FORGETTING_RECIPE_FRESHNESS_WEIGHT
    global FORGETTING_RECIPE_CONTAMINATION_PENALTY
    global FORGETTING_GUARD_FAILURE_WEIGHT
    global FORGETTING_GUARD_FRESHNESS_WEIGHT
    global FORGETTING_GUARD_AVOIDED_WEIGHT
    global FORGETTING_GUARD_BLOCK_WEIGHT
    global FORGETTING_GUARD_AVOIDED_CAP
    global FORGETTING_GUARD_BLOCK_CAP
    global FORGETTING_ROLLBACK_MAX_ITEMS
    global CAUSAL_SIGNIFICANT_DELTA
    global MEMORY_DECISION_ID_LEN
    global ATTRIBUTION_MAX_ITEMS

    ROUTING_TOP_K_TOOLS = int(params["ROUTING_TOP_K_TOOLS"])
    ROUTING_MIN_TOOL_SCORE = float(params["ROUTING_MIN_TOOL_SCORE"])
    ROUTING_MIN_QUERY_LENGTH = int(params["ROUTING_MIN_QUERY_LENGTH"])
    ROUTING_LEXICAL_WEIGHT = float(params["ROUTING_LEXICAL_WEIGHT"])
    ROUTING_NGRAM_WEIGHT = float(params["ROUTING_NGRAM_WEIGHT"])
    ROUTING_RECIPE_WEIGHT = float(params["ROUTING_RECIPE_WEIGHT"])
    ROUTING_GUARD_PENALTY_WEIGHT = float(params["ROUTING_GUARD_PENALTY_WEIGHT"])
    ROUTING_EXACT_MATCH_BOOST = float(params["ROUTING_EXACT_MATCH_BOOST"])
    ROUTING_GLOBAL_RELIABILITY_WEIGHT = float(params["ROUTING_GLOBAL_RELIABILITY_WEIGHT"])
    ROUTING_INTENT_RELIABILITY_WEIGHT = float(params["ROUTING_INTENT_RELIABILITY_WEIGHT"])
    ROUTING_PROTOTYPE_WEIGHT = float(params["ROUTING_PROTOTYPE_WEIGHT"])
    ROUTING_TRANSITION_WEIGHT = float(params["ROUTING_TRANSITION_WEIGHT"])
    ROUTING_LEARNED_SCORE_WEIGHT = float(params["ROUTING_LEARNED_SCORE_WEIGHT"])
    ROUTING_COMPATIBILITY_SCORE_WEIGHT = float(params["ROUTING_COMPATIBILITY_SCORE_WEIGHT"])
    ROUTING_ONLINE_LEARNING_RATE = float(params["ROUTING_ONLINE_LEARNING_RATE"])
    ROUTING_ONLINE_L2 = float(params["ROUTING_ONLINE_L2"])
    ROUTING_NGRAM_SIZE = int(params["ROUTING_NGRAM_SIZE"])
    ROUTING_INTENT_MAX_TOKENS = int(params["ROUTING_INTENT_MAX_TOKENS"])
    ROUTING_SIGMOID_CLIP = float(params["ROUTING_SIGMOID_CLIP"])
    ROUTING_PROTOTYPE_LEARNING_RATE = float(params["ROUTING_PROTOTYPE_LEARNING_RATE"])
    ROUTING_PROTOTYPE_EPSILON = float(params["ROUTING_PROTOTYPE_EPSILON"])
    ROUTING_MAX_SHADOW_REPLAY_ITEMS = int(params["ROUTING_MAX_SHADOW_REPLAY_ITEMS"])
    ROUTING_EPISODIC_DECAY = float(params["ROUTING_EPISODIC_DECAY"])
    ROUTING_MAX_EPISODIC_EXAMPLES = int(params["ROUTING_MAX_EPISODIC_EXAMPLES"])
    ROUTING_EPISODIC_SUCCESS_WEIGHT = float(params["ROUTING_EPISODIC_SUCCESS_WEIGHT"])
    ROUTING_EPISODIC_FAILURE_WEIGHT = float(params["ROUTING_EPISODIC_FAILURE_WEIGHT"])
    ROUTING_TOOL_PROTOTYPE_WEIGHT = float(params["ROUTING_TOOL_PROTOTYPE_WEIGHT"])
    ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT = float(params["ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT"])
    ROUTING_RELIABILITY_BANDIT_WEIGHT = float(params["ROUTING_RELIABILITY_BANDIT_WEIGHT"])
    ROUTING_PAIRWISE_PREFERENCE_WEIGHT = float(params["ROUTING_PAIRWISE_PREFERENCE_WEIGHT"])
    ROUTING_LISTWISE_CONTEXT_WEIGHT = float(params["ROUTING_LISTWISE_CONTEXT_WEIGHT"])
    ROUTING_RERANK_TOP_CANDIDATES = int(params["ROUTING_RERANK_TOP_CANDIDATES"])
    ROUTING_LISTWISE_TEMPERATURE = float(params["ROUTING_LISTWISE_TEMPERATURE"])
    ROUTING_PAIRWISE_PRIOR_ALPHA = float(params["ROUTING_PAIRWISE_PRIOR_ALPHA"])
    ROUTING_PAIRWISE_PRIOR_BETA = float(params["ROUTING_PAIRWISE_PRIOR_BETA"])
    RETENTION_MAX_CONTEXT_SUMMARIES = int(params["RETENTION_MAX_CONTEXT_SUMMARIES"])
    RETENTION_MAX_FACTS = int(params["RETENTION_MAX_FACTS"])
    RETENTION_MAX_TRACE_ITEMS = int(params["RETENTION_MAX_TRACE_ITEMS"])
    FORGETTING_DECAY_DAYS = float(params["FORGETTING_DECAY_DAYS"])
    FORGETTING_MIN_KEEP_DAYS = float(params["FORGETTING_MIN_KEEP_DAYS"])
    FORGETTING_SUMMARY_MIN_FRESHNESS = float(params["FORGETTING_SUMMARY_MIN_FRESHNESS"])
    FORGETTING_FACT_MIN_SCORE = float(params["FORGETTING_FACT_MIN_SCORE"])
    FORGETTING_RECIPE_MIN_QUALITY = float(params["FORGETTING_RECIPE_MIN_QUALITY"])
    FORGETTING_RECIPE_RETIRE_QUALITY = float(params["FORGETTING_RECIPE_RETIRE_QUALITY"])
    FORGETTING_GUARD_MIN_FAILURE_PROB = float(params["FORGETTING_GUARD_MIN_FAILURE_PROB"])
    FORGETTING_GUARD_RETIRE_FAILURE_PROB = float(params["FORGETTING_GUARD_RETIRE_FAILURE_PROB"])
    FORGETTING_RECIPE_QUALITY_WEIGHT = float(params["FORGETTING_RECIPE_QUALITY_WEIGHT"])
    FORGETTING_RECIPE_VERIFICATION_WEIGHT = float(params["FORGETTING_RECIPE_VERIFICATION_WEIGHT"])
    FORGETTING_RECIPE_FRESHNESS_WEIGHT = float(params["FORGETTING_RECIPE_FRESHNESS_WEIGHT"])
    FORGETTING_RECIPE_CONTAMINATION_PENALTY = float(params["FORGETTING_RECIPE_CONTAMINATION_PENALTY"])
    FORGETTING_GUARD_FAILURE_WEIGHT = float(params["FORGETTING_GUARD_FAILURE_WEIGHT"])
    FORGETTING_GUARD_FRESHNESS_WEIGHT = float(params["FORGETTING_GUARD_FRESHNESS_WEIGHT"])
    FORGETTING_GUARD_AVOIDED_WEIGHT = float(params["FORGETTING_GUARD_AVOIDED_WEIGHT"])
    FORGETTING_GUARD_BLOCK_WEIGHT = float(params["FORGETTING_GUARD_BLOCK_WEIGHT"])
    FORGETTING_GUARD_AVOIDED_CAP = float(params["FORGETTING_GUARD_AVOIDED_CAP"])
    FORGETTING_GUARD_BLOCK_CAP = float(params["FORGETTING_GUARD_BLOCK_CAP"])
    FORGETTING_ROLLBACK_MAX_ITEMS = int(params["FORGETTING_ROLLBACK_MAX_ITEMS"])
    CAUSAL_SIGNIFICANT_DELTA = float(params["CAUSAL_SIGNIFICANT_DELTA"])
    MEMORY_DECISION_ID_LEN = int(params["MEMORY_DECISION_ID_LEN"])
    ATTRIBUTION_MAX_ITEMS = int(params["ATTRIBUTION_MAX_ITEMS"])


_apply_memory_plane_params(load_required_params("memory_control_plane", _MEMORY_PLANE_PARAM_KEYS))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(timestamp: Optional[str]) -> Optional[float]:
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - dt).total_seconds() / 86400.0, 0.0)
    except Exception:
        return None


def _exp_freshness(days: Optional[float], decay_days: float) -> float:
    if days is None or decay_days <= 0:
        return 1.0
    return math.exp(-days / decay_days)


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    current: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            current.append(ch)
        elif current:
            tokens.add("".join(current))
            current = []
    if current:
        tokens.add("".join(current))
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ngram_vector(text: str, n: Optional[int] = None) -> dict[str, float]:
    gram_size = ROUTING_NGRAM_SIZE if n is None else n
    normalized = (text or "").lower().strip()
    if len(normalized) < gram_size:
        return {}
    freq: dict[str, float] = {}
    for idx in range(len(normalized) - gram_size + 1):
        gram = normalized[idx : idx + gram_size]
        freq[gram] = freq.get(gram, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in freq.values()))
    if norm <= 1e-12:
        return {}
    return {key: value / norm for key, value in freq.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return sum(value * longer.get(key, 0.0) for key, value in shorter.items())


def _vector_norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _blend_normalized_vectors(
    current: dict[str, float],
    observed: dict[str, float],
    learning_rate: float,
) -> dict[str, float]:
    if not current:
        current = {}
    updated_keys = set(current) | set(observed)
    blended: dict[str, float] = {}
    for key in updated_keys:
        blended[key] = (1.0 - learning_rate) * current.get(key, 0.0) + learning_rate * observed.get(key, 0.0)
    norm = _vector_norm(blended)
    if norm <= ROUTING_PROTOTYPE_EPSILON:
        return {}
    return {key: value / norm for key, value in blended.items() if abs(value / norm) > ROUTING_PROTOTYPE_EPSILON}


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(value, upper))


def _sigmoid(value: float) -> float:
    value = max(min(value, ROUTING_SIGMOID_CLIP), -ROUTING_SIGMOID_CLIP)
    return 1.0 / (1.0 + math.exp(-value))


def _intent_signature(text: str) -> str:
    tokens = sorted(_tokenize(text))
    if not tokens:
        return "empty_intent"
    return "|".join(tokens[:ROUTING_INTENT_MAX_TOKENS])


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _decision_id(kind: str, item_id: str, action: str, reason: str) -> str:
    raw = f"{kind}|{item_id}|{action}|{reason}|{_utc_now()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:MEMORY_DECISION_ID_LEN]


def _normalize_distribution(probabilities: dict[str, float]) -> dict[str, float]:
    total = sum(max(_safe_float(value, 0.0), 0.0) for value in probabilities.values())
    if total <= 1e-12:
        return {}
    return {
        str(key): max(_safe_float(value, 0.0), 0.0) / total
        for key, value in probabilities.items()
        if max(_safe_float(value, 0.0), 0.0) > 0.0
    }


def _softmax(scores: list[float], temperature: float) -> list[float]:
    if not scores:
        return []
    safe_temperature = max(float(temperature), 1e-6)
    shifted = [score / safe_temperature for score in scores]
    max_score = max(shifted)
    exps = [math.exp(score - max_score) for score in shifted]
    total = sum(exps)
    if total <= 1e-12:
        uniform = 1.0 / len(scores)
        return [uniform for _ in scores]
    return [value / total for value in exps]


def _ordered_prefix_match_length(chain: list[str], observed_prefix: list[str]) -> int:
    if not chain or not observed_prefix:
        return 0
    normalized_chain = [str(item).strip() for item in chain if str(item).strip()]
    normalized_observed = [str(item).strip() for item in observed_prefix if str(item).strip()]
    if not normalized_chain or not normalized_observed:
        return 0
    max_len = min(len(normalized_chain), len(normalized_observed))
    for length in range(max_len, 0, -1):
        if normalized_observed[-length:] == normalized_chain[:length]:
            return length
    return 0


def _normalize_feature_mask(feature_mask: Optional[dict[str, bool]]) -> dict[str, bool]:
    if not feature_mask:
        return {}
    normalized: dict[str, bool] = {}
    valid_keys = set(ROUTING_FEATURE_GROUPS) | set(ROUTING_FEATURE_KEYS)
    for raw_key, raw_enabled in feature_mask.items():
        key = str(raw_key).strip()
        if key not in valid_keys:
            raise ValueError(f"Unknown routing feature mask key: {key}")
        normalized[key] = bool(raw_enabled)
    return normalized


def _feature_enabled(feature_name: str, feature_mask: Optional[dict[str, bool]]) -> bool:
    if not feature_mask:
        return True
    if feature_name in feature_mask:
        return bool(feature_mask[feature_name])
    for group_name, feature_names in ROUTING_FEATURE_GROUPS.items():
        if feature_name in feature_names and group_name in feature_mask:
            return bool(feature_mask[group_name])
    return True


def _masked_feature_value(feature_name: str, value: float, feature_mask: Optional[dict[str, bool]]) -> float:
    return value if _feature_enabled(feature_name, feature_mask) else 0.0


@dataclass
class MemoryAttributionItem:
    source: str
    item_id: str
    label: str
    score: float
    freshness: float
    rationale: str


class MemoryControlPlane:
    def __init__(self) -> None:
        self.last_snapshot: dict[str, Any] = self._initial_snapshot()
        self.routing_stats = self._load_routing_stats()
        self._ensure_ledger_shape()

    @staticmethod
    def _initial_snapshot() -> dict[str, Any]:
        return {
            "timestamp": _utc_now(),
            "routing": {},
            "retention": {},
            "forgetting": {},
            "attribution": [],
        }

    def reset_runtime_state(self, *, clear_traces: bool = False) -> dict[str, Any]:
        try:
            if MEMORY_POLICY_LEDGER_PATH.exists():
                MEMORY_POLICY_LEDGER_PATH.unlink()
        except Exception as exc:
            logger.warning("Failed to clear memory policy ledger: %s", exc)
        if clear_traces:
            try:
                if MEMORY_PLANE_TRACE_PATH.exists():
                    MEMORY_PLANE_TRACE_PATH.unlink()
            except Exception as exc:
                logger.warning("Failed to clear memory plane traces: %s", exc)
        self.last_snapshot = self._initial_snapshot()
        self.routing_stats = {}
        self._ensure_ledger_shape()
        self._save_routing_stats()
        return {
            "ok": True,
            "router_reset": True,
            "trace_reset": bool(clear_traces),
            "ledger_path": str(MEMORY_POLICY_LEDGER_PATH),
            "trace_path": str(MEMORY_PLANE_TRACE_PATH),
        }

    def _infer_plane_kind(self, phase: str) -> str:
        normalized_phase = str(phase or "").strip()
        if normalized_phase == "chat_preparation":
            return "chat"
        if normalized_phase == "tool_precheck":
            return "tool"
        if normalized_phase.startswith("policy"):
            return "policy"
        return "runtime"

    def _base_event(
        self,
        *,
        event_type: str,
        event_category: str,
        timestamp: str = "",
        phase: str = "",
        client_id: str = "",
    ) -> dict[str, Any]:
        return {
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "event_type": str(event_type or ""),
            "event_category": str(event_category or ""),
            "timestamp": str(timestamp or ""),
            "phase": str(phase or ""),
            "client_id": str(client_id or ""),
        }

    def _normalize_training_event(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = self._base_event(
            event_type="training",
            event_category="router_update",
            timestamp=str(event.get("timestamp", "")),
            phase=str(event.get("phase", "tool_outcome_learning")),
            client_id=str(event.get("client_id", "")),
        )
        normalized.update(
            {
                "tool_name": str(event.get("tool_name", "")),
                "intent_signature": str(event.get("intent_signature", "")),
                "target": round(_safe_float(event.get("target", 0.0)), 4),
                "blocked": bool(event.get("blocked", False)),
                "success": bool(event.get("success", False)),
                "feature_vector": dict(event.get("feature_vector", {}) or {}),
                "updated_weights": dict(event.get("updated_weights", {}) or {}),
            }
        )
        return normalized

    def _normalize_governance_event(self, event: dict[str, Any]) -> dict[str, Any]:
        kind = str(event.get("kind", event.get("memory_object_type", "")))
        item_id = str(event.get("item_id", ""))
        action = str(event.get("action", "retain"))
        reason = str(event.get("reason", "policy"))
        normalized = self._base_event(
            event_type="governance",
            event_category="forgetting_policy",
            timestamp=str(event.get("timestamp", "")),
            phase=str(event.get("phase", "governance_execution")),
            client_id=str(event.get("client_id", "")),
        )
        normalized.update(
            {
                "decision_id": str(event.get("decision_id") or _decision_id(kind or "unknown", item_id, action, reason)),
                "kind": kind,
                "memory_object_type": kind,
                "item_id": item_id,
                "action": action,
                "reason": reason,
                "applied": bool(event.get("applied", False)),
                "policy": {
                    "family": "forgetting",
                    "version": str(event.get("policy_version", "memory_governance_v2")),
                    "executed": bool(event.get("applied", False)),
                },
                "decision": {
                    "kind": kind,
                    "item_id": item_id,
                    "action": action,
                    "reason": reason,
                },
                "evidence": dict(event.get("evidence", {}) or {}),
            }
        )
        return normalized

    def _normalize_causal_event(self, event: dict[str, Any]) -> dict[str, Any]:
        selected_tool = str(event.get("selected_tool", ""))
        normalized = self._base_event(
            event_type="causal",
            event_category="tool_outcome_attribution",
            timestamp=str(event.get("timestamp", "")),
            phase=str(event.get("phase", "tool_outcome")),
            client_id=str(event.get("client_id", "")),
        )
        normalized.update(
            {
                "selected_tool": selected_tool,
                "success": bool(event.get("success", False)),
                "blocked": bool(event.get("blocked", False)),
                "intent_signature": str(event.get("intent_signature", "")),
                "baseline_probability": round(_safe_float(event.get("baseline_probability", 0.0)), 4),
                "decision": {
                    "selected_tool": selected_tool,
                    "success": bool(event.get("success", False)),
                    "blocked": bool(event.get("blocked", False)),
                    "intent_signature": str(event.get("intent_signature", "")),
                },
                "counterfactuals": dict(event.get("ablation", {}) or {}),
                "ablation": dict(event.get("ablation", {}) or {}),
            }
        )
        return normalized

    def _normalize_shadow_replay_event(self, event: dict[str, Any]) -> dict[str, Any]:
        shadow_replay = dict(event.get("shadow_replay", {}) or {})
        normalized = self._base_event(
            event_type="shadow_replay",
            event_category="counterfactual_routing",
            timestamp=str(event.get("timestamp", "")),
            phase=str(event.get("phase", "tool_outcome")),
            client_id=str(event.get("client_id", "")),
        )
        normalized.update(
            {
                "selected_tool": str(event.get("selected_tool", shadow_replay.get("selected_tool", ""))),
                "shadow_replay": shadow_replay,
            }
        )
        return normalized

    def _normalize_rollback_event(self, event: dict[str, Any]) -> dict[str, Any]:
        recipe_result = event.get("recipe_result", {})
        guard_result = event.get("guard_result", {})
        normalized = self._base_event(
            event_type="rollback",
            event_category="policy_recovery",
            timestamp=str(event.get("timestamp", "")),
            phase=str(event.get("phase", "manual_recovery")),
            client_id=str(event.get("client_id", "")),
        )
        normalized.update(
            {
                "reason": str(event.get("reason", "")),
                "recipe_result": recipe_result,
                "guard_result": guard_result,
                "recovered_objects": {
                    "recipes": recipe_result,
                    "guards": guard_result,
                },
            }
        )
        return normalized

    def _normalize_ledger_event(self, key: str, event: dict[str, Any]) -> dict[str, Any]:
        raw = dict(event or {})
        if key == "training_events":
            return self._normalize_training_event(raw)
        if key == "governance_events":
            return self._normalize_governance_event(raw)
        if key == "causal_events":
            return self._normalize_causal_event(raw)
        if key == "shadow_replay_events":
            return self._normalize_shadow_replay_event(raw)
        if key == "rollback_events":
            return self._normalize_rollback_event(raw)
        normalized = self._base_event(
            event_type=str(raw.get("event_type", "unknown")),
            event_category=str(raw.get("event_category", "unknown")),
            timestamp=str(raw.get("timestamp", "")),
            phase=str(raw.get("phase", "")),
            client_id=str(raw.get("client_id", "")),
        )
        normalized.update(raw)
        normalized.setdefault("schema_version", MEMORY_PLANE_SCHEMA_VERSION)
        return normalized

    def _build_ledger_summary(self) -> dict[str, Any]:
        self._ensure_ledger_shape()
        timestamps: list[str] = []
        for key in (
            "training_events",
            "governance_events",
            "causal_events",
            "shadow_replay_events",
            "rollback_events",
            "system_op_events",
        ):
            events = self.routing_stats.get(key, [])
            if isinstance(events, list) and events:
                timestamp = str((events[-1] or {}).get("timestamp", ""))
                if timestamp:
                    timestamps.append(timestamp)
        return {
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "training_event_count": len(self.routing_stats.get("training_events", [])),
            "governance_event_count": len(self.routing_stats.get("governance_events", [])),
            "causal_event_count": len(self.routing_stats.get("causal_events", [])),
            "shadow_replay_event_count": len(self.routing_stats.get("shadow_replay_events", [])),
            "rollback_event_count": len(self.routing_stats.get("rollback_events", [])),
            "system_op_event_count": len(self.routing_stats.get("system_op_events", [])),
            "router_updates": int(self.routing_stats.get("router", {}).get("updates", 0)),
            "last_event_timestamp": timestamps[-1] if timestamps else "",
        }

    def _build_governance_summary(self, governance: dict[str, Any]) -> dict[str, Any]:
        events = list((governance or {}).get("events", []))
        actions_by_kind: dict[str, int] = {}
        actions_by_name: dict[str, int] = {}
        applied_event_count = 0
        for event in events:
            kind = str(event.get("kind", "unknown"))
            action = str(event.get("action", "retain"))
            actions_by_kind[kind] = int(actions_by_kind.get(kind, 0)) + 1
            actions_by_name[action] = int(actions_by_name.get(action, 0)) + 1
            if bool(event.get("applied", False)):
                applied_event_count += 1
        return {
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "policy_executed": bool((governance or {}).get("policy_executed", False)),
            "policy_version": str((governance or {}).get("policy_version", "")),
            "event_count": len(events),
            "applied_event_count": applied_event_count,
            "actions_by_kind": actions_by_kind,
            "actions_by_name": actions_by_name,
            "suppressed_fact_count": len((governance or {}).get("suppressed_fact_hashes", [])),
        }

    def _finalize_plan_snapshot(self, plan: dict[str, Any]) -> dict[str, Any]:
        finalized = dict(plan)
        finalized.setdefault("schema_version", MEMORY_PLANE_SCHEMA_VERSION)
        phase = str(finalized.get("phase", "runtime"))
        forgetting = dict(finalized.get("forgetting", {}) or {})
        governance = dict(finalized.get("governance", {}) or {})
        memory_plane_meta = dict(finalized.get("memory_plane", {}) or {})
        memory_plane_meta.update(
            {
                "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
                "phase": phase,
                "plane_kind": self._infer_plane_kind(phase),
                "trace_artifact_path": str(MEMORY_PLANE_TRACE_PATH),
                "ledger_artifact_path": str(MEMORY_POLICY_LEDGER_PATH),
                "governance_mode": "executable_policy",
                "policy_version": str(forgetting.get("policy_version", "memory_governance_v2")),
                "governance_event_count": len(governance.get("events", [])),
                "attribution_count": len(finalized.get("attribution", [])),
            }
        )
        finalized["memory_plane"] = memory_plane_meta
        finalized["governance_summary"] = self._build_governance_summary(governance)
        finalized["ledger_summary"] = self._build_ledger_summary()
        finalized.setdefault("routing", {})
        finalized.setdefault("retention", {})
        finalized.setdefault("forgetting", {})
        finalized.setdefault("attribution", [])
        return finalized

    def _initial_router_weights(self) -> dict[str, float]:
        return {
            "bias": 0.0,
            "lexical_score": ROUTING_LEXICAL_WEIGHT,
            "ngram_score": ROUTING_NGRAM_WEIGHT,
            "recipe_support": ROUTING_RECIPE_WEIGHT,
            "guard_penalty": -ROUTING_GUARD_PENALTY_WEIGHT,
            "exact_match_boost": ROUTING_EXACT_MATCH_BOOST,
            "global_reliability": ROUTING_GLOBAL_RELIABILITY_WEIGHT,
            "intent_reliability": ROUTING_INTENT_RELIABILITY_WEIGHT,
            "prototype_similarity": ROUTING_PROTOTYPE_WEIGHT,
            "tool_prototype_similarity": ROUTING_TOOL_PROTOTYPE_WEIGHT,
            "intent_tool_prototype_similarity": ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT,
            "transition_prior": ROUTING_TRANSITION_WEIGHT,
            "episodic_success_support": ROUTING_EPISODIC_SUCCESS_WEIGHT,
            "episodic_failure_penalty": -ROUTING_EPISODIC_FAILURE_WEIGHT,
            "reliability_bandit_score": ROUTING_RELIABILITY_BANDIT_WEIGHT,
            "pairwise_preference_support": ROUTING_PAIRWISE_PREFERENCE_WEIGHT,
            "listwise_context_support": ROUTING_LISTWISE_CONTEXT_WEIGHT,
        }

    def _load_routing_stats(self) -> dict[str, Any]:
        if MEMORY_POLICY_LEDGER_PATH.exists():
            try:
                with open(MEMORY_POLICY_LEDGER_PATH, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                logger.warning("Failed to load memory policy ledger: %s", exc)
        return {}

    def _ensure_ledger_shape(self) -> None:
        for key in (
            "tool_success",
            "tool_failure",
            "tool_calls",
            "intent_success",
            "intent_failure",
            "intent_calls",
            "tool_transition_counts",
            "last_selected_tool_by_client",
            "recent_tool_history_by_client",
        ):
            if not isinstance(self.routing_stats.get(key), dict):
                self.routing_stats[key] = {}
        router = self.routing_stats.get("router")
        if not isinstance(router, dict):
            router = {}
            self.routing_stats["router"] = router
        if not isinstance(router.get("weights"), dict):
            router["weights"] = self._initial_router_weights()
        for key, value in self._initial_router_weights().items():
            router["weights"].setdefault(key, value)
        router.setdefault("updates", 0)
        router["learning_rate"] = ROUTING_ONLINE_LEARNING_RATE
        router["l2"] = ROUTING_ONLINE_L2
        router.setdefault("last_update", "")
        if not isinstance(self.routing_stats.get("training_events"), list):
            self.routing_stats["training_events"] = []
        if not isinstance(self.routing_stats.get("governance_events"), list):
            self.routing_stats["governance_events"] = []
        if not isinstance(self.routing_stats.get("causal_events"), list):
            self.routing_stats["causal_events"] = []
        if not isinstance(self.routing_stats.get("shadow_replay_events"), list):
            self.routing_stats["shadow_replay_events"] = []
        if not isinstance(self.routing_stats.get("rollback_events"), list):
            self.routing_stats["rollback_events"] = []
        if not isinstance(self.routing_stats.get("system_op_events"), list):
            self.routing_stats["system_op_events"] = []
        if not isinstance(router.get("intent_prototypes"), dict):
            router["intent_prototypes"] = {}
        if not isinstance(router.get("tool_prototypes"), dict):
            router["tool_prototypes"] = {}
        if not isinstance(router.get("intent_tool_prototypes"), dict):
            router["intent_tool_prototypes"] = {}
        if not isinstance(router.get("episodic_examples"), list):
            router["episodic_examples"] = []
        if not isinstance(router.get("bandit_alpha"), dict):
            router["bandit_alpha"] = {}
        if not isinstance(router.get("bandit_beta"), dict):
            router["bandit_beta"] = {}
        if not isinstance(router.get("pairwise_preferences"), dict):
            router["pairwise_preferences"] = {}
        for key in (
            "training_events",
            "governance_events",
            "causal_events",
            "shadow_replay_events",
            "rollback_events",
            "system_op_events",
        ):
            events = self.routing_stats.get(key, [])
            if isinstance(events, list):
                self.routing_stats[key] = [
                    self._normalize_ledger_event(key, event)
                    for event in events
                    if isinstance(event, dict)
                ]

    def _save_routing_stats(self) -> None:
        self._ensure_ledger_shape()
        try:
            with open(MEMORY_POLICY_LEDGER_PATH, "w", encoding="utf-8") as handle:
                json.dump(self.routing_stats, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to save memory policy ledger: %s", exc)

    def _append_bounded_ledger_event(self, key: str, event: dict[str, Any]) -> None:
        self._ensure_ledger_shape()
        events = self.routing_stats.get(key)
        if not isinstance(events, list):
            events = []
            self.routing_stats[key] = events
        events.append(self._normalize_ledger_event(key, event))
        if len(events) > RETENTION_MAX_TRACE_ITEMS:
            del events[:-RETENTION_MAX_TRACE_ITEMS]

    def reload_parameters(self) -> dict[str, Any]:
        _apply_memory_plane_params(load_required_params("memory_control_plane", _MEMORY_PLANE_PARAM_KEYS))
        self._ensure_ledger_shape()
        return {
            "ROUTING_TOP_K_TOOLS": ROUTING_TOP_K_TOOLS,
            "ROUTING_MIN_TOOL_SCORE": ROUTING_MIN_TOOL_SCORE,
            "ROUTING_MIN_QUERY_LENGTH": ROUTING_MIN_QUERY_LENGTH,
            "ROUTING_LEXICAL_WEIGHT": ROUTING_LEXICAL_WEIGHT,
            "ROUTING_NGRAM_WEIGHT": ROUTING_NGRAM_WEIGHT,
            "ROUTING_RECIPE_WEIGHT": ROUTING_RECIPE_WEIGHT,
            "ROUTING_GUARD_PENALTY_WEIGHT": ROUTING_GUARD_PENALTY_WEIGHT,
            "ROUTING_EXACT_MATCH_BOOST": ROUTING_EXACT_MATCH_BOOST,
            "ROUTING_GLOBAL_RELIABILITY_WEIGHT": ROUTING_GLOBAL_RELIABILITY_WEIGHT,
            "ROUTING_INTENT_RELIABILITY_WEIGHT": ROUTING_INTENT_RELIABILITY_WEIGHT,
            "ROUTING_PROTOTYPE_WEIGHT": ROUTING_PROTOTYPE_WEIGHT,
            "ROUTING_TRANSITION_WEIGHT": ROUTING_TRANSITION_WEIGHT,
            "ROUTING_LEARNED_SCORE_WEIGHT": ROUTING_LEARNED_SCORE_WEIGHT,
            "ROUTING_COMPATIBILITY_SCORE_WEIGHT": ROUTING_COMPATIBILITY_SCORE_WEIGHT,
            "ROUTING_ONLINE_LEARNING_RATE": ROUTING_ONLINE_LEARNING_RATE,
            "ROUTING_ONLINE_L2": ROUTING_ONLINE_L2,
            "ROUTING_NGRAM_SIZE": ROUTING_NGRAM_SIZE,
            "ROUTING_INTENT_MAX_TOKENS": ROUTING_INTENT_MAX_TOKENS,
            "ROUTING_SIGMOID_CLIP": ROUTING_SIGMOID_CLIP,
            "ROUTING_PROTOTYPE_LEARNING_RATE": ROUTING_PROTOTYPE_LEARNING_RATE,
            "ROUTING_PROTOTYPE_EPSILON": ROUTING_PROTOTYPE_EPSILON,
            "ROUTING_MAX_SHADOW_REPLAY_ITEMS": ROUTING_MAX_SHADOW_REPLAY_ITEMS,
            "ROUTING_EPISODIC_DECAY": ROUTING_EPISODIC_DECAY,
            "ROUTING_MAX_EPISODIC_EXAMPLES": ROUTING_MAX_EPISODIC_EXAMPLES,
            "ROUTING_EPISODIC_SUCCESS_WEIGHT": ROUTING_EPISODIC_SUCCESS_WEIGHT,
            "ROUTING_EPISODIC_FAILURE_WEIGHT": ROUTING_EPISODIC_FAILURE_WEIGHT,
            "ROUTING_TOOL_PROTOTYPE_WEIGHT": ROUTING_TOOL_PROTOTYPE_WEIGHT,
            "ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT": ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT,
            "ROUTING_RELIABILITY_BANDIT_WEIGHT": ROUTING_RELIABILITY_BANDIT_WEIGHT,
            "ROUTING_PAIRWISE_PREFERENCE_WEIGHT": ROUTING_PAIRWISE_PREFERENCE_WEIGHT,
            "ROUTING_LISTWISE_CONTEXT_WEIGHT": ROUTING_LISTWISE_CONTEXT_WEIGHT,
            "ROUTING_RERANK_TOP_CANDIDATES": ROUTING_RERANK_TOP_CANDIDATES,
            "ROUTING_LISTWISE_TEMPERATURE": ROUTING_LISTWISE_TEMPERATURE,
            "ROUTING_PAIRWISE_PRIOR_ALPHA": ROUTING_PAIRWISE_PRIOR_ALPHA,
            "ROUTING_PAIRWISE_PRIOR_BETA": ROUTING_PAIRWISE_PRIOR_BETA,
            "RETENTION_MAX_CONTEXT_SUMMARIES": RETENTION_MAX_CONTEXT_SUMMARIES,
            "RETENTION_MAX_FACTS": RETENTION_MAX_FACTS,
            "RETENTION_MAX_TRACE_ITEMS": RETENTION_MAX_TRACE_ITEMS,
            "FORGETTING_DECAY_DAYS": FORGETTING_DECAY_DAYS,
            "FORGETTING_MIN_KEEP_DAYS": FORGETTING_MIN_KEEP_DAYS,
            "FORGETTING_SUMMARY_MIN_FRESHNESS": FORGETTING_SUMMARY_MIN_FRESHNESS,
            "FORGETTING_FACT_MIN_SCORE": FORGETTING_FACT_MIN_SCORE,
            "FORGETTING_RECIPE_MIN_QUALITY": FORGETTING_RECIPE_MIN_QUALITY,
            "FORGETTING_RECIPE_RETIRE_QUALITY": FORGETTING_RECIPE_RETIRE_QUALITY,
            "FORGETTING_GUARD_MIN_FAILURE_PROB": FORGETTING_GUARD_MIN_FAILURE_PROB,
            "FORGETTING_GUARD_RETIRE_FAILURE_PROB": FORGETTING_GUARD_RETIRE_FAILURE_PROB,
            "FORGETTING_RECIPE_QUALITY_WEIGHT": FORGETTING_RECIPE_QUALITY_WEIGHT,
            "FORGETTING_RECIPE_VERIFICATION_WEIGHT": FORGETTING_RECIPE_VERIFICATION_WEIGHT,
            "FORGETTING_RECIPE_FRESHNESS_WEIGHT": FORGETTING_RECIPE_FRESHNESS_WEIGHT,
            "FORGETTING_RECIPE_CONTAMINATION_PENALTY": FORGETTING_RECIPE_CONTAMINATION_PENALTY,
            "FORGETTING_GUARD_FAILURE_WEIGHT": FORGETTING_GUARD_FAILURE_WEIGHT,
            "FORGETTING_GUARD_FRESHNESS_WEIGHT": FORGETTING_GUARD_FRESHNESS_WEIGHT,
            "FORGETTING_GUARD_AVOIDED_WEIGHT": FORGETTING_GUARD_AVOIDED_WEIGHT,
            "FORGETTING_GUARD_BLOCK_WEIGHT": FORGETTING_GUARD_BLOCK_WEIGHT,
            "FORGETTING_GUARD_AVOIDED_CAP": FORGETTING_GUARD_AVOIDED_CAP,
            "FORGETTING_GUARD_BLOCK_CAP": FORGETTING_GUARD_BLOCK_CAP,
            "CAUSAL_SIGNIFICANT_DELTA": CAUSAL_SIGNIFICANT_DELTA,
            "MEMORY_DECISION_ID_LEN": MEMORY_DECISION_ID_LEN,
            "ATTRIBUTION_MAX_ITEMS": ATTRIBUTION_MAX_ITEMS,
            "router_weights": dict(self.routing_stats["router"]["weights"]),
        }

    def build_chat_memory_plan(
        self,
        *,
        client_id: str,
        query: str,
        tool_names: list[str],
        tool_catalog: Optional[list[dict[str, Any]]] = None,
        context_engine: Any,
        tem: Any,
    ) -> dict[str, Any]:
        memory = context_engine.get_memory(client_id)
        routing = self._route_tools(query, tool_names, tool_catalog or [], tem, client_id=client_id)
        context_tool_names = routing["selected_tools"] or tool_names

        snapshot = tem.get_context_snapshot(query, context_tool_names)
        relevant_tools = snapshot.get("relevant_tools", context_tool_names)
        recipes = snapshot.get("recipes", [])
        guards = snapshot.get("guards", [])

        retention = self._build_retention_view(memory)
        forgetting = self._build_forgetting_view(memory, recipes, guards)
        attribution = self._build_chat_attribution(memory, recipes, guards, routing)
        governance = self._apply_forgetting_governance(
            memory,
            forgetting,
            tem,
            client_id=client_id,
            phase="chat_preparation",
        )

        plan = {
            "timestamp": _utc_now(),
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "phase": "chat_preparation",
            "client_id": client_id,
            "query": query,
            "routing": {
                **routing,
                "context_tool_names": context_tool_names,
                "relevant_tools": relevant_tools,
            },
            "retention": retention,
            "forgetting": forgetting,
            "governance": governance,
            "attribution": [asdict(item) for item in attribution],
            "causal_ablation": self._build_ablation_report(routing, attribution),
        }
        plan = self._finalize_plan_snapshot(plan)
        self._remember(plan)
        self._append_trace(plan)
        return plan

    def build_tool_memory_plan(
        self,
        *,
        client_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        server_name: str,
        task_description: str = "",
        tem: Any,
        allow_recipe_preflight_block: bool = True,
    ) -> dict[str, Any]:
        task_text = task_description or tool_name
        snapshot = tem.get_context_snapshot(task_text, [tool_name])
        recipes = snapshot.get("recipes", [])
        guards = snapshot.get("guards", [])
        recipe_preflight = tem.get_recipe_preflight(
            tool_name=tool_name,
            arguments=arguments,
            server_name=server_name,
            task_description=task_text,
        )
        if not allow_recipe_preflight_block and recipe_preflight.get("decision") == "block":
            recipe_preflight = {
                **recipe_preflight,
                "decision": "warn",
                "original_decision": "block",
                "reason": (
                    f"{recipe_preflight.get('reason', '')};"
                    "manual_explicit_tool_call_recipe_block_downgraded"
                ).strip(";"),
            }
        retention = {
            "tracked_pending_steps": True,
            "retention_trace_budget": RETENTION_MAX_TRACE_ITEMS,
            "arguments_schema_keys": sorted(arguments.keys()),
        }
        explicit_routing = {
            "selected_tools": [tool_name],
            "server_name": server_name,
            "arguments_schema_keys": sorted(arguments.keys()),
            "reason": "explicit_tool_call",
            "intent_signature": "explicit_tool_call",
            "scores": [],
            "router_type": "explicit",
            "evaluation_ready": True,
        }
        forgetting = self._build_forgetting_view(None, recipes, guards)
        attribution = self._build_tool_attribution(tool_name, recipes, guards)
        governance = self._apply_forgetting_governance(
            None,
            forgetting,
            tem,
            client_id=client_id,
            phase="tool_precheck",
        )

        plan = {
            "timestamp": _utc_now(),
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "phase": "tool_precheck",
            "client_id": client_id,
            "task_description": task_text,
            "tool_name": tool_name,
            "server_name": server_name,
            "routing": explicit_routing,
            "retention": retention,
            "forgetting": forgetting,
            "governance": governance,
            "execution_policy": {
                "recipe_preflight": recipe_preflight,
                "guard_context_count": len(guards),
                "recommended_action": (
                    "blocked"
                    if recipe_preflight.get("decision") == "block"
                    else recipe_preflight.get("decision", "proceed")
                ),
            },
            "attribution": [asdict(item) for item in attribution],
            "causal_ablation": self._build_ablation_report(explicit_routing, attribution),
        }
        plan = self._finalize_plan_snapshot(plan)
        self._remember(plan)
        self._append_trace(plan)
        return plan

    def build_routed_tool_execution_plan(
        self,
        *,
        client_id: str,
        query: str,
        candidate_tool_names: list[str],
        tool_catalog: list[dict[str, Any]],
        arguments: dict[str, Any],
        context_engine: Any,
        tem: Any,
        server_name: str = "",
        dry_run: bool = False,
        feature_mask: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        feature_mask = _normalize_feature_mask(feature_mask)
        memory = context_engine.get_memory(client_id)
        routing = self._route_tools(
            query,
            candidate_tool_names,
            tool_catalog or [],
            tem,
            client_id=client_id,
            feature_mask=feature_mask,
        )
        context_tool_names = routing["selected_tools"] or candidate_tool_names
        snapshot = tem.get_context_snapshot(query, context_tool_names)
        relevant_tools = snapshot.get("relevant_tools", context_tool_names)
        recipes = snapshot.get("recipes", [])
        guards = snapshot.get("guards", [])

        retention = {
            "tracked_pending_steps": True,
            "retention_trace_budget": RETENTION_MAX_TRACE_ITEMS,
            "arguments_schema_keys": sorted(arguments.keys()),
            "routing_query_length": len((query or "").strip()),
        }
        forgetting = self._build_forgetting_view(memory, recipes, guards)
        attribution = self._build_chat_attribution(memory, recipes, guards, routing)
        if dry_run:
            governance = {
                "policy_executed": False,
                "policy_version": str(forgetting.get("policy_version", "memory_governance_v2")),
                "reason": "dry_run_routed_tool_execution",
                "events": [],
            }
        else:
            governance = self._apply_forgetting_governance(
                memory,
                forgetting,
                tem,
                client_id=client_id,
                phase="policy_routed_tool_call",
            )

        selected_tool = str((routing.get("selected_tools") or [""])[0]).strip() if routing.get("selected_tools") else ""
        selected_server_name = str(server_name or "")
        if selected_tool and not selected_server_name:
            for tool in tool_catalog or []:
                if str(tool.get("name", "")).strip() == selected_tool:
                    selected_server_name = str(tool.get("server", "")).strip()
                    if selected_server_name:
                        break
        recipe_preflight = (
            tem.get_recipe_preflight(
                tool_name=selected_tool,
                arguments=arguments,
                server_name=selected_server_name,
                task_description=query,
            )
            if selected_tool
            else {
                "decision": "no_candidate",
                "reason": "router_returned_no_tool",
            }
        )

        plan = {
            "timestamp": _utc_now(),
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "phase": "policy_routed_tool_call",
            "client_id": client_id,
            "query": query,
            "task_description": query,
            "tool_name": selected_tool,
            "server_name": selected_server_name,
            "routing": {
                **routing,
                "context_tool_names": context_tool_names,
                "relevant_tools": relevant_tools,
            },
            "retention": retention,
            "forgetting": forgetting,
            "governance": governance,
            "execution_policy": {
                "recipe_preflight": recipe_preflight,
                "guard_context_count": len(guards),
                "recommended_action": (
                    "blocked"
                    if recipe_preflight.get("decision") == "block"
                    else recipe_preflight.get("decision", "proceed")
                ),
                "candidate_tool_count": len(candidate_tool_names),
                "feature_mask": dict(feature_mask),
            },
            "attribution": [asdict(item) for item in attribution],
            "causal_ablation": self._build_ablation_report(routing, attribution),
        }
        plan = self._finalize_plan_snapshot(plan)
        self._remember(plan)
        self._append_trace(plan)
        return plan

    def get_runtime_snapshot(self) -> dict[str, Any]:
        return self._finalize_plan_snapshot(self.last_snapshot)

    def get_ledger_snapshot(self, limit: int = 20) -> dict[str, Any]:
        self._ensure_ledger_shape()
        safe_limit = max(1, min(int(limit), 200))
        return {
            "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
            "ledger_path": str(MEMORY_POLICY_LEDGER_PATH),
            "summary": self._build_ledger_summary(),
            "training_events": list(self.routing_stats.get("training_events", []))[-safe_limit:],
            "governance_events": list(self.routing_stats.get("governance_events", []))[-safe_limit:],
            "causal_events": list(self.routing_stats.get("causal_events", []))[-safe_limit:],
            "shadow_replay_events": list(self.routing_stats.get("shadow_replay_events", []))[-safe_limit:],
            "rollback_events": list(self.routing_stats.get("rollback_events", []))[-safe_limit:],
            "system_op_events": list(self.routing_stats.get("system_op_events", []))[-safe_limit:],
        }

    def register_system_operation_audit(
        self,
        *,
        task_id: str,
        client_id: str,
        step_id: str,
        action_type: str,
        payload: dict[str, Any],
        result: dict[str, Any],
        decision: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, Any]:
        """Optionally absorb System Operation Plane audit as a separate memory channel.

        This does not create recipe or guard objects.  It only gives Memory
        Plane a governance-side evidence channel tagged with
        ``source_plane=system_op``.
        """
        event = {
            "timestamp": _utc_now(),
            "event_type": "system_operation",
            "event_category": "operation_audit",
            "phase": "system_operation_audit",
            "client_id": str(client_id or ""),
            "source_plane": "system_op",
            "task_id": str(task_id or ""),
            "step_id": str(step_id or ""),
            "action_type": str(action_type or ""),
            "success": bool((result or {}).get("success", False)),
            "risk_level": str((decision or {}).get("risk_level", "")),
            "policy_action": str((decision or {}).get("policy_action", "")),
            "audit_id": str((audit or {}).get("audit_id", "")),
            "payload_preview": json.dumps(payload or {}, ensure_ascii=False, default=str)[:800],
            "result_preview": json.dumps(result or {}, ensure_ascii=False, default=str)[:1200],
        }
        self._append_bounded_ledger_event("system_op_events", event)
        self._save_routing_stats()
        return event

    def _get_router_weights(self) -> dict[str, float]:
        self._ensure_ledger_shape()
        return self.routing_stats["router"]["weights"]

    def _get_intent_prototype_similarity(self, intent_signature: str, query_vec: dict[str, float]) -> float:
        self._ensure_ledger_shape()
        prototypes = self.routing_stats["router"].get("intent_prototypes", {})
        prototype = prototypes.get(intent_signature, {})
        if not isinstance(prototype, dict):
            return 0.0
        return _cosine(query_vec, {str(k): _safe_float(v, 0.0) for k, v in prototype.items()})

    def _get_tool_prototype_similarity(self, tool_name: str, query_vec: dict[str, float]) -> float:
        self._ensure_ledger_shape()
        prototypes = self.routing_stats["router"].get("tool_prototypes", {})
        prototype = prototypes.get(tool_name, {})
        if not isinstance(prototype, dict):
            return 0.0
        return _cosine(query_vec, {str(k): _safe_float(v, 0.0) for k, v in prototype.items()})

    def _get_intent_tool_prototype_similarity(self, intent_signature: str, tool_name: str, query_vec: dict[str, float]) -> float:
        self._ensure_ledger_shape()
        prototypes = self.routing_stats["router"].get("intent_tool_prototypes", {})
        prototype = prototypes.get(f"{intent_signature}::{tool_name}", {})
        if not isinstance(prototype, dict):
            return 0.0
        return _cosine(query_vec, {str(k): _safe_float(v, 0.0) for k, v in prototype.items()})

    def _get_reliability_bandit_score(self, tool_name: str, intent_signature: str) -> float:
        self._ensure_ledger_shape()
        router = self.routing_stats["router"]
        alpha_map = router.get("bandit_alpha", {})
        beta_map = router.get("bandit_beta", {})
        tool_key = tool_name
        intent_key = f"{intent_signature}::{tool_name}"
        tool_alpha = _safe_float(alpha_map.get(tool_key, 1.0), 1.0)
        tool_beta = _safe_float(beta_map.get(tool_key, 1.0), 1.0)
        intent_alpha = _safe_float(alpha_map.get(intent_key, tool_alpha), tool_alpha)
        intent_beta = _safe_float(beta_map.get(intent_key, tool_beta), tool_beta)
        tool_mean = tool_alpha / max(tool_alpha + tool_beta, 1e-12)
        intent_mean = intent_alpha / max(intent_alpha + intent_beta, 1e-12)
        return _clamp(0.4 * tool_mean + 0.6 * intent_mean)

    def _get_episodic_support(
        self,
        *,
        query_vec: dict[str, float],
        tool_name: str,
        intent_signature: str,
    ) -> tuple[float, float]:
        self._ensure_ledger_shape()
        examples = self.routing_stats["router"].get("episodic_examples", [])
        if not isinstance(examples, list) or not examples:
            return 0.0, 0.0
        scored_success = 0.0
        scored_failure = 0.0
        for raw in examples[-ROUTING_MAX_EPISODIC_EXAMPLES:]:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("tool_name", "")) != tool_name:
                continue
            stored_vec = raw.get("query_vec", {})
            if not isinstance(stored_vec, dict) or not stored_vec:
                continue
            similarity = max(
                _cosine(
                    query_vec,
                    {str(key): _safe_float(value, 0.0) for key, value in stored_vec.items()},
                ),
                0.0,
            )
            if similarity <= 0.0:
                continue
            recency = _exp_freshness(_days_since(str(raw.get("timestamp", ""))), ROUTING_EPISODIC_DECAY)
            intent_bonus = 1.0 if str(raw.get("intent_signature", "")) == intent_signature else 0.7
            contribution = similarity * recency * intent_bonus
            if bool(raw.get("success", False)):
                scored_success += contribution
            else:
                scored_failure += contribution
        return _clamp(scored_success), _clamp(scored_failure)

    def _get_pairwise_preference_support(
        self,
        *,
        tool_name: str,
        intent_signature: str,
        candidate_names: list[str],
    ) -> float:
        self._ensure_ledger_shape()
        router = self.routing_stats["router"]
        preferences = router.get("pairwise_preferences", {})
        if not isinstance(preferences, dict):
            return 0.0
        wins = 0.0
        losses = 0.0
        for other_tool in candidate_names:
            if other_tool == tool_name:
                continue
            key = f"{intent_signature}::{tool_name}>>{other_tool}"
            reverse_key = f"{intent_signature}::{other_tool}>>{tool_name}"
            raw_wins = preferences.get(key, {})
            raw_losses = preferences.get(reverse_key, {})
            if isinstance(raw_wins, dict):
                wins += _safe_float(raw_wins.get("wins", 0.0), 0.0)
                losses += _safe_float(raw_wins.get("losses", 0.0), 0.0)
            if isinstance(raw_losses, dict):
                wins += _safe_float(raw_losses.get("losses", 0.0), 0.0)
                losses += _safe_float(raw_losses.get("wins", 0.0), 0.0)
        alpha = ROUTING_PAIRWISE_PRIOR_ALPHA + wins
        beta = ROUTING_PAIRWISE_PRIOR_BETA + losses
        return _clamp(alpha / max(alpha + beta, 1e-12))

    def _apply_rank_reranking(
        self,
        *,
        scored: list[dict[str, Any]],
        intent_signature: str,
        feature_mask: Optional[dict[str, bool]] = None,
    ) -> list[dict[str, Any]]:
        if not scored:
            return []
        feature_mask = _normalize_feature_mask(feature_mask)
        top_limit = max(1, min(ROUTING_RERANK_TOP_CANDIDATES, len(scored)))
        top_candidates = [dict(item) for item in scored[:top_limit]]
        candidate_names = [str(item.get("tool_name", "")) for item in top_candidates]
        listwise_probs = _softmax(
            [_safe_float(item.get("final_score", 0.0), 0.0) for item in top_candidates],
            ROUTING_LISTWISE_TEMPERATURE,
        )
        for index, candidate in enumerate(top_candidates):
            pairwise_support = self._get_pairwise_preference_support(
                tool_name=str(candidate.get("tool_name", "")),
                intent_signature=intent_signature,
                candidate_names=candidate_names,
            )
            listwise_support = listwise_probs[index] if index < len(listwise_probs) else 0.0
            masked_pairwise_support = _masked_feature_value(
                "pairwise_preference_support",
                pairwise_support,
                feature_mask,
            )
            masked_listwise_support = _masked_feature_value(
                "listwise_context_support",
                listwise_support,
                feature_mask,
            )
            rerank_score = _clamp(
                _safe_float(candidate.get("final_score", 0.0), 0.0)
                + ROUTING_PAIRWISE_PREFERENCE_WEIGHT * masked_pairwise_support
                + ROUTING_LISTWISE_CONTEXT_WEIGHT * masked_listwise_support
            )
            feature_vector = dict(candidate.get("feature_vector", {}))
            feature_vector["pairwise_preference_support"] = round(masked_pairwise_support, 4)
            feature_vector["listwise_context_support"] = round(masked_listwise_support, 4)
            candidate["pairwise_preference_support"] = round(masked_pairwise_support, 4)
            candidate["listwise_context_support"] = round(masked_listwise_support, 4)
            candidate["pairwise_preference_observed"] = round(pairwise_support, 4)
            candidate["listwise_context_observed"] = round(listwise_support, 4)
            candidate["prerank_score"] = round(_safe_float(candidate.get("final_score", 0.0), 0.0), 4)
            candidate["rerank_score"] = round(rerank_score, 4)
            candidate["final_score"] = round(rerank_score, 4)
            candidate["feature_vector"] = feature_vector
            candidate["score_components"] = {
                **dict(candidate.get("score_components", {})),
                "pairwise_preference_support": round(ROUTING_PAIRWISE_PREFERENCE_WEIGHT * masked_pairwise_support, 4),
                "listwise_context_support": round(ROUTING_LISTWISE_CONTEXT_WEIGHT * masked_listwise_support, 4),
            }
            candidate["reranker"] = {
                "strategy": "pairwise_listwise_reranker_v1",
                "pairwise_preference_support": round(pairwise_support, 4),
                "listwise_context_support": round(listwise_support, 4),
                "temperature": round(ROUTING_LISTWISE_TEMPERATURE, 4),
            }
        top_candidates.sort(
            key=lambda item: (
                _safe_float(item.get("final_score", 0.0), 0.0),
                _safe_float(item.get("router_probability", 0.0), 0.0),
            ),
            reverse=True,
        )
        return top_candidates + scored[top_limit:]

    def _build_router_diagnostics(self, router: dict[str, Any]) -> dict[str, Any]:
        episodic_examples = router.get("episodic_examples", [])
        return {
            "updates": int(router.get("updates", 0)),
            "learning_rate": round(_safe_float(router.get("learning_rate", ROUTING_ONLINE_LEARNING_RATE), ROUTING_ONLINE_LEARNING_RATE), 4),
            "l2": round(_safe_float(router.get("l2", ROUTING_ONLINE_L2), ROUTING_ONLINE_L2), 4),
            "last_update": str(router.get("last_update", "")),
            "intent_prototype_count": len(router.get("intent_prototypes", {})),
            "tool_prototype_count": len(router.get("tool_prototypes", {})),
            "intent_tool_prototype_count": len(router.get("intent_tool_prototypes", {})),
            "episodic_example_count": len(episodic_examples) if isinstance(episodic_examples, list) else 0,
            "pairwise_preference_count": len(router.get("pairwise_preferences", {})),
        }

    def snapshot_runtime_state(self, context_engine: Any, tem: Any) -> dict[str, Any]:
        context_memories = getattr(context_engine, "memories", {})
        pending_steps = getattr(tem, "_pending_steps", {})
        recent_decisions = getattr(tem, "_recent_decisions", [])
        return {
            "routing_stats": copy.deepcopy(self.routing_stats),
            "last_snapshot": copy.deepcopy(self.last_snapshot),
            "context_memories": copy.deepcopy(context_memories),
            "tem": {
                "recipes": copy.deepcopy(getattr(tem.recipes, "recipes", {})),
                "guards": copy.deepcopy(getattr(tem.guards, "guards", {})),
                "pending_steps": copy.deepcopy(pending_steps),
                "recent_decisions": copy.deepcopy(list(recent_decisions)),
                "mode": str(getattr(tem, "mode", "")),
                "mode_flags": copy.deepcopy(getattr(tem, "_mode_flags", {})),
            },
        }

    def restore_runtime_state(self, snapshot: dict[str, Any], context_engine: Any, tem: Any) -> None:
        self.routing_stats = copy.deepcopy(snapshot.get("routing_stats", {}))
        self.last_snapshot = copy.deepcopy(snapshot.get("last_snapshot", self.last_snapshot))
        context_memories = getattr(context_engine, "memories", None)
        if isinstance(context_memories, dict):
            context_memories.clear()
            context_memories.update(copy.deepcopy(snapshot.get("context_memories", {})))
        tem_snapshot = snapshot.get("tem", {}) if isinstance(snapshot, dict) else {}
        if isinstance(tem_snapshot, dict):
            tem.recipes.import_snapshot(copy.deepcopy(tem_snapshot.get("recipes", {})))
            tem.guards.import_snapshot(copy.deepcopy(tem_snapshot.get("guards", {})))
            tem._pending_steps = copy.deepcopy(tem_snapshot.get("pending_steps", {}))
            try:
                tem._recent_decisions.clear()
                tem._recent_decisions.extend(copy.deepcopy(tem_snapshot.get("recent_decisions", [])))
            except Exception as recent_error:
                logger.warning("Failed to restore recent TEM decisions: %s", recent_error)
            if tem_snapshot.get("mode"):
                tem.mode = str(tem_snapshot.get("mode"))
            if isinstance(tem_snapshot.get("mode_flags"), dict):
                tem._mode_flags = copy.deepcopy(tem_snapshot.get("mode_flags", {}))
        self._ensure_ledger_shape()

    def _get_transition_prior(self, client_id: str, tool_name: str) -> float:
        self._ensure_ledger_shape()
        previous_tool = str(self.routing_stats.get("last_selected_tool_by_client", {}).get(client_id, ""))
        if not previous_tool:
            return 0.0
        transition_key = f"{previous_tool}::{tool_name}"
        count = _safe_float(self.routing_stats.get("tool_transition_counts", {}).get(transition_key, 0.0), 0.0)
        total = 0.0
        for key, value in self.routing_stats.get("tool_transition_counts", {}).items():
            if str(key).startswith(f"{previous_tool}::"):
                total += _safe_float(value, 0.0)
        if total <= ROUTING_PROTOTYPE_EPSILON:
            return 0.0
        return count / total

    def _infer_observed_tool_prefix(self, client_id: str, normalized_query: str, tool_names: list[str]) -> list[str]:
        observed: list[str] = []
        previous_tool = str(self.routing_stats.get("last_selected_tool_by_client", {}).get(client_id, "")).strip()
        if previous_tool in tool_names:
            observed.append(previous_tool)

        query_lower = normalized_query.lower()
        marker = "previous_tool"
        if marker in query_lower:
            suffix = normalized_query[query_lower.rfind(marker) + len(marker):].strip()
            explicit_previous = suffix.split()[0].strip("|,:;") if suffix else ""
            if explicit_previous in tool_names and explicit_previous not in observed:
                observed.append(explicit_previous)

        recent_history = self.routing_stats.get("recent_tool_history_by_client", {})
        history = recent_history.get(client_id, []) if isinstance(recent_history, dict) else []
        if isinstance(history, list):
            normalized_history = [str(item).strip() for item in history if str(item).strip() in tool_names]
            for tool_name in normalized_history[-3:]:
                if tool_name not in observed:
                    observed.append(tool_name)
        return observed

    def _build_recipe_next_step_support(
        self,
        *,
        recipe_snapshot: dict[str, Any],
        tool_names: list[str],
        observed_prefix: list[str],
    ) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
        support_by_tool = {tool_name: 0.0 for tool_name in tool_names}
        evidence_by_tool: dict[str, dict[str, Any]] = {}

        for recipe in recipe_snapshot.get("recipes", []):
            steps = [step for step in recipe.get("steps", []) if isinstance(step, dict)]
            if not steps:
                continue
            chain = [str(step.get("tool_name", "")).strip() for step in steps]
            if not any(tool in tool_names for tool in chain):
                continue

            quality = _safe_float(recipe.get("quality_score", recipe.get("success_rate", 0.0)))
            promotion_state = str(recipe.get("promotion_state", ""))
            base_support = quality * (1.0 if promotion_state == "promoted" else 0.7)
            if base_support <= 0.0:
                continue

            matched_prefix_len = _ordered_prefix_match_length(chain, observed_prefix)
            prefix_coverage = matched_prefix_len / max(len(observed_prefix), 1) if observed_prefix else 0.0
            if observed_prefix and matched_prefix_len == 0:
                base_support *= 0.15
            elif observed_prefix and matched_prefix_len < len(observed_prefix):
                base_support *= 0.35 + 0.45 * prefix_coverage

            next_index = matched_prefix_len if matched_prefix_len < len(chain) else len(chain) - 1
            if matched_prefix_len >= len(chain):
                continue

            for index, step_tool in enumerate(chain):
                if step_tool not in support_by_tool:
                    continue
                if index == next_index:
                    position_factor = 1.0
                    match_type = "next_step"
                elif index > next_index:
                    distance = index - next_index
                    position_factor = 0.06 / float(distance * distance)
                    match_type = "future_step"
                else:
                    backward_distance = next_index - index
                    position_factor = 0.02 / float(backward_distance + 1)
                    match_type = "past_step"
                support = _clamp(base_support * position_factor)
                if support > support_by_tool[step_tool]:
                    support_by_tool[step_tool] = support
                    evidence_by_tool[step_tool] = {
                        "recipe_id": str(recipe.get("id", "")),
                        "recipe_name": str(recipe.get("name", "")),
                        "step_index": index,
                        "next_step_index": next_index,
                        "match_type": match_type,
                        "matched_prefix_len": matched_prefix_len,
                        "observed_prefix_len": len(observed_prefix),
                        "prefix_coverage": round(prefix_coverage, 4),
                        "base_support": round(base_support, 4),
                        "position_factor": round(position_factor, 4),
                        "observed_prefix": list(observed_prefix),
                    }
        return support_by_tool, evidence_by_tool

    def _route_tools(
        self,
        query: str,
        tool_names: list[str],
        tool_catalog: list[dict[str, Any]],
        tem: Any,
        *,
        client_id: str = "",
        feature_mask: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        normalized_query = (query or "").strip()
        feature_mask = _normalize_feature_mask(feature_mask)
        if len(normalized_query) < ROUTING_MIN_QUERY_LENGTH:
            return {
                "query_length": len(normalized_query),
                "intent_signature": _intent_signature(normalized_query),
                "selected_tools": [],
                "scores": [],
                "reason": "query_too_short_for_routing",
                "router_type": "online_linear_router",
                "evaluation_ready": False,
                "policy_learning_ready": False,
            }

        query_tokens = _tokenize(normalized_query)
        query_vec = _ngram_vector(normalized_query)
        tool_metadata = {
            str(tool.get("name", "")): {
                "description": str(tool.get("description", "")),
                "display_name": str(tool.get("display_name", tool.get("name", ""))),
                "schema_keys": sorted(((tool.get("input_schema", {}) or {}).get("properties", {}) or {}).keys()),
                "server_name": str(tool.get("server", "")).strip(),
            }
            for tool in tool_catalog
        }
        recipe_snapshot = tem.get_context_snapshot(normalized_query, tool_names)
        intent_signature = _intent_signature(normalized_query)
        observed_prefix = self._infer_observed_tool_prefix(client_id, normalized_query, tool_names)
        recipe_support_by_tool, recipe_evidence_by_tool = self._build_recipe_next_step_support(
            recipe_snapshot=recipe_snapshot,
            tool_names=tool_names,
            observed_prefix=observed_prefix,
        )
        guard_penalty_by_tool = {tool_name: 0.0 for tool_name in tool_names}

        for guard in recipe_snapshot.get("guards", []):
            tool = str(guard.get("tool", guard.get("tool_name", "")))
            failure_prob = _safe_float(guard.get("failure_prob", 0.0))
            if tool in guard_penalty_by_tool:
                guard_penalty_by_tool[tool] = max(guard_penalty_by_tool[tool], failure_prob)

        weights = self._get_router_weights()
        scored: list[dict[str, Any]] = []
        for tool_name in tool_names:
            metadata = tool_metadata.get(tool_name, {})
            server_name = str(metadata.get("server_name", "")).strip()
            tool_text = " ".join(
                [
                    tool_name.replace(".", " "),
                    server_name.replace("_", " "),
                    metadata.get("display_name", ""),
                    metadata.get("description", ""),
                    " ".join(metadata.get("schema_keys", [])),
                ]
            ).strip()
            tool_tokens = _tokenize(tool_text.replace(".", "_"))
            lexical_score = _jaccard(query_tokens, tool_tokens)
            tool_vec = _ngram_vector(tool_text or tool_name.replace(".", " "))
            ngram_score = _cosine(query_vec, tool_vec)
            exact_match_boost = 1.0 if tool_name.lower() in normalized_query.lower() else 0.0
            recipe_support = recipe_support_by_tool.get(tool_name, 0.0)
            recipe_route_evidence = recipe_evidence_by_tool.get(tool_name, {})
            guard_penalty = guard_penalty_by_tool.get(tool_name, 0.0)
            success_count = _safe_float(self.routing_stats["tool_success"].get(tool_name, 0.0))
            failure_count = _safe_float(self.routing_stats["tool_failure"].get(tool_name, 0.0))
            global_reliability = (success_count + 1.0) / (success_count + failure_count + 2.0)
            intent_key = f"{intent_signature}::{tool_name}"
            intent_success = _safe_float(self.routing_stats["intent_success"].get(intent_key, 0.0))
            intent_failure = _safe_float(self.routing_stats["intent_failure"].get(intent_key, 0.0))
            intent_reliability = (intent_success + 1.0) / (intent_success + intent_failure + 2.0)
            prototype_similarity = self._get_intent_prototype_similarity(intent_signature, query_vec)
            tool_prototype_similarity = self._get_tool_prototype_similarity(tool_name, query_vec)
            intent_tool_prototype_similarity = self._get_intent_tool_prototype_similarity(intent_signature, tool_name, query_vec)
            transition_prior = self._get_transition_prior(client_id, tool_name)
            episodic_success_support, episodic_failure_penalty = self._get_episodic_support(
                query_vec=query_vec,
                tool_name=tool_name,
                intent_signature=intent_signature,
            )
            reliability_bandit_score = self._get_reliability_bandit_score(tool_name, intent_signature)

            observed_features = {
                "bias": 1.0,
                "lexical_score": lexical_score,
                "ngram_score": ngram_score,
                "recipe_support": recipe_support,
                "guard_penalty": guard_penalty,
                "exact_match_boost": exact_match_boost,
                "global_reliability": global_reliability,
                "intent_reliability": intent_reliability,
                "prototype_similarity": prototype_similarity,
                "tool_prototype_similarity": tool_prototype_similarity,
                "intent_tool_prototype_similarity": intent_tool_prototype_similarity,
                "transition_prior": transition_prior,
                "episodic_success_support": episodic_success_support,
                "episodic_failure_penalty": episodic_failure_penalty,
                "reliability_bandit_score": reliability_bandit_score,
                "pairwise_preference_support": 0.0,
                "listwise_context_support": 0.0,
            }
            features = {
                name: _masked_feature_value(name, value, feature_mask)
                for name, value in observed_features.items()
            }
            linear_score = sum(weights.get(name, 0.0) * value for name, value in features.items())
            probability = _sigmoid(linear_score)
            compatibility_score = _clamp(
                ROUTING_LEXICAL_WEIGHT * features["lexical_score"]
                + ROUTING_NGRAM_WEIGHT * features["ngram_score"]
                + ROUTING_RECIPE_WEIGHT * features["recipe_support"]
                + ROUTING_EXACT_MATCH_BOOST * features["exact_match_boost"]
                + ROUTING_GLOBAL_RELIABILITY_WEIGHT * features["global_reliability"]
                + ROUTING_INTENT_RELIABILITY_WEIGHT * features["intent_reliability"]
                + ROUTING_PROTOTYPE_WEIGHT * features["prototype_similarity"]
                + ROUTING_TOOL_PROTOTYPE_WEIGHT * features["tool_prototype_similarity"]
                + ROUTING_INTENT_TOOL_PROTOTYPE_WEIGHT * features["intent_tool_prototype_similarity"]
                + ROUTING_TRANSITION_WEIGHT * features["transition_prior"]
                + ROUTING_EPISODIC_SUCCESS_WEIGHT * features["episodic_success_support"]
                + ROUTING_RELIABILITY_BANDIT_WEIGHT * features["reliability_bandit_score"]
                - ROUTING_GUARD_PENALTY_WEIGHT * features["guard_penalty"]
                - ROUTING_EPISODIC_FAILURE_WEIGHT * features["episodic_failure_penalty"]
            )
            final_score = _clamp(
                ROUTING_LEARNED_SCORE_WEIGHT * probability
                + ROUTING_COMPATIBILITY_SCORE_WEIGHT * compatibility_score
            )
            if final_score < ROUTING_MIN_TOOL_SCORE:
                continue
            component_contrib = {
                name: round(weights.get(name, 0.0) * features[name], 4)
                for name in ROUTING_FEATURE_KEYS
                if name != "bias"
            }
            scored.append(
                {
                    "tool_name": tool_name,
                    "intent_signature": intent_signature,
                    "router_type": "online_linear_router",
                    "lexical_score": round(lexical_score, 4),
                    "ngram_score": round(ngram_score, 4),
                    "recipe_support": round(recipe_support, 4),
                    "recipe_route_evidence": recipe_route_evidence,
                    "guard_penalty": round(guard_penalty, 4),
                    "exact_match_boost": round(exact_match_boost, 4),
                    "global_reliability": round(global_reliability, 4),
                    "intent_reliability": round(intent_reliability, 4),
                    "prototype_similarity": round(prototype_similarity, 4),
                    "tool_prototype_similarity": round(tool_prototype_similarity, 4),
                    "intent_tool_prototype_similarity": round(intent_tool_prototype_similarity, 4),
                    "transition_prior": round(transition_prior, 4),
                    "episodic_success_support": round(episodic_success_support, 4),
                    "episodic_failure_penalty": round(episodic_failure_penalty, 4),
                    "reliability_bandit_score": round(reliability_bandit_score, 4),
                    "pairwise_preference_support": 0.0,
                    "listwise_context_support": 0.0,
                    "router_probability": round(probability, 4),
                    "compatibility_score": round(compatibility_score, 4),
                    "final_score": round(final_score, 4),
                    "feature_vector": {key: round(value, 4) for key, value in features.items()},
                    "feature_vector_observed": {key: round(value, 4) for key, value in observed_features.items()},
                    "weight_vector": {key: round(_safe_float(weights.get(key, 0.0)), 4) for key in ROUTING_FEATURE_KEYS},
                    "score_components": component_contrib,
                }
            )

        scored.sort(key=lambda item: item["final_score"], reverse=True)
        scored = self._apply_rank_reranking(
            scored=scored,
            intent_signature=intent_signature,
            feature_mask=feature_mask,
        )
        top = scored[:ROUTING_TOP_K_TOOLS]
        router = self.routing_stats["router"]
        return {
            "query_length": len(normalized_query),
            "intent_signature": intent_signature,
            "selected_tools": [item["tool_name"] for item in top],
            "scores": top,
            "reason": "memory_aware_hybrid_routing",
            "router_type": "hybrid_memory_router_v3_pairwise_listwise",
            "recipe_routing": {
                "strategy": "prefix_conditioned_next_step_support_v1",
                "observed_prefix": observed_prefix,
                "matched_recipe_tools": sorted(
                    tool for tool, score in recipe_support_by_tool.items() if score > 0.0
                ),
            },
            "feature_mask": dict(feature_mask),
            "feature_groups": copy.deepcopy(ROUTING_FEATURE_GROUPS),
            "evaluation_ready": True,
            "policy_learning_ready": bool(top),
            "router_weights": {key: round(_safe_float(weights.get(key, 0.0)), 4) for key in ROUTING_FEATURE_KEYS},
            "router_training_state": self._build_router_diagnostics(router),
        }

    def _build_retention_view(self, memory: Any) -> dict[str, Any]:
        facts = list(getattr(memory, "long_term_facts", []) or [])
        retained_facts: list[dict[str, Any]] = []
        suppressed_facts: list[dict[str, Any]] = []
        for fact in facts:
            confidence = _safe_float(fact.get("confidence", 0.0))
            age_days = _days_since(fact.get("added_at"))
            freshness = _exp_freshness(age_days, FORGETTING_DECAY_DAYS)
            item = {
                "fact": str(fact.get("fact", ""))[:120],
                "confidence": round(confidence, 3),
                "freshness": round(freshness, 3),
            }
            if confidence >= FORGETTING_FACT_MIN_SCORE:
                retained_facts.append(item)
            else:
                item["reason"] = "fact_confidence_below_threshold"
                suppressed_facts.append(item)

        return {
            "message_count": len(getattr(memory, "messages", [])) if memory is not None else 0,
            "has_summary": bool(getattr(memory, "summary", "")) if memory is not None else False,
            "summary_characters": len(getattr(memory, "summary", "")) if memory is not None else 0,
            "long_term_fact_count": len(facts),
            "retained_fact_count": min(len(retained_facts), RETENTION_MAX_FACTS),
            "suppressed_fact_count": len(suppressed_facts),
            "retained_facts": retained_facts[:RETENTION_MAX_FACTS],
            "suppressed_facts": suppressed_facts[:RETENTION_MAX_FACTS],
            "max_context_summaries": RETENTION_MAX_CONTEXT_SUMMARIES,
            "max_retained_facts": RETENTION_MAX_FACTS,
            "trace_budget": RETENTION_MAX_TRACE_ITEMS,
        }

    def _build_forgetting_view(
        self,
        memory: Any,
        recipes: list[dict[str, Any]],
        guards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        summary_age = _days_since(getattr(memory, "updated_at", None)) if memory is not None else None
        summary_freshness = _exp_freshness(summary_age, FORGETTING_DECAY_DAYS)
        summary_action = "retain"
        summary_reason = "fresh_summary"
        if memory is None or not getattr(memory, "summary", ""):
            summary_action = "absent"
            summary_reason = "no_summary_present"
        elif summary_age is not None and summary_age >= FORGETTING_MIN_KEEP_DAYS and summary_freshness < FORGETTING_SUMMARY_MIN_FRESHNESS:
            summary_action = "suppress_from_context"
            summary_reason = "summary_stale"

        recipe_actions: list[dict[str, Any]] = []
        for recipe in recipes:
            quality_score = _safe_float(recipe.get("quality_score", recipe.get("success_rate", 0.0)))
            age_days = _days_since(recipe.get("last_used_at") or recipe.get("created_at"))
            freshness = _exp_freshness(age_days, FORGETTING_DECAY_DAYS)
            verification_rate = _safe_float(recipe.get("verification_rate", recipe.get("success_rate", 0.0)))
            contamination_risk = _safe_float(recipe.get("contamination_risk", 0.0))
            utility = max(
                0.0,
                min(
                    1.0,
                    FORGETTING_RECIPE_QUALITY_WEIGHT * quality_score
                    + FORGETTING_RECIPE_VERIFICATION_WEIGHT * verification_rate
                    + FORGETTING_RECIPE_FRESHNESS_WEIGHT * freshness
                    - FORGETTING_RECIPE_CONTAMINATION_PENALTY * contamination_risk,
                ),
            )
            action = "retain"
            reason = "recipe_utility_above_policy_threshold"
            if age_days is not None and age_days >= FORGETTING_MIN_KEEP_DAYS:
                if utility < FORGETTING_RECIPE_RETIRE_QUALITY:
                    action = "candidate_retire"
                    reason = "recipe_utility_below_retire_threshold"
                elif utility < FORGETTING_RECIPE_MIN_QUALITY:
                    action = "suppress_from_retrieval"
                    reason = "recipe_utility_below_retrieval_threshold"
            recipe_actions.append(
                {
                    "id": str(recipe.get("id", "")),
                    "name": str(recipe.get("name", "recipe")),
                    "quality_score": round(quality_score, 3),
                    "verification_rate": round(verification_rate, 3),
                    "contamination_risk": round(contamination_risk, 3),
                    "freshness": round(freshness, 3),
                    "policy_utility": round(utility, 3),
                    "action": action,
                    "reason": reason,
                    "evidence": {
                        "quality_score": round(quality_score, 3),
                        "verification_rate": round(verification_rate, 3),
                        "freshness": round(freshness, 3),
                        "contamination_risk": round(contamination_risk, 3),
                    },
                }
            )

        guard_actions: list[dict[str, Any]] = []
        for guard in guards:
            failure_prob = _safe_float(guard.get("failure_prob", 0.0))
            age_days = _days_since(guard.get("last_triggered_at") or guard.get("created_at"))
            freshness = _exp_freshness(age_days, FORGETTING_DECAY_DAYS)
            avoided_count = _safe_float(guard.get("avoided_count", 0.0))
            block_count = _safe_float(guard.get("times", guard.get("block_count", 0.0)))
            utility = max(
                0.0,
                min(
                    1.0,
                    FORGETTING_GUARD_FAILURE_WEIGHT * failure_prob
                    + FORGETTING_GUARD_FRESHNESS_WEIGHT * freshness
                    + FORGETTING_GUARD_AVOIDED_WEIGHT * min(avoided_count / max(FORGETTING_GUARD_AVOIDED_CAP, 1e-12), 1.0)
                    + FORGETTING_GUARD_BLOCK_WEIGHT * min(block_count / max(FORGETTING_GUARD_BLOCK_CAP, 1e-12), 1.0),
                ),
            )
            action = "retain"
            reason = "guard_utility_above_policy_threshold"
            if age_days is not None and age_days >= FORGETTING_MIN_KEEP_DAYS:
                if utility < FORGETTING_GUARD_RETIRE_FAILURE_PROB:
                    action = "candidate_retire"
                    reason = "guard_utility_below_retire_threshold"
                elif utility < FORGETTING_GUARD_MIN_FAILURE_PROB:
                    action = "suppress_from_precheck"
                    reason = "guard_utility_below_blocking_threshold"
            guard_actions.append(
                {
                    "id": str(guard.get("id", "")),
                    "tool": str(guard.get("tool", guard.get("tool_name", "guard"))),
                    "failure_prob": round(failure_prob, 3),
                    "freshness": round(freshness, 3),
                    "policy_utility": round(utility, 3),
                    "avoided_count": int(avoided_count),
                    "action": action,
                    "reason": reason,
                    "evidence": {
                        "failure_prob": round(failure_prob, 3),
                        "freshness": round(freshness, 3),
                        "avoided_count": int(avoided_count),
                        "block_count": int(block_count),
                    },
                }
            )

        return {
            "decay_days": FORGETTING_DECAY_DAYS,
            "min_keep_days": FORGETTING_MIN_KEEP_DAYS,
            "policy_version": "memory_governance_v2",
            "summary": {
                "freshness": round(summary_freshness, 4),
                "action": summary_action,
                "reason": summary_reason,
            },
            "recipes": recipe_actions[:ATTRIBUTION_MAX_ITEMS],
            "guards": guard_actions[:ATTRIBUTION_MAX_ITEMS],
        }

    def _apply_forgetting_governance(
        self,
        memory: Any,
        forgetting: dict[str, Any],
        tem: Any,
        *,
        client_id: str = "",
        phase: str = "",
    ) -> dict[str, Any]:
        recipe_actions = forgetting.get("recipes", [])
        guard_actions = forgetting.get("guards", [])
        recipe_changes = tem.recipes.apply_governance_actions(recipe_actions)
        guard_changes = tem.guards.apply_governance_actions(guard_actions)
        governance_timestamp = _utc_now()
        policy_version = str(forgetting.get("policy_version", "memory_governance_v2"))

        suppressed_fact_hashes: list[str] = []
        fact_events: list[dict[str, Any]] = []
        if memory is not None:
            retained = []
            for fact in list(getattr(memory, "long_term_facts", []) or []):
                confidence = _safe_float(fact.get("confidence", 0.0))
                age_days = _days_since(fact.get("added_at"))
                freshness = _exp_freshness(age_days, FORGETTING_DECAY_DAYS)
                keep = confidence >= FORGETTING_FACT_MIN_SCORE or (age_days is not None and age_days < FORGETTING_MIN_KEEP_DAYS)
                if keep and freshness >= FORGETTING_SUMMARY_MIN_FRESHNESS:
                    retained.append(fact)
                    continue
                fact_hash = str(fact.get("hash", ""))
                suppressed_fact_hashes.append(fact_hash)
                fact_events.append(
                    self._normalize_governance_event(
                        {
                            "timestamp": governance_timestamp,
                            "phase": phase,
                            "client_id": client_id,
                            "policy_version": policy_version,
                            "decision_id": _decision_id("fact", fact_hash, "suppress_from_context", "fact_policy"),
                            "kind": "fact",
                            "item_id": fact_hash,
                            "action": "suppress_from_context",
                            "reason": "fact_policy",
                            "applied": True,
                            "evidence": {
                                "confidence": round(confidence, 3),
                                "freshness": round(freshness, 3),
                            },
                        }
                    )
                )
            if len(retained) != len(getattr(memory, "long_term_facts", [])):
                memory.long_term_facts = retained[-RETENTION_MAX_FACTS:]
                memory.updated_at = _utc_now()
                try:
                    memory.save()
                except Exception as exc:
                    logger.warning("Failed to persist governed memory facts: %s", exc)

        governance_events: list[dict[str, Any]] = []
        for item in recipe_actions:
            event = self._normalize_governance_event(
                {
                    "timestamp": governance_timestamp,
                    "phase": phase,
                    "client_id": client_id,
                    "policy_version": policy_version,
                    "decision_id": _decision_id("recipe", str(item.get("id", "")), str(item.get("action", "retain")), str(item.get("reason", "policy"))),
                    "kind": "recipe",
                    "item_id": str(item.get("id", "")),
                    "action": str(item.get("action", "retain")),
                    "reason": str(item.get("reason", "policy")),
                    "applied": str(item.get("action", "retain")) != "retain",
                    "evidence": dict(item.get("evidence", {})),
                }
            )
            governance_events.append(event)
            self._append_bounded_ledger_event("governance_events", event)
        for item in guard_actions:
            event = self._normalize_governance_event(
                {
                    "timestamp": governance_timestamp,
                    "phase": phase,
                    "client_id": client_id,
                    "policy_version": policy_version,
                    "decision_id": _decision_id("guard", str(item.get("id", "")), str(item.get("action", "retain")), str(item.get("reason", "policy"))),
                    "kind": "guard",
                    "item_id": str(item.get("id", "")),
                    "action": str(item.get("action", "retain")),
                    "reason": str(item.get("reason", "policy")),
                    "applied": str(item.get("action", "retain")) != "retain",
                    "evidence": dict(item.get("evidence", {})),
                }
            )
            governance_events.append(event)
            self._append_bounded_ledger_event("governance_events", event)
        for event in fact_events:
            governance_events.append(event)
            self._append_bounded_ledger_event("governance_events", event)
        self._save_routing_stats()

        return {
            "policy_executed": True,
            "policy_version": policy_version,
            "recipes": recipe_changes,
            "guards": guard_changes,
            "suppressed_fact_hashes": [value for value in suppressed_fact_hashes if value],
            "events": governance_events[-RETENTION_MAX_TRACE_ITEMS:],
        }

    def _build_chat_attribution(
        self,
        memory: Any,
        recipes: list[dict[str, Any]],
        guards: list[dict[str, Any]],
        routing: dict[str, Any],
    ) -> list[MemoryAttributionItem]:
        items: list[MemoryAttributionItem] = []
        if memory is not None and getattr(memory, "summary", ""):
            freshness = _exp_freshness(_days_since(getattr(memory, "updated_at", None)), FORGETTING_DECAY_DAYS)
            score = min(len(memory.summary) / 800.0, 1.0)
            rationale = "compressed episodic context retained for chat planning"
            items.append(MemoryAttributionItem("context_summary", "conversation_summary", "conversation summary", round(score, 4), round(freshness, 4), rationale))
        for recipe in recipes[:ATTRIBUTION_MAX_ITEMS]:
            freshness = _exp_freshness(_days_since(recipe.get("last_used_at") or recipe.get("created_at")), FORGETTING_DECAY_DAYS)
            items.append(
                MemoryAttributionItem(
                    "recipe_memory",
                    str(recipe.get("id", "")),
                    str(recipe.get("name", "recipe")),
                    _safe_float(recipe.get("quality_score", recipe.get("success_rate", 0.0))),
                    round(freshness, 4),
                    (
                        f"recipe state={recipe.get('promotion_state', 'unknown')}, "
                        f"governance={recipe.get('governance_state', 'unknown')}, "
                        f"verification={_safe_float(recipe.get('verification_rate', 0.0)):.2f}"
                    ),
                )
            )
        for guard in guards[:ATTRIBUTION_MAX_ITEMS]:
            freshness = _exp_freshness(_days_since(guard.get("last_triggered_at") or guard.get("created_at")), FORGETTING_DECAY_DAYS)
            items.append(
                MemoryAttributionItem(
                    "guard_memory",
                    str(guard.get("id", "")),
                    str(guard.get("tool", guard.get("tool_name", "guard"))),
                    _safe_float(guard.get("failure_prob", 0.0)),
                    round(freshness, 4),
                    f"failure evidence with governance={guard.get('governance_state', 'unknown')}",
                )
            )
        for candidate in routing.get("scores", [])[:ATTRIBUTION_MAX_ITEMS]:
            if candidate.get("tool_name") not in routing.get("selected_tools", []):
                continue
            items.append(
                MemoryAttributionItem(
                    "routing_evidence",
                    str(candidate.get("tool_name", "")),
                    f"routing:{candidate.get('tool_name', '')}",
                    _safe_float(candidate.get("final_score", 0.0)),
                    1.0,
                    f"router_probability={_safe_float(candidate.get('router_probability', 0.0)):.3f}",
                )
            )
        items.sort(key=lambda item: (item.score * item.freshness), reverse=True)
        return items[:ATTRIBUTION_MAX_ITEMS]

    def _build_tool_attribution(
        self,
        tool_name: str,
        recipes: list[dict[str, Any]],
        guards: list[dict[str, Any]],
    ) -> list[MemoryAttributionItem]:
        items: list[MemoryAttributionItem] = []
        for recipe in recipes[:ATTRIBUTION_MAX_ITEMS]:
            freshness = _exp_freshness(_days_since(recipe.get("last_used_at") or recipe.get("created_at")), FORGETTING_DECAY_DAYS)
            items.append(
                MemoryAttributionItem(
                    "recipe_memory",
                    str(recipe.get("id", "")),
                    f"{tool_name}:{recipe.get('name', 'recipe')}",
                    _safe_float(recipe.get("quality_score", recipe.get("success_rate", 0.0))),
                    round(freshness, 4),
                    (
                        f"recipe state={recipe.get('promotion_state', 'unknown')}, "
                        f"governance={recipe.get('governance_state', 'unknown')}, "
                        f"verification={_safe_float(recipe.get('verification_rate', 0.0)):.2f}"
                    ),
                )
            )
        for guard in guards[:ATTRIBUTION_MAX_ITEMS]:
            freshness = _exp_freshness(_days_since(guard.get("last_triggered_at") or guard.get("created_at")), FORGETTING_DECAY_DAYS)
            items.append(
                MemoryAttributionItem(
                    "guard_memory",
                    str(guard.get("id", "")),
                    f"{tool_name}:{guard.get('error', guard.get('error_type', 'guard'))}",
                    _safe_float(guard.get("failure_prob", 0.0)),
                    round(freshness, 4),
                    f"safety evidence with governance={guard.get('governance_state', 'unknown')}",
                )
            )
        items.sort(key=lambda item: (item.score * item.freshness), reverse=True)
        return items[:ATTRIBUTION_MAX_ITEMS]

    def _build_ablation_report(self, routing: dict[str, Any], attribution: list[MemoryAttributionItem]) -> dict[str, Any]:
        selected = routing.get("scores", [])[:1]
        if not selected:
            return {"available": False, "reason": "no_routing_candidate"}
        candidate = selected[0]
        feature_vector = dict(candidate.get("feature_vector", {}))
        weight_vector = dict(candidate.get("weight_vector", {}))
        baseline_probability = _safe_float(candidate.get("router_probability", 0.0))
        ablations = []
        for feature_name in (
            "recipe_support",
            "guard_penalty",
            "global_reliability",
            "intent_reliability",
            "exact_match_boost",
            "tool_prototype_similarity",
            "intent_tool_prototype_similarity",
            "episodic_success_support",
            "episodic_failure_penalty",
            "reliability_bandit_score",
            "pairwise_preference_support",
            "listwise_context_support",
        ):
            modified = dict(feature_vector)
            modified[feature_name] = 0.0
            linear_score = sum(_safe_float(weight_vector.get(name, 0.0)) * _safe_float(modified.get(name, 0.0)) for name in ROUTING_FEATURE_KEYS)
            counterfactual_probability = _sigmoid(linear_score)
            delta = baseline_probability - counterfactual_probability
            ablations.append(
                {
                    "feature": feature_name,
                    "baseline_probability": round(baseline_probability, 4),
                    "counterfactual_probability": round(counterfactual_probability, 4),
                    "delta": round(delta, 4),
                    "significant": abs(delta) >= CAUSAL_SIGNIFICANT_DELTA,
                }
            )
        return {
            "available": True,
            "selected_tool": candidate.get("tool_name", ""),
            "router_type": routing.get("router_type", "unknown"),
            "ablations": ablations,
            "attribution_sources": [item.source for item in attribution],
            "significant_effects": [item["feature"] for item in ablations if item["significant"]],
        }

    def register_chat_context(self, plan: dict[str, Any], tem: Any) -> None:
        recipe_ids = [
            str(item.get("item_id", ""))
            for item in plan.get("attribution", [])
            if item.get("source") == "recipe_memory" and item.get("item_id")
        ]
        if recipe_ids:
            tem.recipes.record_retrieval(recipe_ids)

    def _update_router_weights(self, feature_vector: dict[str, Any], target: float) -> dict[str, float]:
        self._ensure_ledger_shape()
        router = self.routing_stats["router"]
        weights = router["weights"]
        learning_rate = _safe_float(router.get("learning_rate", ROUTING_ONLINE_LEARNING_RATE), ROUTING_ONLINE_LEARNING_RATE)
        l2 = _safe_float(router.get("l2", ROUTING_ONLINE_L2), ROUTING_ONLINE_L2)
        linear_score = sum(_safe_float(weights.get(name, 0.0)) * _safe_float(feature_vector.get(name, 0.0)) for name in ROUTING_FEATURE_KEYS)
        prediction = _sigmoid(linear_score)
        error = target - prediction
        for name in ROUTING_FEATURE_KEYS:
            current_weight = _safe_float(weights.get(name, 0.0))
            feature_value = _safe_float(feature_vector.get(name, 0.0))
            updated = current_weight + learning_rate * (error * feature_value - l2 * current_weight)
            weights[name] = round(updated, 6)
        router["updates"] = int(router.get("updates", 0)) + 1
        router["last_update"] = _utc_now()
        return {name: round(_safe_float(weights.get(name, 0.0)), 6) for name in ROUTING_FEATURE_KEYS}

    def _update_pairwise_preferences(
        self,
        *,
        intent_signature: str,
        selected_tool: str,
        ranked_candidates: list[str],
        outcome_positive: bool,
    ) -> None:
        self._ensure_ledger_shape()
        if not selected_tool:
            return
        router = self.routing_stats["router"]
        preferences = router.setdefault("pairwise_preferences", {})
        if not isinstance(preferences, dict):
            return
        for other_tool in ranked_candidates:
            other_tool = str(other_tool or "")
            if not other_tool or other_tool == selected_tool:
                continue
            key = f"{intent_signature}::{selected_tool}>>{other_tool}"
            current = preferences.get(key, {})
            if not isinstance(current, dict):
                current = {}
            current["wins"] = round(_safe_float(current.get("wins", 0.0), 0.0) + (1.0 if outcome_positive else 0.0), 4)
            current["losses"] = round(_safe_float(current.get("losses", 0.0), 0.0) + (0.0 if outcome_positive else 1.0), 4)
            current["updated_at"] = _utc_now()
            preferences[key] = current

    def _update_router_memory_structures(
        self,
        *,
        client_id: str,
        intent_signature: str,
        query_text: str,
        selected_tool: str,
        outcome_positive: bool,
    ) -> None:
        self._ensure_ledger_shape()
        router = self.routing_stats["router"]
        prototypes = router.setdefault("intent_prototypes", {})
        tool_prototypes = router.setdefault("tool_prototypes", {})
        intent_tool_prototypes = router.setdefault("intent_tool_prototypes", {})
        episodic_examples = router.setdefault("episodic_examples", [])
        alpha_map = router.setdefault("bandit_alpha", {})
        beta_map = router.setdefault("bandit_beta", {})
        query_vec = _ngram_vector(query_text)
        if outcome_positive and query_vec:
            if intent_signature and intent_signature != "explicit_tool_call":
                current_intent = prototypes.get(intent_signature, {})
                if isinstance(current_intent, dict):
                    prototypes[intent_signature] = _blend_normalized_vectors(
                        {str(k): _safe_float(v, 0.0) for k, v in current_intent.items()},
                        query_vec,
                        ROUTING_PROTOTYPE_LEARNING_RATE,
                    )
            current_tool = tool_prototypes.get(selected_tool, {})
            if isinstance(current_tool, dict):
                tool_prototypes[selected_tool] = _blend_normalized_vectors(
                    {str(k): _safe_float(v, 0.0) for k, v in current_tool.items()},
                    query_vec,
                    ROUTING_PROTOTYPE_LEARNING_RATE,
                )
            if intent_signature and intent_signature != "explicit_tool_call":
                pair_key = f"{intent_signature}::{selected_tool}"
                current_pair = intent_tool_prototypes.get(pair_key, {})
                if isinstance(current_pair, dict):
                    intent_tool_prototypes[pair_key] = _blend_normalized_vectors(
                        {str(k): _safe_float(v, 0.0) for k, v in current_pair.items()},
                        query_vec,
                        ROUTING_PROTOTYPE_LEARNING_RATE,
                    )

        episode = {
            "timestamp": _utc_now(),
            "client_id": client_id,
            "intent_signature": intent_signature,
            "tool_name": selected_tool,
            "success": bool(outcome_positive),
            "query_vec": query_vec,
        }
        episodic_examples.append(episode)
        if len(episodic_examples) > ROUTING_MAX_EPISODIC_EXAMPLES:
            del episodic_examples[:-ROUTING_MAX_EPISODIC_EXAMPLES]

        tool_alpha_key = selected_tool
        intent_alpha_key = f"{intent_signature}::{selected_tool}"
        if outcome_positive:
            alpha_map[tool_alpha_key] = _safe_float(alpha_map.get(tool_alpha_key, 1.0), 1.0) + 1.0
            alpha_map[intent_alpha_key] = _safe_float(alpha_map.get(intent_alpha_key, alpha_map[tool_alpha_key]), alpha_map[tool_alpha_key]) + 1.0
        else:
            beta_map[tool_alpha_key] = _safe_float(beta_map.get(tool_alpha_key, 1.0), 1.0) + 1.0
            beta_map[intent_alpha_key] = _safe_float(beta_map.get(intent_alpha_key, beta_map[tool_alpha_key]), beta_map[tool_alpha_key]) + 1.0

        last_selected = self.routing_stats.setdefault("last_selected_tool_by_client", {})
        recent_history = self.routing_stats.setdefault("recent_tool_history_by_client", {})
        transitions = self.routing_stats.setdefault("tool_transition_counts", {})
        previous_tool = str(last_selected.get(client_id, ""))
        if previous_tool and selected_tool:
            transition_key = f"{previous_tool}::{selected_tool}"
            transitions[transition_key] = int(transitions.get(transition_key, 0)) + 1
        if client_id and selected_tool:
            last_selected[client_id] = selected_tool
            history = recent_history.get(client_id, [])
            if not isinstance(history, list):
                history = []
            history.append(selected_tool)
            recent_history[client_id] = history[-3:]

    def _build_shadow_replay(
        self,
        *,
        selected_tool: str,
        plan: dict[str, Any],
        counterfactual_routing: Optional[dict[str, Any]] = None,
        feature_mask: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        routing = dict(plan.get("routing", {}))
        scores = list(routing.get("scores", []))
        if not scores:
            return {"available": False, "reason": "no_routing_scores"}
        counterfactual_scores = {}
        counterfactual_selected_tool = ""
        if isinstance(counterfactual_routing, dict):
            counterfactual_selected = list(counterfactual_routing.get("scores", []))
            counterfactual_scores = {
                str(item.get("tool_name", "")): item
                for item in counterfactual_selected
                if str(item.get("tool_name", "")).strip()
            }
            selected_tools = list(counterfactual_routing.get("selected_tools", []))
            counterfactual_selected_tool = str(selected_tools[0]) if selected_tools else ""

        replay_items: list[dict[str, Any]] = []
        for candidate in scores[:ROUTING_MAX_SHADOW_REPLAY_ITEMS]:
            tool_name = str(candidate.get("tool_name", ""))
            counterfactual_candidate = counterfactual_scores.get(tool_name, {})
            replay_items.append(
                {
                    "tool_name": tool_name,
                    "observed_final_score": round(_safe_float(candidate.get("final_score", 0.0), 0.0), 4),
                    "observed_probability": round(_safe_float(candidate.get("router_probability", 0.0), 0.0), 4),
                    "counterfactual_final_score": round(_safe_float(counterfactual_candidate.get("final_score", 0.0), 0.0), 4),
                    "counterfactual_probability": round(_safe_float(counterfactual_candidate.get("router_probability", 0.0), 0.0), 4),
                    "score_delta": round(
                        _safe_float(candidate.get("final_score", 0.0), 0.0)
                        - _safe_float(counterfactual_candidate.get("final_score", 0.0), 0.0),
                        4,
                    ),
                    "would_be_selected": tool_name == selected_tool,
                    "counterfactual_would_be_selected": bool(counterfactual_selected_tool) and tool_name == counterfactual_selected_tool,
                    "memory_components": {
                        "recipe_support": round(_safe_float(candidate.get("recipe_support", 0.0), 0.0), 4),
                        "guard_penalty": round(_safe_float(candidate.get("guard_penalty", 0.0), 0.0), 4),
                        "global_reliability": round(_safe_float(candidate.get("global_reliability", 0.0), 0.0), 4),
                        "intent_reliability": round(_safe_float(candidate.get("intent_reliability", 0.0), 0.0), 4),
                        "prototype_similarity": round(_safe_float(candidate.get("prototype_similarity", 0.0), 0.0), 4),
                        "transition_prior": round(_safe_float(candidate.get("transition_prior", 0.0), 0.0), 4),
                    },
                }
            )
        return {
            "available": True,
            "selected_tool": selected_tool,
            "counterfactual_selected_tool": counterfactual_selected_tool,
            "feature_mask": dict(_normalize_feature_mask(feature_mask)),
            "items": replay_items,
        }

    def register_tool_outcome(
        self,
        *,
        selected_tool: str,
        plan: dict[str, Any],
        success: bool,
        blocked: bool = False,
        guard_id: str = "",
        counterfactual: str = "",
        tem: Any,
    ) -> dict[str, Any]:
        self._ensure_ledger_shape()
        outcome_positive = bool(success or blocked)
        self.routing_stats["tool_calls"][selected_tool] = int(self.routing_stats["tool_calls"].get(selected_tool, 0)) + 1
        target_bucket = "tool_success" if outcome_positive else "tool_failure"
        self.routing_stats[target_bucket][selected_tool] = int(self.routing_stats[target_bucket].get(selected_tool, 0)) + 1

        intent_signature = str(plan.get("routing", {}).get("intent_signature", "explicit_tool_call"))
        query_text = str(plan.get("query", plan.get("task_description", "")))
        intent_key = f"{intent_signature}::{selected_tool}"
        self.routing_stats["intent_calls"][intent_key] = int(self.routing_stats["intent_calls"].get(intent_key, 0)) + 1
        intent_target_bucket = "intent_success" if outcome_positive else "intent_failure"
        self.routing_stats[intent_target_bucket][intent_key] = int(self.routing_stats[intent_target_bucket].get(intent_key, 0)) + 1

        recipe_ids = [
            str(item.get("item_id", ""))
            for item in plan.get("attribution", [])
            if item.get("source") == "recipe_memory" and item.get("item_id")
        ]
        if recipe_ids:
            tem.recipes.record_verification_result(recipe_ids, success=success)
        if blocked and guard_id:
            tem.guards.record_avoided_failure(guard_id, counterfactual=counterfactual)

        selected_tools = plan.get("routing", {}).get("selected_tools", []) or [selected_tool]
        routing_scores = plan.get("routing", {}).get("scores", [])
        top_alternative = ""
        selected_score: Optional[dict[str, Any]] = None
        for candidate in routing_scores:
            if str(candidate.get("tool_name", "")) == selected_tool:
                selected_score = candidate
                break
        for candidate in routing_scores:
            candidate_name = str(candidate.get("tool_name", ""))
            if candidate_name and candidate_name != selected_tool:
                top_alternative = candidate_name
                break

        if selected_score and selected_score.get("feature_vector"):
            updated_weights = self._update_router_weights(selected_score.get("feature_vector", {}), 1.0 if outcome_positive else 0.0)
            training_event = {
                "timestamp": _utc_now(),
                "phase": str(plan.get("phase", "tool_outcome_learning")),
                "client_id": str(plan.get("client_id", "")),
                "tool_name": selected_tool,
                "intent_signature": intent_signature,
                "target": 1.0 if outcome_positive else 0.0,
                "blocked": blocked,
                "success": success,
                "feature_vector": dict(selected_score.get("feature_vector", {})),
                "updated_weights": updated_weights,
            }
            self._append_bounded_ledger_event("training_events", training_event)
        ranked_candidates = [
            str(candidate.get("tool_name", ""))
            for candidate in routing_scores
            if str(candidate.get("tool_name", "")).strip()
        ]
        self._update_pairwise_preferences(
            intent_signature=intent_signature,
            selected_tool=selected_tool,
            ranked_candidates=ranked_candidates,
            outcome_positive=outcome_positive,
        )
        self._update_router_memory_structures(
            client_id=str(plan.get("client_id", "")),
            intent_signature=intent_signature,
            query_text=query_text,
            selected_tool=selected_tool,
            outcome_positive=outcome_positive,
        )

        recipe_attribution = [item for item in plan.get("attribution", []) if item.get("source") == "recipe_memory"]
        guard_attribution = [item for item in plan.get("attribution", []) if item.get("source") == "guard_memory"]
        summary_attribution = [item for item in plan.get("attribution", []) if item.get("source") == "context_summary"]
        ablation = self._build_ablation_report(plan.get("routing", {}), [MemoryAttributionItem(**item) if isinstance(item, dict) else item for item in plan.get("attribution", [])])
        baseline_probability = _safe_float(selected_score.get("router_probability", 0.0) if selected_score else 0.0)
        cf_recipe = next((item for item in ablation.get("ablations", []) if item.get("feature") == "recipe_support"), None)
        cf_guard = next((item for item in ablation.get("ablations", []) if item.get("feature") == "guard_penalty"), None)
        cf_global = next((item for item in ablation.get("ablations", []) if item.get("feature") == "global_reliability"), None)
        cf_intent = next((item for item in ablation.get("ablations", []) if item.get("feature") == "intent_reliability"), None)
        causal_event = self._normalize_causal_event(
            {
                "timestamp": _utc_now(),
                "phase": str(plan.get("phase", "tool_outcome")),
                "client_id": str(plan.get("client_id", "")),
                "selected_tool": selected_tool,
                "success": success,
                "blocked": blocked,
                "intent_signature": intent_signature,
                "baseline_probability": round(baseline_probability, 4),
                "ablation": ablation,
            }
        )
        self._append_bounded_ledger_event("causal_events", causal_event)
        shadow_replay = self._build_shadow_replay(selected_tool=selected_tool, plan=plan)
        if shadow_replay.get("available", False):
            self._append_bounded_ledger_event(
                "shadow_replay_events",
                {
                    "timestamp": _utc_now(),
                    "phase": str(plan.get("phase", "tool_outcome")),
                    "client_id": str(plan.get("client_id", "")),
                    "selected_tool": selected_tool,
                    "shadow_replay": shadow_replay,
                },
            )
        self._save_routing_stats()

        preflight = plan.get("execution_policy", {}).get("recipe_preflight", {})
        policy_action = plan.get("execution_policy", {}).get("recommended_action", "proceed")
        governance_events = list((plan.get("governance") or {}).get("events", []))
        significant_effects = list(ablation.get("significant_effects", [])) if isinstance(ablation, dict) else []
        policy_learning_outcome = "positive" if outcome_positive else "negative"
        return {
            "selected_tool": selected_tool,
            "routing_candidates": selected_tools,
            "top_alternative_tool": top_alternative,
            "intent_signature": intent_signature,
            "recipe_memory_used": bool(recipe_attribution),
            "guard_memory_used": bool(guard_attribution),
            "context_summary_used": bool(summary_attribution),
            "counterfactual_without_recipe": (
                f"routing_probability_would_change_by_{_safe_float(cf_recipe.get('delta', 0.0)):.4f}"
                if cf_recipe else "no_recipe_memory_used"
            ),
            "counterfactual_without_guard": (
                f"routing_probability_would_change_by_{_safe_float(cf_guard.get('delta', 0.0)):.4f}"
                if cf_guard else "no_guard_memory_used"
            ),
            "counterfactual_without_summary": (
                "context_budget_would_change_without_summary"
                if summary_attribution else "no_summary_memory_used"
            ),
            "counterfactual_without_global_reliability": (
                f"routing_probability_would_change_by_{_safe_float(cf_global.get('delta', 0.0)):.4f}"
                if cf_global else "no_global_reliability_effect"
            ),
            "counterfactual_without_intent_reliability": (
                f"routing_probability_would_change_by_{_safe_float(cf_intent.get('delta', 0.0)):.4f}"
                if cf_intent else "no_intent_reliability_effect"
            ),
            "routing_score_observed": round(_safe_float(selected_score.get("final_score", 0.0) if selected_score else 0.0), 4),
            "routing_score_components": dict(selected_score.get("score_components", {}) if selected_score else {}),
            "execution_policy_action": policy_action,
            "recipe_preflight_decision": preflight.get("decision", "not_evaluated"),
            "recipe_preflight_reason": preflight.get("reason", ""),
            "blocked": blocked,
            "success": success,
            "guard_id": guard_id,
            "counterfactual_action": counterfactual,
            "policy_learning_outcome": policy_learning_outcome,
            "significant_causal_effects": significant_effects,
            "governance_event_count": len(governance_events),
            "shadow_replay": shadow_replay,
            "causal_ablation": ablation,
        }

    def build_policy_evaluator_view(
        self,
        *,
        client_id: str,
        query: str,
        tool_catalog: list[dict[str, Any]],
        context_engine: Any,
        tem: Any,
        dry_run: bool = True,
        feature_mask: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        feature_mask = _normalize_feature_mask(feature_mask)
        tool_names = [str(tool.get("name", "")) for tool in tool_catalog if str(tool.get("name", "")).strip()]
        if dry_run:
            memory = context_engine.get_memory(client_id)
            routing = self._route_tools(
                query,
                tool_names,
                tool_catalog or [],
                tem,
                client_id=client_id,
                feature_mask=feature_mask,
            )
            context_tool_names = routing["selected_tools"] or tool_names
            snapshot = tem.get_context_snapshot(query, context_tool_names)
            recipes = snapshot.get("recipes", [])
            guards = snapshot.get("guards", [])
            retention = self._build_retention_view(memory)
            forgetting = self._build_forgetting_view(memory, recipes, guards)
            attribution = self._build_chat_attribution(memory, recipes, guards, routing)
            plan = self._finalize_plan_snapshot(
                {
                    "timestamp": _utc_now(),
                    "schema_version": MEMORY_PLANE_SCHEMA_VERSION,
                    "phase": "policy_evaluation_dry_run",
                    "client_id": client_id,
                    "query": query,
                    "routing": {
                        **routing,
                        "context_tool_names": context_tool_names,
                        "relevant_tools": snapshot.get("relevant_tools", context_tool_names),
                    },
                    "retention": retention,
                    "forgetting": forgetting,
                    "governance": {
                        "policy_executed": False,
                        "policy_version": str(forgetting.get("policy_version", "memory_governance_v2")),
                        "reason": "dry_run_evaluation",
                        "events": [],
                    },
                    "attribution": [asdict(item) for item in attribution],
                    "causal_ablation": self._build_ablation_report(routing, attribution),
                }
            )
        else:
            plan = self.build_chat_memory_plan(
                client_id=client_id,
                query=query,
                tool_names=tool_names,
                tool_catalog=tool_catalog,
                context_engine=context_engine,
                tem=tem,
            )
        routing = dict(plan.get("routing", {}))
        ablation = dict(plan.get("causal_ablation", {}))
        recommended_tools = [str(name) for name in routing.get("selected_tools", [])]
        scores = list(routing.get("scores", []))
        return {
            "query": query,
            "client_id": client_id,
            "router_type": routing.get("router_type", "unknown"),
            "intent_signature": routing.get("intent_signature", ""),
            "recommended_tools": recommended_tools,
            "top_score": _safe_float(scores[0].get("final_score", 0.0), 0.0) if scores else 0.0,
            "candidate_count": len(scores),
            "routing_scores": scores,
            "ablation": ablation,
            "attribution": list(plan.get("attribution", [])),
            "governance": dict(plan.get("governance", {})),
            "dry_run": dry_run,
            "feature_mask": dict(feature_mask),
            "router_training_state": routing.get("router_training_state", {}),
            "evaluation_ready": bool(routing.get("evaluation_ready", False)),
            "policy_learning_ready": bool(routing.get("policy_learning_ready", False)),
        }

    def rollback_recent_governance(self, tem: Any, reason: str = "manual_recovery_check") -> dict[str, Any]:
        self._ensure_ledger_shape()
        events = list(self.routing_stats.get("governance_events", []))
        recent = events[-FORGETTING_ROLLBACK_MAX_ITEMS:]
        recipe_ids = [str(item.get("item_id", "")) for item in recent if item.get("kind") == "recipe" and item.get("action") in {"candidate_retire", "suppress_from_retrieval"}]
        guard_ids = [str(item.get("item_id", "")) for item in recent if item.get("kind") == "guard" and item.get("action") in {"candidate_retire", "suppress_from_precheck"}]
        recipe_result = tem.recipes.rollback_governance(recipe_ids=recipe_ids, reason=reason)
        guard_result = tem.guards.rollback_governance(guard_ids=guard_ids, reason=reason)
        rollback_event = self._normalize_rollback_event(
            {
                "timestamp": _utc_now(),
                "phase": "manual_recovery",
                "reason": reason,
                "recipe_result": recipe_result,
                "guard_result": guard_result,
            }
        )
        self._append_bounded_ledger_event("rollback_events", rollback_event)
        self._save_routing_stats()
        return {
            "ok": True,
            "restored_recipes": recipe_result,
            "restored_guards": guard_result,
            "rollback_event": rollback_event,
        }

    def _remember(self, snapshot: dict[str, Any]) -> None:
        self.last_snapshot = snapshot

    def _append_trace(self, trace: dict[str, Any]) -> None:
        try:
            with open(MEMORY_PLANE_TRACE_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(trace, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist memory plane trace: %s", exc)


memory_control_plane = MemoryControlPlane()


def reload_memory_plane_parameters() -> dict[str, Any]:
    return memory_control_plane.reload_parameters()


def reset_memory_plane_runtime(*, clear_traces: bool = False) -> dict[str, Any]:
    return memory_control_plane.reset_runtime_state(clear_traces=clear_traces)
