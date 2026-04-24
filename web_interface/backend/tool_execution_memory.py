"""Tool Execution Memory for MCP Mirror."""

import json
import hashlib
import logging
import math
import random
import re
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from probabilistic_params import load_required_params

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
RECIPES_DIR = ARTIFACTS_DIR / "recipes"
GUARDS_DIR = ARTIFACTS_DIR / "guards"
MEMORY_DIR = ARTIFACTS_DIR / "memory"
CENTROIDS_PATH = ARTIFACTS_DIR / "error_centroids.json"
TEM_TRACE_PATH = MEMORY_DIR / "tem_decisions.jsonl"
RECIPES_DIR.mkdir(parents=True, exist_ok=True)
GUARDS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

_TEM_PARAM_KEYS = [
    "HASH_TRUNCATE_LEN",
    "RESULT_SUMMARY_MAX_LEN",
    "CONTEXT_HINT_MAX_LEN",
    "RECIPE_HINT_MAX_LEN",
    "RECIPE_MIN_PROMOTION_SUCCESSES",
    "RECIPE_MAX_ALLOWED_FAILURE_RATE",
    "RECIPE_MIN_SCHEMA_CONSISTENCY",
    "RECIPE_MAX_CONTAMINATION_RISK",
    "RECIPE_PROBATION_RETRIEVAL_PENALTY",
    "RECIPE_QUALITY_EVIDENCE_SCALE",
    "RECIPE_FAILURE_SCHEMA_MATCH_THRESHOLD",
    "RECIPE_PREFLIGHT_MIN_VERIFICATIONS",
    "RECIPE_PREFLIGHT_MIN_VERIFICATION_RATE",
    "RECIPE_PREFLIGHT_MIN_SUCCESS_RATE",
    "RECIPE_PREFLIGHT_MIN_SCHEMA_SIMILARITY",
    "RECIPE_PREFLIGHT_MIN_QUALITY",
    "RECIPE_MAX_CHAIN_LENGTH",
    "RECIPE_MAX_STEP_GAP_SECONDS",
    "RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN",
    "ARG_VALUE_PREVIEW_LEN",
    "GUARD_CONTEXT_MAX_ITEMS",
    "RECIPE_MATCH_MAX_RESULTS",
    "RECIPE_CONTEXT_MAX_ITEMS",
    "RECIPE_LIFECYCLE_EVENT_MAX_ITEMS",
    "GUARD_LIFECYCLE_EVENT_MAX_ITEMS",
    "TOP_STATS_LIMIT",
    "NGRAM_SIZE",
    "CENTROID_LEARNING_RATE",
    "EVIDENCE_HALF_LIFE_DAYS",
    "BAYESIAN_PRIOR_ALPHA",
    "BAYESIAN_PRIOR_BETA",
    "BAYESIAN_BLOCK_CONFIDENCE",
    "DANGER_THRESHOLD",
    "DYNAMIC_THRESHOLD_STD_MULTIPLIER",
    "CENTROID_UPDATE_MIN_CONFIDENCE",
    "CENTROID_UPDATE_MIN_MARGIN",
    "NGRAM_NORM_EPSILON",
    "CENTROID_SPARSIFY_EPSILON",
    "A5_TOP_K_SUGGESTIONS",
    "A5_MIN_SCHEMA_SIMILARITY",
    "A5_PARAM_PREVIEW_MAX_ITEMS",
    "GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY",
    "GUARD_GENERALIZATION_MIN_RISK_OVERLAP",
    "BETACF_MAX_ITER",
    "BETACF_EPSILON",
    "BETACF_TINY",
    "BETA_LOG_EPSILON",
]


def _apply_tem_params(params: dict[str, Any]):
    global HASH_TRUNCATE_LEN
    global RESULT_SUMMARY_MAX_LEN
    global CONTEXT_HINT_MAX_LEN
    global RECIPE_HINT_MAX_LEN
    global RECIPE_MIN_PROMOTION_SUCCESSES
    global RECIPE_MAX_ALLOWED_FAILURE_RATE
    global RECIPE_MIN_SCHEMA_CONSISTENCY
    global RECIPE_MAX_CONTAMINATION_RISK
    global RECIPE_PROBATION_RETRIEVAL_PENALTY
    global RECIPE_QUALITY_EVIDENCE_SCALE
    global RECIPE_FAILURE_SCHEMA_MATCH_THRESHOLD
    global RECIPE_PREFLIGHT_MIN_VERIFICATIONS
    global RECIPE_PREFLIGHT_MIN_VERIFICATION_RATE
    global RECIPE_PREFLIGHT_MIN_SUCCESS_RATE
    global RECIPE_PREFLIGHT_MIN_SCHEMA_SIMILARITY
    global RECIPE_PREFLIGHT_MIN_QUALITY
    global RECIPE_MAX_CHAIN_LENGTH
    global RECIPE_MAX_STEP_GAP_SECONDS
    global RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN
    global ARG_VALUE_PREVIEW_LEN
    global GUARD_CONTEXT_MAX_ITEMS
    global RECIPE_MATCH_MAX_RESULTS
    global RECIPE_CONTEXT_MAX_ITEMS
    global RECIPE_LIFECYCLE_EVENT_MAX_ITEMS
    global GUARD_LIFECYCLE_EVENT_MAX_ITEMS
    global TOP_STATS_LIMIT
    global NGRAM_SIZE
    global CENTROID_LEARNING_RATE
    global EVIDENCE_HALF_LIFE_DAYS
    global BAYESIAN_PRIOR_ALPHA
    global BAYESIAN_PRIOR_BETA
    global BAYESIAN_BLOCK_CONFIDENCE
    global DANGER_THRESHOLD
    global DYNAMIC_THRESHOLD_STD_MULTIPLIER
    global CENTROID_UPDATE_MIN_CONFIDENCE
    global CENTROID_UPDATE_MIN_MARGIN
    global NGRAM_NORM_EPSILON
    global CENTROID_SPARSIFY_EPSILON
    global A5_TOP_K_SUGGESTIONS
    global A5_MIN_SCHEMA_SIMILARITY
    global A5_PARAM_PREVIEW_MAX_ITEMS
    global GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY
    global GUARD_GENERALIZATION_MIN_RISK_OVERLAP
    global BETACF_MAX_ITER
    global BETACF_EPSILON
    global BETACF_TINY
    global BETA_LOG_EPSILON

    HASH_TRUNCATE_LEN = int(params["HASH_TRUNCATE_LEN"])
    RESULT_SUMMARY_MAX_LEN = int(params["RESULT_SUMMARY_MAX_LEN"])
    CONTEXT_HINT_MAX_LEN = int(params["CONTEXT_HINT_MAX_LEN"])
    RECIPE_HINT_MAX_LEN = int(params["RECIPE_HINT_MAX_LEN"])
    RECIPE_MIN_PROMOTION_SUCCESSES = int(params["RECIPE_MIN_PROMOTION_SUCCESSES"])
    RECIPE_MAX_ALLOWED_FAILURE_RATE = float(params["RECIPE_MAX_ALLOWED_FAILURE_RATE"])
    RECIPE_MIN_SCHEMA_CONSISTENCY = float(params["RECIPE_MIN_SCHEMA_CONSISTENCY"])
    RECIPE_MAX_CONTAMINATION_RISK = float(params["RECIPE_MAX_CONTAMINATION_RISK"])
    RECIPE_PROBATION_RETRIEVAL_PENALTY = float(params["RECIPE_PROBATION_RETRIEVAL_PENALTY"])
    RECIPE_QUALITY_EVIDENCE_SCALE = float(params["RECIPE_QUALITY_EVIDENCE_SCALE"])
    RECIPE_FAILURE_SCHEMA_MATCH_THRESHOLD = float(params["RECIPE_FAILURE_SCHEMA_MATCH_THRESHOLD"])
    RECIPE_PREFLIGHT_MIN_VERIFICATIONS = int(params["RECIPE_PREFLIGHT_MIN_VERIFICATIONS"])
    RECIPE_PREFLIGHT_MIN_VERIFICATION_RATE = float(params["RECIPE_PREFLIGHT_MIN_VERIFICATION_RATE"])
    RECIPE_PREFLIGHT_MIN_SUCCESS_RATE = float(params["RECIPE_PREFLIGHT_MIN_SUCCESS_RATE"])
    RECIPE_PREFLIGHT_MIN_SCHEMA_SIMILARITY = float(params["RECIPE_PREFLIGHT_MIN_SCHEMA_SIMILARITY"])
    RECIPE_PREFLIGHT_MIN_QUALITY = float(params["RECIPE_PREFLIGHT_MIN_QUALITY"])
    RECIPE_MAX_CHAIN_LENGTH = int(params["RECIPE_MAX_CHAIN_LENGTH"])
    RECIPE_MAX_STEP_GAP_SECONDS = float(params["RECIPE_MAX_STEP_GAP_SECONDS"])
    RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN = float(params["RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN"])
    ARG_VALUE_PREVIEW_LEN = int(params["ARG_VALUE_PREVIEW_LEN"])
    GUARD_CONTEXT_MAX_ITEMS = int(params["GUARD_CONTEXT_MAX_ITEMS"])
    RECIPE_MATCH_MAX_RESULTS = int(params["RECIPE_MATCH_MAX_RESULTS"])
    RECIPE_CONTEXT_MAX_ITEMS = int(params["RECIPE_CONTEXT_MAX_ITEMS"])
    RECIPE_LIFECYCLE_EVENT_MAX_ITEMS = int(params["RECIPE_LIFECYCLE_EVENT_MAX_ITEMS"])
    GUARD_LIFECYCLE_EVENT_MAX_ITEMS = int(params["GUARD_LIFECYCLE_EVENT_MAX_ITEMS"])
    TOP_STATS_LIMIT = int(params["TOP_STATS_LIMIT"])

    NGRAM_SIZE = int(params["NGRAM_SIZE"])
    CENTROID_LEARNING_RATE = float(params["CENTROID_LEARNING_RATE"])
    EVIDENCE_HALF_LIFE_DAYS = float(params["EVIDENCE_HALF_LIFE_DAYS"])
    BAYESIAN_PRIOR_ALPHA = float(params["BAYESIAN_PRIOR_ALPHA"])
    BAYESIAN_PRIOR_BETA = float(params["BAYESIAN_PRIOR_BETA"])
    BAYESIAN_BLOCK_CONFIDENCE = float(params["BAYESIAN_BLOCK_CONFIDENCE"])
    DANGER_THRESHOLD = float(params["DANGER_THRESHOLD"])
    DYNAMIC_THRESHOLD_STD_MULTIPLIER = float(params["DYNAMIC_THRESHOLD_STD_MULTIPLIER"])
    CENTROID_UPDATE_MIN_CONFIDENCE = float(params["CENTROID_UPDATE_MIN_CONFIDENCE"])
    CENTROID_UPDATE_MIN_MARGIN = float(params["CENTROID_UPDATE_MIN_MARGIN"])
    NGRAM_NORM_EPSILON = float(params["NGRAM_NORM_EPSILON"])
    CENTROID_SPARSIFY_EPSILON = float(params["CENTROID_SPARSIFY_EPSILON"])
    A5_TOP_K_SUGGESTIONS = int(params["A5_TOP_K_SUGGESTIONS"])
    A5_MIN_SCHEMA_SIMILARITY = float(params["A5_MIN_SCHEMA_SIMILARITY"])
    A5_PARAM_PREVIEW_MAX_ITEMS = int(params["A5_PARAM_PREVIEW_MAX_ITEMS"])
    GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY = float(
        params["GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY"]
    )
    GUARD_GENERALIZATION_MIN_RISK_OVERLAP = float(
        params["GUARD_GENERALIZATION_MIN_RISK_OVERLAP"]
    )
    BETACF_MAX_ITER = int(params["BETACF_MAX_ITER"])
    BETACF_EPSILON = float(params["BETACF_EPSILON"])
    BETACF_TINY = float(params["BETACF_TINY"])
    BETA_LOG_EPSILON = float(params["BETA_LOG_EPSILON"])


_apply_tem_params(load_required_params("tool_execution_memory", _TEM_PARAM_KEYS))

SUPPORTED_TEM_MODES = ("baseline", "recipe_only", "guard_only", "full_tem")
TEM_MODE_FLAGS: dict[str, dict[str, bool]] = {
    "baseline": {
        "enable_recipe_context": False,
        "enable_recipe_learning": False,
        "enable_guard_blocking": False,
        "enable_guard_learning": False,
    },
    "recipe_only": {
        "enable_recipe_context": True,
        "enable_recipe_learning": True,
        "enable_guard_blocking": False,
        "enable_guard_learning": False,
    },
    "guard_only": {
        "enable_recipe_context": False,
        "enable_recipe_learning": False,
        "enable_guard_blocking": True,
        "enable_guard_learning": True,
    },
    "full_tem": {
        "enable_recipe_context": True,
        "enable_recipe_learning": True,
        "enable_guard_blocking": True,
        "enable_guard_learning": True,
    },
}
DEFAULT_TEM_MODE = "full_tem"


def normalize_tem_mode(mode: Optional[str]) -> str:
    normalized = (mode or DEFAULT_TEM_MODE).strip().lower()
    if normalized not in TEM_MODE_FLAGS:
        supported = ", ".join(SUPPORTED_TEM_MODES)
        raise ValueError(f"Unsupported TEM mode: {mode!r}. Supported: {supported}")
    return normalized


class FailureCause(str, Enum):
    """Tool Execution Memory for MCP Mirror."""
    RESOURCE_NOT_FOUND = "resource_not_found"
    PERMISSION_DENIED = "permission_denied"
    INVALID_ARGUMENT = "invalid_argument"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    DEPENDENCY_MISSING = "dependency_missing"
    BUSINESS_LOGIC_ERROR = "business_logic_error"
    UNKNOWN = "unknown"


def ngram_vector(text: str, n: Optional[int] = None) -> dict[str, float]:
    """Tool Execution Memory for MCP Mirror."""
    if n is None:
        n = NGRAM_SIZE
    text = text.lower().strip()
    if len(text) < n:
        return {}
    freq: dict[str, float] = {}
    for i in range(len(text) - n + 1):
        gram = text[i:i + n]
        freq[gram] = freq.get(gram, 0) + 1.0
    norm = math.sqrt(sum(v * v for v in freq.values()))
    if norm < NGRAM_NORM_EPSILON:
        return {}
    return {k: v / norm for k, v in freq.items()}


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Tool Execution Memory for MCP Mirror."""
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return sum(v * longer.get(k, 0.0) for k, v in shorter.items())


def _normalize_text_tokens(text: str) -> set[str]:
    return {tok for tok in re.split(r"[^a-z0-9_]+", text.lower()) if tok}


def _tool_name_tokens(tool_name: str) -> set[str]:
    return {tok for tok in re.split(r"[_\W]+", tool_name.lower()) if tok}


def _schema_signature_items(arguments: dict) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key in sorted(arguments.keys()):
        items.append({
            "key": str(key),
            "type": type(arguments[key]).__name__,
        })
    return items


def _schema_signature_text(arguments: dict) -> str:
    return "|".join(
        f"{item['key']}:{item['type']}"
        for item in _schema_signature_items(arguments)
    )


def _risk_tags_for_argument(key: str, value: Any) -> set[str]:
    tags: set[str] = set()
    key_lower = str(key).lower()
    value_text = str(value).lower()

    if key_lower in {"path", "file", "filepath", "directory", "dir"}:
        tags.add("filesystem_target")
        if ".." in value_text:
            tags.add("path_traversal")
        if value_text.startswith("/") or re.match(r"^[a-z]:[\\/]", value_text):
            tags.add("absolute_path")
        if "\\windows\\" in value_text or "/etc/" in value_text:
            tags.add("system_path")

    if key_lower in {"query", "pattern", "search", "keyword"}:
        tags.add("search_like")

    if key_lower in {"content", "text", "value"} and len(str(value)) > ARG_VALUE_PREVIEW_LEN:
        tags.add("large_payload")

    if key_lower in {"limit", "max_results", "top_k"}:
        tags.add("bounded_query")

    if isinstance(value, str) and not value.strip():
        tags.add("empty_string")
    if value in (None, "", [], {}):
        tags.add("missing_like_value")
    return tags


def _risk_tags_from_arguments(arguments: dict) -> list[str]:
    tags: set[str] = set()
    for key, value in arguments.items():
        tags |= _risk_tags_for_argument(key, value)
    return sorted(tags)


def _risk_overlap_score(a: list[str], b: list[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def infer_relevant_tool_names(task_description: str, candidate_tool_names: list[str]) -> list[str]:
    task_lower = task_description.lower()
    task_tokens = _normalize_text_tokens(task_description)
    scored: list[tuple[int, str]] = []
    for tool_name in candidate_tool_names:
        tokens = _tool_name_tokens(tool_name)
        overlap = len(tokens & task_tokens)
        exact = int(tool_name.lower() in task_lower)
        if exact or overlap:
            scored.append((exact * 100 + overlap, tool_name))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [tool_name for _, tool_name in scored]


def _iso_utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()



_SEED_TEXTS: dict[str, str] = {
    "resource_not_found":
        "resource not found file missing no such file path does not exist",
    "permission_denied":
        "permission denied forbidden access denied unauthorized",
    "invalid_argument":
        "invalid argument format type error value error validation failed",
    "timeout":
        "timeout timed out deadline exceeded connection timed out",
    "rate_limit":
        "rate limit too many requests 429 throttle quota exceeded",
    "server_error":
        "server error 500 internal server error service unavailable 503",
    "network_error":
        "network error connection refused dns resolution failed socket unreachable",
    "dependency_missing":
        "dependency missing module not found import error not installed",
    "business_logic_error":
        "business logic error business rule violation logic validation failed",
}


class SemanticErrorClassifier:
    """Tool Execution Memory for MCP Mirror."""

    def __init__(self):
        self.centroids: dict[str, dict[str, float]] = {}
        self._observation_counts: dict[str, int] = {}
        if not self._load():
            self._init_seed_centroids()

    def _init_seed_centroids(self):
        for cause_val, seed in _SEED_TEXTS.items():
            self.centroids[cause_val] = ngram_vector(seed)
            self._observation_counts[cause_val] = 0

    def _inter_centroid_stats(self) -> tuple[float, float]:
        """Tool Execution Memory for MCP Mirror."""
        causes = list(self.centroids.keys())
        if len(causes) < 2:
            return 0.0, 0.0
        sims: list[float] = []
        for i in range(len(causes)):
            for j in range(i + 1, len(causes)):
                s = cosine_similarity(
                    self.centroids[causes[i]], self.centroids[causes[j]])
                sims.append(s)
        mean = sum(sims) / len(sims)
        var = sum((s - mean) ** 2 for s in sims) / len(sims)
        return mean, math.sqrt(var)

    def dynamic_threshold(self) -> float:
        """Tool Execution Memory for MCP Mirror."""
        mu, sigma = self._inter_centroid_stats()
        return mu + DYNAMIC_THRESHOLD_STD_MULTIPLIER * sigma

    def classify(self, error_type: str, error_message: str) -> tuple[FailureCause, float]:
        """Tool Execution Memory for MCP Mirror."""
        text = f"{error_type} {error_message}"
        vec = ngram_vector(text)
        if not vec:
            return FailureCause.UNKNOWN, 0.0

        best_cause = FailureCause.UNKNOWN
        best_sim = -1.0
        second_best_sim = -1.0
        threshold = self.dynamic_threshold()

        for cause_val, centroid in self.centroids.items():
            sim = cosine_similarity(vec, centroid)
            if sim > best_sim:
                second_best_sim = best_sim
                best_sim = sim
                best_cause = FailureCause._value2member_map_.get(cause_val, FailureCause.UNKNOWN)
            elif sim > second_best_sim:
                second_best_sim = sim

        if best_sim < threshold:
            return FailureCause.UNKNOWN, best_sim

        margin = best_sim - max(second_best_sim, 0.0)
        if (
            best_sim >= CENTROID_UPDATE_MIN_CONFIDENCE
            and margin >= CENTROID_UPDATE_MIN_MARGIN
        ):
            self._update_centroid(best_cause.value, vec)
        return best_cause, best_sim

    def _update_centroid(self, cause_val: str, vec: dict[str, float]):
        """Tool Execution Memory for MCP Mirror."""
        centroid = self.centroids.get(cause_val, {})
        lr = CENTROID_LEARNING_RATE
        new_centroid: dict[str, float] = {}
        for k in set(centroid) | set(vec):
            new_centroid[k] = (1.0 - lr) * centroid.get(k, 0.0) + lr * vec.get(k, 0.0)
        norm = math.sqrt(sum(v * v for v in new_centroid.values()))
        if norm > NGRAM_NORM_EPSILON:
            self.centroids[cause_val] = {
                k: v / norm
                for k, v in new_centroid.items()
                if abs(v / norm) > CENTROID_SPARSIFY_EPSILON
            }
        self._observation_counts[cause_val] = self._observation_counts.get(cause_val, 0) + 1
        self._save()

    def _save(self):
        try:
            data = {
                "centroids": {k: dict(v) for k, v in self.centroids.items()},
                "observation_counts": self._observation_counts,
            }
            with open(CENTROIDS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save semantic error centroids: {e}")

    def _load(self) -> bool:
        try:
            if not CENTROIDS_PATH.exists():
                return False
            with open(CENTROIDS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.centroids = data.get("centroids", {})
            self._observation_counts = data.get("observation_counts", {})
            return bool(self.centroids)
        except Exception:
            return False


_error_classifier = SemanticErrorClassifier()


def classify_failure_cause(error_type: str, error_message: str) -> FailureCause:
    """Tool Execution Memory for MCP Mirror."""
    msg = f"{error_type} {error_message}".lower()
    if any(token in msg for token in ["access denied", "outside allowed directories", "forbidden", "unauthorized"]):
        return FailureCause.PERMISSION_DENIED
    if any(token in msg for token in ["invalid input", "validation error", "invalid arguments", "missing required argument"]):
        return FailureCause.INVALID_ARGUMENT
    if any(token in msg for token in ["enoent", "no such file or directory", "not found", "does not exist"]):
        return FailureCause.RESOURCE_NOT_FOUND
    if any(token in msg for token in ["429", "rate limit", "too many requests", "throttle", "quota exceeded"]):
        return FailureCause.RATE_LIMIT
    if any(token in msg for token in ["timed out", "timeout", "deadline exceeded"]):
        return FailureCause.TIMEOUT
    if any(token in msg for token in ["connection issue", "connection refused", "dns", "network"]):
        return FailureCause.NETWORK_ERROR
    cause, _ = _error_classifier.classify(error_type, error_message)
    return cause


def _betacf(a: float, b: float, x: float,
            max_iter: Optional[int] = None, eps: Optional[float] = None) -> float:
    """Tool Execution Memory for MCP Mirror."""
    iter_cap = BETACF_MAX_ITER if max_iter is None else max_iter
    convergence_eps = BETACF_EPSILON if eps is None else eps
    tiny = BETACF_TINY
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0

    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d

    for m in range(1, iter_cap + 1):
        m2 = 2 * m

        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c

        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta

        if abs(delta - 1.0) < convergence_eps:
            return h

    logger.warning(f"_betacf did not converge: a={a}, b={b}, x={x}")
    return h


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Tool Execution Memory for MCP Mirror."""
    if a <= 0 or b <= 0:
        raise ValueError(f"a ({a}) and b ({b}) must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - regularized_incomplete_beta(1.0 - x, b, a)

    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(
        a * math.log(max(x, BETA_LOG_EPSILON))
        + b * math.log(max(1.0 - x, BETA_LOG_EPSILON))
        - log_beta
    ) / a

    return front * _betacf(a, b, x)


def exponential_decay_factor(age_days: float,
                             half_life: float = EVIDENCE_HALF_LIFE_DAYS) -> float:
    """Tool Execution Memory for MCP Mirror."""
    if age_days <= 0 or half_life <= 0:
        return 1.0
    return 2.0 ** (-age_days / half_life)


def _age_days_from_iso(iso_str: str) -> float:
    """Tool Execution Memory for MCP Mirror."""
    if not iso_str:
        return 0.0
    try:
        ts = datetime.fromisoformat(iso_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(tz=timezone.utc) - ts
        return max(delta.total_seconds() / 86400.0, 0.0)
    except (ValueError, TypeError):
        return 0.0


@dataclass
class ToolStep:
    """Tool Execution Memory for MCP Mirror."""
    tool_name: str
    arguments: dict
    result_summary: str
    success: bool
    latency_ms: float = 0.0
    server_name: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())


@dataclass
class ToolRecipe:
    """Tool Execution Memory for MCP Mirror."""
    id: str
    name: str
    description: str
    preconditions: list[str]
    steps: list[dict]
    parameter_schema: dict = field(default_factory=dict)
    success_count: int = 1
    fail_count: int = 0
    avg_latency_ms: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    last_used_at: str = ""
    tags: list[str] = field(default_factory=list)
    evidence_count: int = 1
    schema_consistency: float = 1.0
    contamination_risk: float = 0.0
    promotion_state: str = "probation"
    quality_score: float = 0.0
    last_failed_at: str = ""
    retired_at: str = ""
    suppression_reason: str = ""
    source_task_hint: str = ""
    task_vector_text: str = ""
    governance_state: str = "active"
    governance_reason: str = ""
    governance_updated_at: str = ""
    retrieval_count: int = 0
    verified_success_count: int = 0
    verified_fail_count: int = 0
    last_verified_at: str = ""
    version: int = 1
    parent_recipe_id: str = ""
    schema_drift_score: float = 0.0
    transfer_success_count: int = 0
    transfer_fail_count: int = 0
    lifecycle_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def freshness(self) -> float:
        """Tool Execution Memory for MCP Mirror."""
        ref = self.last_used_at or self.created_at
        return exponential_decay_factor(_age_days_from_iso(ref))

    @property
    def failure_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.fail_count / total if total > 0 else 0.0

    @property
    def is_retrievable(self) -> bool:
        return self.promotion_state in {"promoted", "probation"} and self.governance_state == "active"

    @property
    def verification_rate(self) -> float:
        total = self.verified_success_count + self.verified_fail_count
        return self.verified_success_count / total if total > 0 else 0.0

    @property
    def transfer_success_rate(self) -> float:
        total = self.transfer_success_count + self.transfer_fail_count
        return self.transfer_success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["success_rate"] = round(self.success_rate, 3)
        d["failure_rate"] = round(self.failure_rate, 3)
        d["freshness"] = round(self.freshness, 3)
        d["is_retrievable"] = self.is_retrievable
        d["is_stale"] = self.freshness < 0.1
        d["verification_rate"] = round(self.verification_rate, 3)
        d["program_memory_type"] = "procedural_tool_recipe"
        d["verification_total"] = self.verified_success_count + self.verified_fail_count
        d["verifiable"] = bool(self.steps and self.parameter_schema)
        d["transfer_success_rate"] = round(self.transfer_success_rate, 3)
        d["lineage"] = {
            "recipe_id": self.id,
            "version": self.version,
            "parent_recipe_id": self.parent_recipe_id,
            "current_state": self.governance_state,
            "promotion_state": self.promotion_state,
            "last_updated_at": self.governance_updated_at or self.last_used_at or self.created_at,
            "event_count": len(self.lifecycle_events),
        }
        d["quality_gate"] = {
            "quality_score": round(self.quality_score, 3),
            "schema_consistency": round(self.schema_consistency, 3),
            "schema_drift_score": round(self.schema_drift_score, 3),
            "contamination_risk": round(self.contamination_risk, 3),
            "verification_rate": round(self.verification_rate, 3),
            "verification_total": self.verified_success_count + self.verified_fail_count,
            "transfer_success_rate": round(self.transfer_success_rate, 3),
            "promotion_state": self.promotion_state,
            "governance_state": self.governance_state,
            "gate_reason": self.governance_reason or self.suppression_reason,
        }
        d["quality_evidence"] = {
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "evidence_count": self.evidence_count,
            "schema_consistency": round(self.schema_consistency, 3),
            "contamination_risk": round(self.contamination_risk, 3),
            "schema_drift_score": round(self.schema_drift_score, 3),
            "transfer_success_count": self.transfer_success_count,
            "transfer_fail_count": self.transfer_fail_count,
            "promotion_state": self.promotion_state,
            "governance_state": self.governance_state,
        }
        d["lifecycle_events"] = list(self.lifecycle_events[-RECIPE_LIFECYCLE_EVENT_MAX_ITEMS:])
        return d


@dataclass
class Guard:
    """Tool Execution Memory for MCP Mirror."""
    id: str
    tool_name: str
    server_name: str
    error_type: str
    error_message: str
    argument_pattern: dict
    argument_value_hash: str
    match_level: str = "exact"
    match_signature: str = ""
    schema_signature: list[dict[str, str]] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
    generalization_confidence: float = 1.0
    context_hint: str = ""
    alternative_suggestion: str = ""
    failure_cause: str = FailureCause.UNKNOWN.value
    block_count: int = 0
    alpha: float = BAYESIAN_PRIOR_ALPHA
    beta_param: float = BAYESIAN_PRIOR_BETA
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    last_triggered_at: str = ""
    governance_state: str = "active"
    governance_reason: str = ""
    governance_updated_at: str = ""
    avoided_count: int = 0
    last_counterfactual_suggestion: str = ""
    success_evidence_count: int = 0
    lifecycle_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def freshness(self) -> float:
        ref = self.last_triggered_at or self.created_at
        return exponential_decay_factor(_age_days_from_iso(ref))

    @property
    def effective_alpha(self) -> float:
        """Tool Execution Memory for MCP Mirror."""
        decay = self.freshness
        return BAYESIAN_PRIOR_ALPHA + (self.alpha - BAYESIAN_PRIOR_ALPHA) * decay

    @property
    def effective_beta(self) -> float:
        """Tool Execution Memory for MCP Mirror."""
        decay = self.freshness
        return BAYESIAN_PRIOR_BETA + (self.beta_param - BAYESIAN_PRIOR_BETA) * decay

    @property
    def posterior_failure_prob(self) -> float:
        """Tool Execution Memory for MCP Mirror."""
        a_eff = self.effective_alpha
        b_eff = self.effective_beta
        return 1.0 - regularized_incomplete_beta(DANGER_THRESHOLD, a_eff, b_eff)

    def should_block(self) -> bool:
        """Tool Execution Memory for MCP Mirror."""
        return self.posterior_failure_prob > BAYESIAN_BLOCK_CONFIDENCE

    def explanation(self) -> str:
        level = self.match_level or "exact"
        risk_text = ", ".join(self.risk_tags[:3]) if self.risk_tags else "none"
        return (
            f"guard={level}, fail_prob={self.posterior_failure_prob:.1%}, "
            f"risk_tags={risk_text}, gen_conf={self.generalization_confidence:.2f}"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posterior_failure_prob"] = round(self.posterior_failure_prob, 3)
        d["freshness"] = round(self.freshness, 3)
        d["counterfactual_memory_type"] = "failure_guard"
        d["guard_evidence"] = {
            "posterior_failure_prob": round(self.posterior_failure_prob, 3),
            "effective_alpha": round(self.effective_alpha, 3),
            "effective_beta": round(self.effective_beta, 3),
            "block_count": self.block_count,
            "avoided_count": self.avoided_count,
            "success_evidence_count": self.success_evidence_count,
            "false_block_risk_proxy": round(
                self.success_evidence_count / max(self.block_count + self.success_evidence_count, 1),
                3,
            ),
            "governance_state": self.governance_state,
            "governance_reason": self.governance_reason,
            "match_level": self.match_level,
            "risk_tags": list(self.risk_tags),
        }
        d["counterfactual"] = {
            "avoided_count": self.avoided_count,
            "suggestion": self.alternative_suggestion,
            "last_suggestion": self.last_counterfactual_suggestion,
            "match_level": self.match_level,
            "generalization_confidence": round(self.generalization_confidence, 3),
        }
        d["lifecycle_events"] = list(self.lifecycle_events[-GUARD_LIFECYCLE_EVENT_MAX_ITEMS:])
        return d


class RecipeStore:
    """Tool Execution Memory for MCP Mirror."""

    def __init__(self):
        self.recipes: dict[str, ToolRecipe] = {}
        self._load_all()

    def _load_all(self):
        known = set(ToolRecipe.__dataclass_fields__)
        for f in RECIPES_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                recipe = ToolRecipe(**{k: v for k, v in data.items() if k in known})
                self._refresh_quality_state(recipe)
                self.recipes[recipe.id] = recipe
            except Exception as e:
                logger.warning(f"Failed to load ToolRecipe {f}: {e}")
        logger.info(f"RecipeStore loaded {len(self.recipes)} recipes")

    def _save(self, recipe: ToolRecipe):
        path = RECIPES_DIR / f"{recipe.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(recipe.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def _append_lifecycle_event(recipe: ToolRecipe, event_type: str, **payload: Any) -> None:
        event = {
            "timestamp": _iso_utc_now(),
            "event_type": event_type,
            "version": recipe.version,
            **payload,
        }
        recipe.lifecycle_events.append(event)
        if len(recipe.lifecycle_events) > RECIPE_LIFECYCLE_EVENT_MAX_ITEMS:
            recipe.lifecycle_events = recipe.lifecycle_events[-RECIPE_LIFECYCLE_EVENT_MAX_ITEMS:]

    @staticmethod
    def _bump_version_if_needed(recipe: ToolRecipe, *, schema_drift_changed: bool = False, governance_changed: bool = False) -> None:
        if schema_drift_changed or governance_changed:
            recipe.version += 1

    def import_snapshot(self, recipes: dict[str, ToolRecipe]) -> None:
        self.recipes = recipes

    @staticmethod
    def _build_parameter_schema(arguments: dict) -> dict:
        """Tool Execution Memory for MCP Mirror."""
        schema: dict[str, str] = {}
        for k, v in arguments.items():
            t = type(v).__name__
            if isinstance(v, str):
                schema[k] = f"str[{len(v)}]"
            elif isinstance(v, (int, float)):
                schema[k] = t
            elif isinstance(v, list):
                schema[k] = f"list[{len(v)}]"
            elif isinstance(v, dict):
                schema[k] = f"dict[{len(v)}]"
            else:
                schema[k] = t
        return schema

    @staticmethod
    def _schema_similarity(current_schema: dict, target_schema: dict) -> float:
        if not current_schema or not target_schema:
            return 0.0
        current_keys = set(current_schema.keys())
        target_keys = set(target_schema.keys())
        union = current_keys | target_keys
        if not union:
            return 0.0
        overlap = current_keys & target_keys
        if not overlap:
            return 0.0
        key_jaccard = len(overlap) / len(union)
        value_match = sum(
            1 for key in overlap if current_schema.get(key) == target_schema.get(key)
        ) / len(overlap)
        return math.sqrt(key_jaccard * value_match)

    @staticmethod
    def _chain_schema_consistency(steps: list[dict], merged_schema: dict) -> float:
        if not steps:
            return 0.0
        scores: list[float] = []
        for step in steps:
            step_schema = step.get("parameter_schema", {})
            if not step_schema:
                scores.append(1.0 if not merged_schema else 0.0)
                continue
            scores.append(RecipeStore._schema_similarity(step_schema, merged_schema))
        return sum(scores) / len(scores)

    @staticmethod
    def _task_chain_similarity(task_description: str, recipe_text: str) -> float:
        if not task_description.strip():
            return 1.0
        task_vec = ngram_vector(task_description)
        recipe_vec = ngram_vector(recipe_text)
        if not task_vec or not recipe_vec:
            return 0.0
        return cosine_similarity(task_vec, recipe_vec)

    @staticmethod
    def _task_similarity_to_recipe(task_description: str, recipe: ToolRecipe) -> float:
        recipe_text = recipe.task_vector_text or (
            f"{recipe.name} {recipe.description} {' '.join(recipe.tags)}"
        )
        return RecipeStore._task_chain_similarity(task_description, recipe_text)

    @staticmethod
    def _quality_from_evidence(recipe: ToolRecipe) -> float:
        evidence_weight = min(
            max(recipe.evidence_count, 0) / RECIPE_QUALITY_EVIDENCE_SCALE,
            1.0,
        )
        score = (
            recipe.success_rate
            * recipe.schema_consistency
            * (1.0 - recipe.contamination_risk)
            * evidence_weight
            * recipe.freshness
        )
        return max(0.0, min(score, 1.0))

    @staticmethod
    def _refresh_quality_state(recipe: ToolRecipe) -> None:
        recipe.evidence_count = max(recipe.success_count + recipe.fail_count, recipe.evidence_count)
        recipe.contamination_risk = max(0.0, min(recipe.contamination_risk, 1.0))
        recipe.schema_consistency = max(0.0, min(recipe.schema_consistency, 1.0))
        recipe.quality_score = round(RecipeStore._quality_from_evidence(recipe), 4)
        recipe.governance_updated_at = _iso_utc_now()

        if recipe.retired_at:
            recipe.promotion_state = "retired"
            if not recipe.suppression_reason:
                recipe.suppression_reason = "retired_recipe"
            recipe.governance_state = "retired"
            if not recipe.governance_reason:
                recipe.governance_reason = "retired_recipe"
            return

        if (
            recipe.failure_rate > RECIPE_MAX_ALLOWED_FAILURE_RATE
            or recipe.schema_consistency < RECIPE_MIN_SCHEMA_CONSISTENCY
            or recipe.contamination_risk > RECIPE_MAX_CONTAMINATION_RISK
        ):
            recipe.promotion_state = "quarantined"
            recipe.governance_state = "quarantined"
            if recipe.failure_rate > RECIPE_MAX_ALLOWED_FAILURE_RATE:
                recipe.suppression_reason = "failure_rate_exceeded"
                recipe.governance_reason = "failure_rate_exceeded"
            elif recipe.schema_consistency < RECIPE_MIN_SCHEMA_CONSISTENCY:
                recipe.suppression_reason = "schema_consistency_below_threshold"
                recipe.governance_reason = "schema_consistency_below_threshold"
            else:
                recipe.suppression_reason = "contamination_risk_exceeded"
                recipe.governance_reason = "contamination_risk_exceeded"
            return

        if recipe.success_count >= RECIPE_MIN_PROMOTION_SUCCESSES:
            recipe.promotion_state = "promoted"
            recipe.suppression_reason = ""
            recipe.governance_state = "active"
            recipe.governance_reason = "promoted_recipe"
            return

        recipe.promotion_state = "probation"
        recipe.suppression_reason = "awaiting_more_success_evidence"
        recipe.governance_state = "active"
        recipe.governance_reason = "awaiting_more_success_evidence"

    @staticmethod
    def _step_gap_seconds(previous: ToolStep, current: ToolStep) -> Optional[float]:
        prev_ts = getattr(previous, "timestamp", "")
        curr_ts = getattr(current, "timestamp", "")
        if not prev_ts or not curr_ts:
            return None
        try:
            prev_dt = datetime.fromisoformat(prev_ts)
            curr_dt = datetime.fromisoformat(curr_ts)
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=timezone.utc)
            if curr_dt.tzinfo is None:
                curr_dt = curr_dt.replace(tzinfo=timezone.utc)
            return max((curr_dt - prev_dt).total_seconds(), 0.0)
        except Exception:
            return None

    def prune_pending_steps(self, steps: list[ToolStep]) -> list[ToolStep]:
        kept: list[ToolStep] = []
        for step in steps:
            if kept:
                gap = self._step_gap_seconds(kept[-1], step)
                if gap is not None and gap > RECIPE_MAX_STEP_GAP_SECONDS:
                    kept = []
            kept.append(step)
            if len(kept) > RECIPE_MAX_CHAIN_LENGTH:
                kept = kept[-RECIPE_MAX_CHAIN_LENGTH:]
        return kept

    def extract_recipe(self, steps: list[ToolStep], task_description: str = "") -> Optional[ToolRecipe]:
        """Tool Execution Memory for MCP Mirror."""
        successful = self.prune_pending_steps([s for s in steps if s.success])
        if not successful:
            return None

        tool_chain = [s.tool_name for s in successful]
        server_names = sorted({s.server_name for s in successful if s.server_name})
        param_keys = sorted({k for s in successful for k in s.arguments.keys()})
        chain_key = f"{'|'.join(tool_chain)}||{'|'.join(server_names)}||{'|'.join(param_keys)}"
        recipe_id = hashlib.md5(chain_key.encode()).hexdigest()[:HASH_TRUNCATE_LEN]

        if recipe_id in self.recipes:
            existing = self.recipes[recipe_id]
            old_version = existing.version
            old_governance_state = existing.governance_state
            old_promotion_state = existing.promotion_state
            old_schema_drift = existing.schema_drift_score
            existing.success_count += 1
            existing.evidence_count = existing.success_count + existing.fail_count
            existing.last_used_at = datetime.now(tz=timezone.utc).isoformat()
            total_latency = sum(s.latency_ms for s in successful)
            existing.avg_latency_ms = round(
                (existing.avg_latency_ms * (existing.success_count - 1) + total_latency)
                / existing.success_count,
                1,
            )
            observed_schema: dict = {}
            for step in successful:
                observed_schema.update(self._build_parameter_schema(step.arguments))
            schema_similarity = self._schema_similarity(observed_schema, existing.parameter_schema)
            existing.schema_consistency = round(
                (
                    existing.schema_consistency * (existing.success_count - 1)
                    + schema_similarity
                )
                / existing.success_count,
                4,
            )
            existing.schema_drift_score = round(max(existing.schema_drift_score, 1.0 - schema_similarity), 4)
            task_similarity = self._task_similarity_to_recipe(task_description, existing)
            if task_similarity < RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN:
                existing.contamination_risk = min(
                    1.0,
                    existing.contamination_risk
                    + (RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN - task_similarity),
                )
                existing.suppression_reason = "task_chain_similarity_below_threshold"
                existing.transfer_fail_count += 1
            else:
                existing.transfer_success_count += 1
            self._refresh_quality_state(existing)
            schema_drift_changed = abs(existing.schema_drift_score - old_schema_drift) > 1e-9
            governance_changed = (
                existing.governance_state != old_governance_state
                or existing.promotion_state != old_promotion_state
            )
            self._bump_version_if_needed(
                existing,
                schema_drift_changed=schema_drift_changed,
                governance_changed=governance_changed,
            )
            self._append_lifecycle_event(
                existing,
                "reuse_success",
                previous_version=old_version,
                schema_similarity=round(schema_similarity, 4),
                schema_drift_score=round(existing.schema_drift_score, 4),
                task_similarity=round(task_similarity, 4),
                transfer_outcome="success" if task_similarity >= RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN else "fail",
                governance_state=existing.governance_state,
                promotion_state=existing.promotion_state,
            )
            self._save(existing)
            logger.info(
                "ToolRecipe updated: %s (success=%s, state=%s, quality=%.3f)",
                existing.name,
                existing.success_count,
                existing.promotion_state,
                existing.quality_score,
            )
            return existing

        name = " -> ".join(tool_chain)
        description = task_description or f"Tool chain: {name}"

        merged_schema: dict = {}
        recipe_steps = []
        for step in successful:
            step_schema = self._build_parameter_schema(step.arguments)
            merged_schema.update(step_schema)
            recipe_steps.append(
                {
                    "tool_name": step.tool_name,
                    "parameter_schema": step_schema,
                    "expected_result_hint": step.result_summary[:RECIPE_HINT_MAX_LEN],
                    "server_name": step.server_name,
                }
            )

        recipe_text = f"{name} {description} {' '.join(server_names)} {' '.join(param_keys)}"
        schema_consistency = self._chain_schema_consistency(recipe_steps, merged_schema)
        task_similarity = self._task_chain_similarity(task_description, recipe_text)
        contamination_risk = 0.0
        if task_similarity < RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN:
            contamination_risk = RECIPE_MIN_TASK_SIMILARITY_TO_CHAIN - task_similarity

        recipe = ToolRecipe(
            id=recipe_id,
            name=name,
            description=description,
            preconditions=server_names,
            steps=recipe_steps,
            parameter_schema=merged_schema,
            avg_latency_ms=round(sum(s.latency_ms for s in successful), 1),
            tags=tool_chain,
            evidence_count=1,
            schema_consistency=round(schema_consistency, 4),
            contamination_risk=round(contamination_risk, 4),
            source_task_hint=task_description[:CONTEXT_HINT_MAX_LEN],
            task_vector_text=recipe_text,
            schema_drift_score=round(1.0 - schema_consistency, 4),
        )
        self._refresh_quality_state(recipe)
        self._append_lifecycle_event(
            recipe,
            "created",
            parent_recipe_id=recipe.parent_recipe_id,
            governance_state=recipe.governance_state,
            promotion_state=recipe.promotion_state,
            schema_drift_score=round(recipe.schema_drift_score, 4),
            contamination_risk=round(recipe.contamination_risk, 4),
        )
        self.recipes[recipe.id] = recipe
        self._save(recipe)
        logger.info(
            "ToolRecipe learned: %s (id=%s, state=%s, quality=%.3f)",
            recipe.name,
            recipe.id,
            recipe.promotion_state,
            recipe.quality_score,
        )
        return recipe

    def match_recipes(self, task_description: str, tool_names: Optional[list[str]] = None) -> list[ToolRecipe]:
        """Tool Execution Memory for MCP Mirror."""
        if not self.recipes:
            return []

        query_text = task_description
        if tool_names:
            query_text = f"{query_text} {' '.join(tool_names)}"
        query_vec = ngram_vector(query_text)

        candidates: list[tuple[float, ToolRecipe]] = []
        for recipe in self.recipes.values():
            self._refresh_quality_state(recipe)
            if not recipe.is_retrievable:
                continue

            doc_text = f"{recipe.name} {recipe.description} {' '.join(recipe.tags)}"
            doc_vec = ngram_vector(doc_text)
            relevance = cosine_similarity(query_vec, doc_vec)
            quality = random.betavariate(
                recipe.success_count + BAYESIAN_PRIOR_ALPHA,
                recipe.fail_count + BAYESIAN_PRIOR_BETA,
            )
            freshness = recipe.freshness
            quality_gate = recipe.quality_score
            if recipe.promotion_state == "probation":
                quality_gate *= RECIPE_PROBATION_RETRIEVAL_PENALTY

            score = relevance * quality * freshness * quality_gate
            if score > 0:
                candidates.append((score, recipe))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [recipe for _, recipe in candidates[:RECIPE_MATCH_MAX_RESULTS]]

    def record_recipe_failure(
        self,
        recipe_id: str,
        failure_context: str = "",
        schema: Optional[dict] = None,
    ):
        """Tool Execution Memory for MCP Mirror."""
        if recipe_id in self.recipes:
            recipe = self.recipes[recipe_id]
            old_version = recipe.version
            old_governance_state = recipe.governance_state
            old_promotion_state = recipe.promotion_state
            recipe.fail_count += 1
            recipe.evidence_count = recipe.success_count + recipe.fail_count
            recipe.last_failed_at = datetime.now(tz=timezone.utc).isoformat()
            schema_similarity = None
            if schema:
                schema_similarity = self._schema_similarity(schema, recipe.parameter_schema)
                if schema_similarity >= RECIPE_FAILURE_SCHEMA_MATCH_THRESHOLD:
                    recipe.contamination_risk = min(
                        1.0,
                        recipe.contamination_risk + (1.0 - schema_similarity),
                    )
            if failure_context:
                recipe.suppression_reason = failure_context[:CONTEXT_HINT_MAX_LEN]
            self._refresh_quality_state(recipe)
            governance_changed = (
                recipe.governance_state != old_governance_state
                or recipe.promotion_state != old_promotion_state
            )
            self._bump_version_if_needed(recipe, governance_changed=governance_changed)
            self._append_lifecycle_event(
                recipe,
                "failure",
                previous_version=old_version,
                failure_context=failure_context[:CONTEXT_HINT_MAX_LEN],
                schema_similarity=round(schema_similarity, 4) if schema_similarity is not None else None,
                contamination_risk=round(recipe.contamination_risk, 4),
                governance_state=recipe.governance_state,
                promotion_state=recipe.promotion_state,
            )
            self._save(recipe)

    def apply_governance_actions(self, actions: list[dict[str, Any]]) -> dict[str, int]:
        changed = {"active": 0, "suppressed": 0, "retired": 0, "quarantined": 0}
        for action in actions:
            recipe_id = str(action.get("id", ""))
            if not recipe_id or recipe_id not in self.recipes:
                continue
            recipe = self.recipes[recipe_id]
            old_version = recipe.version
            old_governance_state = recipe.governance_state
            old_promotion_state = recipe.promotion_state
            decision = str(action.get("action", "retain"))
            reason = str(action.get("reason", "policy"))
            now_iso = _iso_utc_now()
            if decision == "candidate_retire":
                recipe.governance_state = "retired"
                recipe.governance_reason = reason
                recipe.retired_at = recipe.retired_at or now_iso
                recipe.suppression_reason = reason
                changed["retired"] += 1
            elif decision == "suppress_from_retrieval":
                recipe.governance_state = "suppressed"
                recipe.governance_reason = reason
                recipe.suppression_reason = reason
                changed["suppressed"] += 1
            elif decision == "retain":
                if recipe.promotion_state == "quarantined":
                    recipe.governance_state = "quarantined"
                    recipe.governance_reason = recipe.suppression_reason or reason
                    changed["quarantined"] += 1
                else:
                    recipe.governance_state = "active"
                    recipe.governance_reason = reason
                    if recipe.retired_at:
                        recipe.retired_at = ""
                    changed["active"] += 1
            recipe.governance_updated_at = now_iso
            self._refresh_quality_state(recipe)
            governance_changed = (
                recipe.governance_state != old_governance_state
                or recipe.promotion_state != old_promotion_state
            )
            self._bump_version_if_needed(recipe, governance_changed=governance_changed)
            self._append_lifecycle_event(
                recipe,
                "governance",
                previous_version=old_version,
                previous_state=old_governance_state,
                previous_promotion_state=old_promotion_state,
                action=decision,
                reason=reason,
                governance_state=recipe.governance_state,
                promotion_state=recipe.promotion_state,
            )
            self._save(recipe)
        return changed

    def rollback_governance(self, recipe_ids: Optional[list[str]] = None, reason: str = "policy_rollback") -> dict[str, Any]:
        targets = set(recipe_ids or [])
        changed: list[str] = []
        for recipe in self.recipes.values():
            if targets and recipe.id not in targets:
                continue
            if recipe.governance_state not in {"suppressed", "retired"} and not recipe.retired_at:
                continue
            old_version = recipe.version
            old_governance_state = recipe.governance_state
            old_promotion_state = recipe.promotion_state
            recipe.governance_state = "active"
            recipe.governance_reason = reason
            recipe.suppression_reason = ""
            recipe.retired_at = ""
            recipe.governance_updated_at = _iso_utc_now()
            self._refresh_quality_state(recipe)
            self._bump_version_if_needed(recipe, governance_changed=True)
            self._append_lifecycle_event(
                recipe,
                "rollback",
                previous_version=old_version,
                previous_state=old_governance_state,
                previous_promotion_state=old_promotion_state,
                reason=reason,
                governance_state=recipe.governance_state,
                promotion_state=recipe.promotion_state,
            )
            self._save(recipe)
            changed.append(recipe.id)
        return {"restored": len(changed), "ids": changed}

    def record_retrieval(self, recipe_ids: list[str]) -> None:
        now_iso = _iso_utc_now()
        for recipe_id in recipe_ids:
            recipe = self.recipes.get(recipe_id)
            if not recipe:
                continue
            recipe.retrieval_count += 1
            recipe.last_used_at = now_iso
            self._refresh_quality_state(recipe)
            self._append_lifecycle_event(
                recipe,
                "retrieval",
                retrieval_count=recipe.retrieval_count,
                governance_state=recipe.governance_state,
                promotion_state=recipe.promotion_state,
            )
            self._save(recipe)

    def record_verification_result(self, recipe_ids: list[str], success: bool) -> None:
        now_iso = _iso_utc_now()
        for recipe_id in recipe_ids:
            recipe = self.recipes.get(recipe_id)
            if not recipe:
                continue
            old_version = recipe.version
            old_governance_state = recipe.governance_state
            old_promotion_state = recipe.promotion_state
            if success:
                recipe.verified_success_count += 1
            else:
                recipe.verified_fail_count += 1
            recipe.last_verified_at = now_iso
            self._refresh_quality_state(recipe)
            governance_changed = (
                recipe.governance_state != old_governance_state
                or recipe.promotion_state != old_promotion_state
            )
            self._bump_version_if_needed(recipe, governance_changed=governance_changed)
            self._append_lifecycle_event(
                recipe,
                "verification",
                previous_version=old_version,
                verification_success=bool(success),
                verification_rate=round(recipe.verification_rate, 4),
                verification_total=recipe.verified_success_count + recipe.verified_fail_count,
                governance_state=recipe.governance_state,
                promotion_state=recipe.promotion_state,
            )
            self._save(recipe)

    def record_tool_failure(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        server_name: str = "",
        failure_context: str = "",
    ) -> list[str]:
        current_schema = self._build_parameter_schema(arguments or {})
        affected: list[str] = []
        for recipe in self.recipes.values():
            if tool_name not in {step.get("tool_name") for step in recipe.steps}:
                continue
            if server_name and server_name not in {step.get("server_name", "") for step in recipe.steps}:
                continue
            best_schema = 0.0
            for step in recipe.steps:
                if step.get("tool_name") != tool_name:
                    continue
                best_schema = max(
                    best_schema,
                    self._schema_similarity(current_schema, step.get("parameter_schema", {})),
                )
            if current_schema and best_schema < RECIPE_FAILURE_SCHEMA_MATCH_THRESHOLD:
                continue
            self.record_recipe_failure(
                recipe.id,
                failure_context=failure_context or "tool_failure_negative_evidence",
                schema=current_schema,
            )
            affected.append(recipe.id)
        return affected

    def verify_tool_call_against_recipes(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        server_name: str = "",
        task_description: str = "",
    ) -> dict[str, Any]:
        """Check a planned tool call against learned procedural memory."""
        current_schema = self._build_parameter_schema(arguments or {})
        candidates: list[dict[str, Any]] = []

        for recipe in self.recipes.values():
            self._refresh_quality_state(recipe)
            if not recipe.is_retrievable:
                continue

            task_similarity = self._task_similarity_to_recipe(task_description, recipe) if task_description else 1.0
            for step in recipe.steps:
                if step.get("tool_name") != tool_name:
                    continue
                step_server = str(step.get("server_name", ""))
                if server_name and step_server and step_server != server_name:
                    continue

                schema_similarity = self._schema_similarity(
                    current_schema,
                    step.get("parameter_schema", {}),
                )
                verification_total = recipe.verified_success_count + recipe.verified_fail_count
                has_verification = verification_total >= RECIPE_PREFLIGHT_MIN_VERIFICATIONS
                verification_rate = recipe.verification_rate if verification_total > 0 else recipe.success_rate
                score = (
                    schema_similarity
                    * recipe.quality_score
                    * recipe.success_rate
                    * verification_rate
                    * recipe.freshness
                    * task_similarity
                )
                candidates.append(
                    {
                        "recipe_id": recipe.id,
                        "recipe_name": recipe.name,
                        "step_tool_name": tool_name,
                        "server_name": step_server,
                        "schema_similarity": round(schema_similarity, 4),
                        "quality_score": round(recipe.quality_score, 4),
                        "success_rate": round(recipe.success_rate, 4),
                        "verification_rate": round(verification_rate, 4),
                        "verification_total": verification_total,
                        "has_verification": has_verification,
                        "freshness": round(recipe.freshness, 4),
                        "task_similarity": round(task_similarity, 4),
                        "governance_state": recipe.governance_state,
                        "promotion_state": recipe.promotion_state,
                        "score": round(score, 4),
                        "expected_schema": step.get("parameter_schema", {}),
                    }
                )

        candidates.sort(key=lambda item: item["score"], reverse=True)
        if not candidates:
            return {
                "decision": "no_evidence",
                "reason": "no_retrievable_recipe_for_tool",
                "tool_name": tool_name,
                "server_name": server_name,
                "arguments_schema": current_schema,
                "candidates": [],
            }

        best = candidates[0]
        reasons: list[str] = []
        decision = "proceed"
        if best["schema_similarity"] < RECIPE_PREFLIGHT_MIN_SCHEMA_SIMILARITY:
            decision = "warn"
            reasons.append("schema_similarity_below_recipe_evidence")
        if best["quality_score"] < RECIPE_PREFLIGHT_MIN_QUALITY:
            decision = "warn"
            reasons.append("recipe_quality_below_preflight_threshold")
        if best["success_rate"] < RECIPE_PREFLIGHT_MIN_SUCCESS_RATE:
            decision = "warn"
            reasons.append("recipe_success_rate_below_preflight_threshold")
        if best["has_verification"] and best["verification_rate"] < RECIPE_PREFLIGHT_MIN_VERIFICATION_RATE:
            decision = "block"
            reasons.append("verified_recipe_failure_rate_too_high")

        if not reasons:
            reasons.append("matched_verified_procedural_memory")

        return {
            "decision": decision,
            "reason": ";".join(reasons),
            "tool_name": tool_name,
            "server_name": server_name,
            "arguments_schema": current_schema,
            "best": best,
            "candidates": candidates[:RECIPE_CONTEXT_MAX_ITEMS],
        }

    def get_all(self) -> list[dict]:
        for recipe in self.recipes.values():
            self._refresh_quality_state(recipe)
        return [r.to_dict() for r in sorted(
            self.recipes.values(), key=lambda r: r.quality_score, reverse=True
        )]

    def reset_all(self) -> int:
        removed_count = len(self.recipes)
        self.recipes.clear()
        for f in RECIPES_DIR.glob("*.json"):
            try:
                f.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete recipe file {f}: {e}")
        return removed_count

class FailureGuardStore:
    """Tool Execution Memory for MCP Mirror."""

    def __init__(self):
        self.guards: dict[str, Guard] = {}
        self._load_all()

    def _load_all(self):
        known = set(Guard.__dataclass_fields__)
        for f in GUARDS_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if "alpha" not in data:
                    bc = data.get("block_count", 0)
                    data["alpha"] = BAYESIAN_PRIOR_ALPHA + bc
                    data["beta_param"] = BAYESIAN_PRIOR_BETA
                guard = Guard(**{k: v for k, v in data.items() if k in known})
                self.guards[guard.id] = guard
            except Exception as e:
                logger.warning(f"Failed to load Guard {f}: {e}")
        logger.info(f"FailureGuardStore loaded {len(self.guards)} guards")

    def _save(self, guard: Guard):
        path = GUARDS_DIR / f"{guard.id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(guard.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def _append_lifecycle_event(guard: Guard, event_type: str, **payload: Any) -> None:
        event = {
            "timestamp": _iso_utc_now(),
            "event_type": event_type,
            "guard_id": guard.id,
            **payload,
        }
        guard.lifecycle_events.append(event)
        if len(guard.lifecycle_events) > GUARD_LIFECYCLE_EVENT_MAX_ITEMS:
            guard.lifecycle_events = guard.lifecycle_events[-GUARD_LIFECYCLE_EVENT_MAX_ITEMS:]

    def import_snapshot(self, guards: dict[str, Guard]) -> None:
        self.guards = guards

    @staticmethod
    def _build_exact_signature(tool_name: str, server_name: str, error_type: str, val_hash: str) -> str:
        return f"exact|{tool_name}|{server_name}|{error_type}|{val_hash}"

    @staticmethod
    def _build_pattern_signature(
        tool_name: str,
        server_name: str,
        error_type: str,
        failure_cause: str,
        schema_signature_text: str,
    ) -> str:
        return f"pattern|{tool_name}|{server_name}|{error_type}|{failure_cause}|{schema_signature_text}"

    @staticmethod
    def _hash_argument_values(arguments: dict) -> str:
        """Tool Execution Memory for MCP Mirror."""
        parts: list[str] = []
        for k in sorted(arguments.keys()):
            v = arguments[k]
            v_text = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else str(v)
            v_hash = hashlib.md5(v_text.encode("utf-8")).hexdigest()[:12]
            parts.append(f"{k}={type(v).__name__}:{v_hash}")
        return "|".join(parts)

    @staticmethod
    def _schema_similarity(current_schema: dict, target_schema: dict) -> float:
        """Tool Execution Memory for MCP Mirror."""
        if not current_schema or not target_schema:
            return 0.0
        current_keys = set(current_schema.keys())
        target_keys = set(target_schema.keys())
        union = current_keys | target_keys
        if not union:
            return 0.0
        overlap = current_keys & target_keys
        key_jaccard = len(overlap) / len(union)
        if not overlap:
            return 0.0
        value_match = sum(
            1 for k in overlap if current_schema.get(k) == target_schema.get(k)
        ) / len(overlap)
        return math.sqrt(key_jaccard * value_match)

    @staticmethod
    def _merge_context(existing: Guard, context_hint: str, alternative_suggestion: str) -> None:
        if context_hint and context_hint not in existing.context_hint:
            existing.context_hint = f"{existing.context_hint}; {context_hint}".strip("; ")[:CONTEXT_HINT_MAX_LEN]
        if alternative_suggestion and not existing.alternative_suggestion:
            existing.alternative_suggestion = alternative_suggestion

    def _upsert_guard(
        self,
        *,
        guard_id: str,
        tool_name: str,
        server_name: str,
        error_type: str,
        error_message: str,
        argument_pattern: dict[str, str],
        argument_value_hash: str,
        match_level: str,
        match_signature: str,
        schema_signature: list[dict[str, str]],
        risk_tags: list[str],
        generalization_confidence: float,
        context_hint: str,
        alternative_suggestion: str,
        failure_cause: str,
    ) -> Guard:
        existing = self.guards.get(guard_id)
        if existing:
            existing.block_count += 1
            existing.alpha += 1.0
            existing.last_triggered_at = datetime.now(tz=timezone.utc).isoformat()
            existing.argument_pattern = dict(argument_pattern)
            existing.argument_value_hash = argument_value_hash
            existing.match_level = match_level
            existing.match_signature = match_signature
            existing.schema_signature = list(schema_signature)
            existing.risk_tags = list(risk_tags)
            existing.generalization_confidence = generalization_confidence
            self._merge_context(existing, context_hint, alternative_suggestion)
            self._append_lifecycle_event(
                existing,
                "failure_reinforced",
                match_level=match_level,
                error_type=error_type,
                failure_cause=failure_cause,
                posterior_failure_prob=round(existing.posterior_failure_prob, 4),
                block_count=existing.block_count,
                risk_tags=list(risk_tags),
            )
            self._save(existing)
            return existing

        guard = Guard(
            id=guard_id,
            tool_name=tool_name,
            server_name=server_name,
            error_type=error_type,
            error_message=error_message[:CONTEXT_HINT_MAX_LEN],
            argument_pattern=dict(argument_pattern),
            argument_value_hash=argument_value_hash,
            match_level=match_level,
            match_signature=match_signature,
            schema_signature=list(schema_signature),
            risk_tags=list(risk_tags),
            generalization_confidence=generalization_confidence,
            context_hint=context_hint[:CONTEXT_HINT_MAX_LEN],
            alternative_suggestion=alternative_suggestion,
            failure_cause=failure_cause,
            block_count=1,
            alpha=BAYESIAN_PRIOR_ALPHA + 1.0,
            beta_param=BAYESIAN_PRIOR_BETA,
        )
        self.guards[guard.id] = guard
        self._append_lifecycle_event(
            guard,
            "created",
            match_level=match_level,
            error_type=error_type,
            failure_cause=failure_cause,
            posterior_failure_prob=round(guard.posterior_failure_prob, 4),
            block_count=guard.block_count,
            risk_tags=list(risk_tags),
        )
        self._save(guard)
        return guard

    def _select_guard_candidate(
        self,
        tool_name: str,
        arguments: dict,
        server_name: str,
    ) -> Optional[tuple[Guard, dict[str, Any]]]:
        current_val_hash = self._hash_argument_values(arguments)
        current_schema = RecipeStore._build_parameter_schema(arguments)
        current_risk_tags = _risk_tags_from_arguments(arguments)

        exact_best: Optional[tuple[Guard, dict[str, Any]]] = None
        best: Optional[tuple[Guard, dict[str, Any]]] = None
        for guard in self.guards.values():
            if guard.tool_name != tool_name:
                continue
            if server_name and guard.server_name and guard.server_name != server_name:
                continue
            # Environment/runtime dependency failures are useful audit evidence,
            # but they should not permanently block future retries after the
            # runtime has been repaired.
            if guard.failure_cause == FailureCause.DEPENDENCY_MISSING.value:
                continue

            if guard.match_level == "exact" and guard.argument_value_hash == current_val_hash:
                evidence = {
                    "match_level": "exact",
                    "schema_similarity": 1.0,
                    "risk_overlap": 1.0,
                    "match_reason": "exact_argument_value_hash",
                    "generalization_confidence": 1.0,
                    "adjusted_failure_prob": round(guard.posterior_failure_prob, 3),
                }
                if exact_best is None or guard.posterior_failure_prob > exact_best[0].posterior_failure_prob:
                    exact_best = (guard, evidence)
                continue

            if not self._guard_allows_generalization(guard):
                continue

            schema_similarity = self._schema_similarity(current_schema, guard.argument_pattern)
            risk_overlap = _risk_overlap_score(current_risk_tags, guard.risk_tags)
            generalization_confidence = max(
                schema_similarity,
                risk_overlap,
                guard.generalization_confidence,
            )
            if schema_similarity < GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY:
                if risk_overlap < GUARD_GENERALIZATION_MIN_RISK_OVERLAP:
                    continue

            adjusted_prob = guard.posterior_failure_prob * generalization_confidence
            if adjusted_prob <= BAYESIAN_BLOCK_CONFIDENCE:
                continue

            evidence = {
                "match_level": "pattern",
                "schema_similarity": round(schema_similarity, 3),
                "risk_overlap": round(risk_overlap, 3),
                "match_reason": "schema_and_risk_pattern",
                "generalization_confidence": round(generalization_confidence, 3),
                "adjusted_failure_prob": round(adjusted_prob, 3),
            }
            if best is None:
                best = (guard, evidence)
                continue
            best_score = best[1].get("adjusted_failure_prob", best[0].posterior_failure_prob)
            if adjusted_prob > best_score:
                best = (guard, evidence)
        return exact_best or best

    @staticmethod
    def _guard_allows_generalization(guard: Guard) -> bool:
        cause = str(guard.failure_cause)
        risk_tags = set(guard.risk_tags)
        if cause == FailureCause.PERMISSION_DENIED.value:
            return bool(risk_tags & {"path_traversal", "system_path", "absolute_path"})
        if cause == FailureCause.INVALID_ARGUMENT.value:
            return "missing_like_value" in risk_tags
        if cause == FailureCause.RESOURCE_NOT_FOUND.value:
            # Missing resources may generalize only when the failed call clearly
            # targeted a narrow unsafe/missing namespace, not arbitrary valid files.
            if "filesystem_target" not in risk_tags:
                return False
            return bool(risk_tags & {"system_path", "path_traversal"})
        return False

    def record_failure(
        self,
        tool_name: str,
        arguments: dict,
        error_type: str,
        error_message: str,
        server_name: str = "",
        context_hint: str = "",
        alternative_suggestion: str = "",
    ) -> Guard:
        """Tool Execution Memory for MCP Mirror."""
        val_hash = self._hash_argument_values(arguments)
        cause, _ = _error_classifier.classify(error_type, error_message)
        argument_pattern = {k: type(v).__name__ for k, v in arguments.items()}
        schema_signature = _schema_signature_items(arguments)
        schema_signature_text = _schema_signature_text(arguments)
        risk_tags = _risk_tags_from_arguments(arguments)

        exact_sig = self._build_exact_signature(tool_name, server_name, error_type, val_hash)
        exact_guard_id = hashlib.md5(exact_sig.encode()).hexdigest()[:HASH_TRUNCATE_LEN]
        exact_guard = self._upsert_guard(
            guard_id=exact_guard_id,
            tool_name=tool_name,
            server_name=server_name,
            error_type=error_type,
            error_message=error_message,
            argument_pattern=argument_pattern,
            argument_value_hash=val_hash,
            match_level="exact",
            match_signature=exact_sig,
            schema_signature=schema_signature,
            risk_tags=risk_tags,
            generalization_confidence=1.0,
            context_hint=context_hint,
            alternative_suggestion=alternative_suggestion,
            failure_cause=cause.value,
        )

        pattern_sig = self._build_pattern_signature(
            tool_name,
            server_name,
            error_type,
            cause.value,
            schema_signature_text,
        )
        pattern_guard_id = hashlib.md5(pattern_sig.encode()).hexdigest()[:HASH_TRUNCATE_LEN]
        self._upsert_guard(
            guard_id=pattern_guard_id,
            tool_name=tool_name,
            server_name=server_name,
            error_type=error_type,
            error_message=error_message,
            argument_pattern=argument_pattern,
            argument_value_hash=val_hash,
            match_level="pattern",
            match_signature=pattern_sig,
            schema_signature=schema_signature,
            risk_tags=risk_tags,
            generalization_confidence=max(
                GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY,
                GUARD_GENERALIZATION_MIN_RISK_OVERLAP,
            ),
            context_hint=context_hint,
            alternative_suggestion=alternative_suggestion,
            failure_cause=cause.value,
        )

        logger.info(
            "Guard learned %s@%s | %s | cause=%s | exact=%s | pattern=%s",
            tool_name,
            server_name,
            error_type,
            cause.value,
            exact_guard.id,
            pattern_guard_id,
        )
        return exact_guard

    def record_success(self, tool_name: str, arguments: dict,
                       server_name: str = ""):
        """Tool Execution Memory for MCP Mirror."""
        val_hash = self._hash_argument_values(arguments)
        current_schema = RecipeStore._build_parameter_schema(arguments)
        current_risk_tags = _risk_tags_from_arguments(arguments)
        for guard in self.guards.values():
            if guard.tool_name != tool_name:
                continue
            if server_name and guard.server_name and guard.server_name != server_name:
                continue
            exact_match = guard.match_level == "exact" and guard.argument_value_hash == val_hash
            schema_similarity = self._schema_similarity(current_schema, guard.argument_pattern)
            risk_overlap = _risk_overlap_score(current_risk_tags, guard.risk_tags)
            if not exact_match and not self._guard_allows_generalization(guard):
                continue
            if not exact_match and schema_similarity < GUARD_GENERALIZATION_MIN_SCHEMA_SIMILARITY:
                if risk_overlap < GUARD_GENERALIZATION_MIN_RISK_OVERLAP:
                    continue
            guard.beta_param += 1.0
            guard.success_evidence_count += 1
            guard.last_triggered_at = datetime.now(tz=timezone.utc).isoformat()
            self._append_lifecycle_event(
                guard,
                "success_evidence",
                exact_match=exact_match,
                schema_similarity=round(schema_similarity, 4),
                risk_overlap=round(risk_overlap, 4),
                posterior_failure_prob=round(guard.posterior_failure_prob, 4),
                success_evidence_count=guard.success_evidence_count,
            )
            self._save(guard)
            logger.info(
                "Guard success evidence %s@%s | level=%s | P(fail)=%.3f",
                tool_name,
                server_name,
                guard.match_level,
                guard.posterior_failure_prob,
            )

    def check_guards(self, tool_name: str, arguments: dict,
                     server_name: str = "") -> Optional[Guard]:
        """Tool Execution Memory for MCP Mirror."""
        candidate = self.check_guards_with_evidence(tool_name, arguments, server_name)
        return candidate[0] if candidate else None

    def check_guards_with_evidence(
        self,
        tool_name: str,
        arguments: dict,
        server_name: str = "",
    ) -> Optional[tuple[Guard, dict[str, Any]]]:
        """Return the blocking guard plus the observable match evidence."""
        candidate = self._select_guard_candidate(tool_name, arguments, server_name)
        if candidate is None:
            return None

        guard, evidence = candidate
        if guard.governance_state in {"suppressed", "retired"}:
            return None
        guard.block_count += 1
        guard.last_triggered_at = datetime.now(tz=timezone.utc).isoformat()
        self._append_lifecycle_event(
            guard,
            "blocked",
            match_level=evidence.get("match_level", guard.match_level),
            match_reason=evidence.get("match_reason", ""),
            schema_similarity=evidence.get("schema_similarity"),
            risk_overlap=evidence.get("risk_overlap"),
            posterior_failure_prob=round(guard.posterior_failure_prob, 4),
            adjusted_failure_prob=evidence.get("adjusted_failure_prob"),
            governance_state=guard.governance_state,
        )
        self._save(guard)
        logger.warning(
            "Guard blocked %s@%s (%s, reason=%s, schema=%.3f, risk=%.3f)",
            tool_name,
            server_name,
            guard.explanation(),
            evidence.get("match_reason", "unknown"),
            float(evidence.get("schema_similarity", 0.0)),
            float(evidence.get("risk_overlap", 0.0)),
        )
        return guard, evidence

    def apply_governance_actions(self, actions: list[dict[str, Any]]) -> dict[str, int]:
        changed = {"active": 0, "suppressed": 0, "retired": 0}
        for action in actions:
            guard_id = str(action.get("id", ""))
            if not guard_id or guard_id not in self.guards:
                continue
            guard = self.guards[guard_id]
            old_governance_state = guard.governance_state
            decision = str(action.get("action", "retain"))
            reason = str(action.get("reason", "policy"))
            now_iso = _iso_utc_now()
            if decision == "candidate_retire":
                guard.governance_state = "retired"
                guard.governance_reason = reason
                changed["retired"] += 1
            elif decision == "suppress_from_precheck":
                guard.governance_state = "suppressed"
                guard.governance_reason = reason
                changed["suppressed"] += 1
            else:
                guard.governance_state = "active"
                guard.governance_reason = reason
                changed["active"] += 1
            guard.governance_updated_at = now_iso
            self._append_lifecycle_event(
                guard,
                "governance",
                previous_state=old_governance_state,
                action=decision,
                reason=reason,
                governance_state=guard.governance_state,
                posterior_failure_prob=round(guard.posterior_failure_prob, 4),
            )
            self._save(guard)
        return changed

    def rollback_governance(self, guard_ids: Optional[list[str]] = None, reason: str = "policy_rollback") -> dict[str, Any]:
        targets = set(guard_ids or [])
        changed: list[str] = []
        for guard in self.guards.values():
            if targets and guard.id not in targets:
                continue
            if guard.governance_state not in {"suppressed", "retired"}:
                continue
            old_governance_state = guard.governance_state
            guard.governance_state = "active"
            guard.governance_reason = reason
            guard.governance_updated_at = _iso_utc_now()
            self._append_lifecycle_event(
                guard,
                "rollback",
                previous_state=old_governance_state,
                reason=reason,
                governance_state=guard.governance_state,
                posterior_failure_prob=round(guard.posterior_failure_prob, 4),
            )
            self._save(guard)
            changed.append(guard.id)
        return {"restored": len(changed), "ids": changed}

    def record_avoided_failure(self, guard_id: str, counterfactual: str = "") -> None:
        guard = self.guards.get(guard_id)
        if not guard:
            return
        guard.avoided_count += 1
        guard.last_counterfactual_suggestion = counterfactual[:CONTEXT_HINT_MAX_LEN]
        guard.last_triggered_at = _iso_utc_now()
        self._append_lifecycle_event(
            guard,
            "avoided_failure",
            counterfactual=guard.last_counterfactual_suggestion,
            avoided_count=guard.avoided_count,
            posterior_failure_prob=round(guard.posterior_failure_prob, 4),
        )
        self._save(guard)

    def suggest_alternative_from_recipes(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        recipe_store: Optional["RecipeStore"] = None,
    ) -> str:
        """Tool Execution Memory for MCP Mirror."""
        if not recipe_store:
            return f"Check {tool_name} arguments and retry."

        current_schema = RecipeStore._build_parameter_schema(arguments or {})
        candidates: list[tuple[float, float, ToolRecipe, dict]] = []
        for recipe in recipe_store.recipes.values():
            if not recipe.is_retrievable:
                continue
            for step in recipe.steps:
                if step.get("tool_name") != tool_name:
                    continue
                step_schema = step.get("parameter_schema", {})
                schema_sim = self._schema_similarity(current_schema, step_schema)
                if arguments and schema_sim < A5_MIN_SCHEMA_SIMILARITY:
                    continue
                quality = recipe.success_rate
                freshness = recipe.freshness
                schema_weight = schema_sim if arguments else 1.0
                score = schema_weight * quality * freshness
                if score > 0.0:
                    candidates.append((score, schema_sim, recipe, step_schema))

        if not candidates:
            return f"Check {tool_name} arguments and retry."

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:A5_TOP_K_SUGGESTIONS]
        lines: list[str] = []
        for _, schema_sim, recipe, step_schema in top:
            param_items = list(step_schema.items())[:A5_PARAM_PREVIEW_MAX_ITEMS]
            param_desc = ", ".join(f"{k}: {v}" for k, v in param_items)
            lines.append(
                f"{recipe.name}(sim={schema_sim:.2f}, success={recipe.success_rate:.0%}, fresh={recipe.freshness:.0%})"
                + (f" argument pattern: {param_desc}" if param_desc else "")
            )
        return "Reference successful recipe: " + " | ".join(lines)

    def get_all(self) -> list[dict]:
        return [g.to_dict() for g in sorted(
            self.guards.values(), key=lambda g: g.block_count, reverse=True
        )]

    def reset_all(self) -> int:
        """Tool Execution Memory for MCP Mirror."""
        removed_count = len(self.guards)
        self.guards.clear()
        for f in GUARDS_DIR.glob("*.json"):
            try:
                f.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete guard file {f}: {e}")
        return removed_count

    def get_guards_for_context(self,
                               tool_names: Optional[list[str]] = None) -> list[dict]:
        """Tool Execution Memory for MCP Mirror."""
        candidates: list[tuple[float, Guard]] = []
        for guard in self.guards.values():
            if guard.governance_state in {"suppressed", "retired"}:
                continue
            if tool_names and guard.tool_name not in tool_names:
                continue
            candidates.append((guard.posterior_failure_prob, guard))

        candidates.sort(key=lambda x: x[0], reverse=True)

        result: list[dict] = []
        for prob, guard in candidates[:GUARD_CONTEXT_MAX_ITEMS]:
            result.append({
                "id": guard.id,
                "tool": guard.tool_name,
                "tool_name": guard.tool_name,
                "server": guard.server_name,
                "server_name": guard.server_name,
                "error": guard.error_type,
                "error_type": guard.error_type,
                "cause": guard.failure_cause,
                "hint": guard.context_hint[:100],
                "suggestion": guard.alternative_suggestion[:150],
                "times": guard.block_count,
                "failure_prob": round(prob, 3),
                "governance_state": guard.governance_state,
                "governance_reason": guard.governance_reason,
                "created_at": guard.created_at,
                "last_triggered_at": guard.last_triggered_at,
                "avoided_count": guard.avoided_count,
                "match_level": guard.match_level,
            })
        return result


class ToolExecutionMemory:
    """Tool Execution Memory for MCP Mirror."""

    def __init__(self):
        self.recipes = RecipeStore()
        self.guards = FailureGuardStore()
        self._pending_steps: dict[str, list[ToolStep]] = {}
        self._recent_decisions: deque[dict[str, Any]] = deque(maxlen=200)
        self.mode = DEFAULT_TEM_MODE
        self._mode_flags = dict(TEM_MODE_FLAGS[self.mode])

    def set_mode(self, mode: str) -> dict[str, Any]:
        normalized = normalize_tem_mode(mode)
        self.mode = normalized
        self._mode_flags = dict(TEM_MODE_FLAGS[normalized])
        self._pending_steps.clear()
        trace = self._append_decision_trace({
            "trace_id": hashlib.md5(
                f"mode|{normalized}|{_iso_utc_now()}".encode("utf-8")
            ).hexdigest()[:HASH_TRUNCATE_LEN],
            "phase": "runtime_control",
            "decision": "set_mode",
            "mode": normalized,
            "flags": dict(self._mode_flags),
        })
        return {
            "ok": True,
            "mode": normalized,
            "flags": dict(self._mode_flags),
            "decision_trace_id": trace["trace_id"],
        }

    def get_mode_state(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "supported_modes": list(SUPPORTED_TEM_MODES),
            "flags": dict(self._mode_flags),
        }

    def reset_traces(self) -> int:
        removed_count = 0
        if TEM_TRACE_PATH.exists():
            removed_count = 1
            try:
                TEM_TRACE_PATH.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete TEM trace file {TEM_TRACE_PATH}: {e}")
                removed_count = 0
        self._recent_decisions.clear()
        return removed_count

    def reset_memory(
        self,
        *,
        recipes: bool = False,
        guards: bool = False,
        traces: bool = False,
        pending: bool = True,
    ) -> dict[str, Any]:
        removed = {
            "recipes": self.recipes.reset_all() if recipes else 0,
            "guards": self.guards.reset_all() if guards else 0,
            "traces": self.reset_traces() if traces else 0,
            "pending_clients": len(self._pending_steps) if pending else 0,
        }
        if pending:
            self._pending_steps.clear()
        return {"ok": True, "removed": removed, "mode": self.mode}

    def _append_decision_trace(self, record: dict[str, Any]) -> dict[str, Any]:
        trace = dict(record)
        trace.setdefault("timestamp", _iso_utc_now())
        self._recent_decisions.append(trace)
        try:
            with open(TEM_TRACE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"TEM decision trace save failed: {e}")
        return trace

    def get_recent_decisions(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        cap = limit or max(TOP_STATS_LIMIT * 4, 10)
        recent: deque[dict[str, Any]] = deque(maxlen=cap)
        if TEM_TRACE_PATH.exists():
            try:
                with open(TEM_TRACE_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            recent.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning(f"TEM decision trace read failed: {e}")
        if not recent:
            recent = deque(self._recent_decisions, maxlen=cap)
        return list(recent)[-cap:]

    def get_context_snapshot(self, task_description: str = "",
                             tool_names: Optional[list[str]] = None) -> dict[str, Any]:
        raw_tools = list(dict.fromkeys(tool_names or []))
        relevant_tools = infer_relevant_tool_names(task_description, raw_tools) if task_description and raw_tools else raw_tools
        matched = (
            self.recipes.match_recipes(task_description, relevant_tools)
            if self._mode_flags["enable_recipe_context"]
            else []
        )
        recipe_items: list[dict[str, Any]] = []
        for recipe in matched[:RECIPE_CONTEXT_MAX_ITEMS]:
            recipe_tools = {str(tag) for tag in recipe.tags}
            allowed = set(relevant_tools)
            tool_overlap = len(recipe_tools & allowed) / len(recipe_tools | allowed) if allowed and recipe_tools else 0.0
            recipe_items.append({
                "id": recipe.id,
                "name": recipe.name,
                "success_rate": round(recipe.success_rate, 3),
                "failure_rate": round(recipe.failure_rate, 3),
                "freshness": round(recipe.freshness, 3),
                "quality_score": round(recipe.quality_score, 3),
                "promotion_state": recipe.promotion_state,
                "governance_state": recipe.governance_state,
                "governance_reason": recipe.governance_reason,
                "schema_consistency": round(recipe.schema_consistency, 3),
                "contamination_risk": round(recipe.contamination_risk, 3),
                "suppression_reason": recipe.suppression_reason,
                "retrieval_count": recipe.retrieval_count,
                "verification_rate": round(recipe.verification_rate, 3),
                "verified_success_count": recipe.verified_success_count,
                "verified_fail_count": recipe.verified_fail_count,
                "created_at": recipe.created_at,
                "last_used_at": recipe.last_used_at,
                "last_verified_at": recipe.last_verified_at,
                "verification_total": recipe.verified_success_count + recipe.verified_fail_count,
                "program_memory_type": "procedural_tool_recipe",
                "verifiable": bool(recipe.steps and recipe.parameter_schema),
                "tool_overlap": round(tool_overlap, 3),
                "steps": recipe.steps,
            })
        return {
            "task_description": task_description,
            "candidate_tools": raw_tools,
            "relevant_tools": relevant_tools,
            "mode": self.mode,
            "flags": dict(self._mode_flags),
            "recipes": recipe_items,
            "guards": self.guards.get_guards_for_context(relevant_tools) if self._mode_flags["enable_guard_blocking"] else [],
        }

    def get_recipe_preflight(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_name: str = "",
        task_description: str = "",
    ) -> dict[str, Any]:
        return self.recipes.verify_tool_call_against_recipes(
            tool_name=tool_name,
            arguments=arguments,
            server_name=server_name,
            task_description=task_description,
        )

    def before_tool_call(self, tool_name: str, arguments: dict,
                         server_name: str = "",
                         task_description: str = "",
                         enforce_recipe_preflight_block: bool = True,
                         enforce_guard_block: bool = True) -> Optional[dict]:
        """Tool Execution Memory for MCP Mirror."""
        if not self._mode_flags["enable_guard_blocking"]:
            return None
        recipe_preflight = None
        if self._mode_flags["enable_recipe_context"]:
            recipe_preflight = self.recipes.verify_tool_call_against_recipes(
                tool_name=tool_name,
                arguments=arguments,
                server_name=server_name,
                task_description=task_description,
            )
            if recipe_preflight.get("decision") == "block":
                if not enforce_recipe_preflight_block:
                    self._append_decision_trace({
                        "trace_id": hashlib.md5(
                            f"before_recipe_warn|{tool_name}|{server_name}|{_iso_utc_now()}".encode("utf-8")
                        ).hexdigest()[:HASH_TRUNCATE_LEN],
                        "phase": "before_tool_call",
                        "decision": "recipe_preflight_warned",
                        "tool_name": tool_name,
                        "server_name": server_name,
                        "arguments_schema": RecipeStore._build_parameter_schema(arguments),
                        "recipe_preflight": recipe_preflight,
                    })
                    recipe_preflight = {
                        **recipe_preflight,
                        "decision": "warn",
                        "original_decision": "block",
                        "reason": (
                            f"{recipe_preflight.get('reason', '')};"
                            "manual_explicit_tool_call_recipe_block_downgraded"
                        ).strip(";"),
                    }
                else:
                    trace = self._append_decision_trace({
                        "trace_id": hashlib.md5(
                            f"before_recipe|{tool_name}|{server_name}|{_iso_utc_now()}".encode("utf-8")
                        ).hexdigest()[:HASH_TRUNCATE_LEN],
                        "phase": "before_tool_call",
                        "decision": "blocked_by_recipe_preflight",
                        "tool_name": tool_name,
                        "server_name": server_name,
                        "arguments_schema": RecipeStore._build_parameter_schema(arguments),
                        "recipe_preflight": recipe_preflight,
                    })
                    best = recipe_preflight.get("best", {})
                    return {
                        "blocked": True,
                        "block_source": "recipe_preflight",
                        "trace_id": trace["trace_id"],
                        "tool_name": tool_name,
                        "reason": (
                            "Recipe preflight blocked the tool call: "
                            f"schema={float(best.get('schema_similarity', 0.0)):.2f}, "
                            f"verification={float(best.get('verification_rate', 0.0)):.2f}, "
                            f"quality={float(best.get('quality_score', 0.0)):.2f}"
                        ),
                        "suggestion": (
                            f"Check arguments against verified recipe {best.get('recipe_name', 'unknown')} "
                            "or use a different tool path."
                        ),
                        "context_hint": recipe_preflight.get("reason", ""),
                        "recipe_preflight": recipe_preflight,
                        "counterfactual": {
                            "type": "recipe_preflight_counterfactual",
                            "suggested_action": "repair_arguments_or_choose_alternative_recipe",
                            "evidence": best,
                        },
                    }
        if enforce_guard_block:
            guard_result = self.guards.check_guards_with_evidence(tool_name, arguments, server_name)
        else:
            guard_result = self.guards._select_guard_candidate(tool_name, arguments, server_name)
        if guard_result:
            guard, evidence = guard_result
            if not enforce_guard_block:
                self._append_decision_trace({
                    "trace_id": hashlib.md5(
                        f"before_guard_warn|{tool_name}|{server_name}|{_iso_utc_now()}|{guard.id}".encode("utf-8")
                    ).hexdigest()[:HASH_TRUNCATE_LEN],
                    "phase": "before_tool_call",
                    "decision": "guard_warned",
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "arguments_schema": RecipeStore._build_parameter_schema(arguments),
                    "guard_id": guard.id,
                    "error_type": guard.error_type,
                    "failure_cause": guard.failure_cause,
                    "posterior_failure_prob": round(guard.posterior_failure_prob, 3),
                    "effective_alpha": round(guard.effective_alpha, 3),
                    "effective_beta": round(guard.effective_beta, 3),
                    "suggestion": guard.alternative_suggestion,
                    "guard_evidence": {
                        **dict(evidence or {}),
                        "reason": (
                            f"{str((evidence or {}).get('match_reason', ''))};"
                            "manual_explicit_tool_call_guard_block_downgraded"
                        ).strip(";"),
                    },
                    "recipe_preflight": recipe_preflight,
                })
                return None
            trace = self._append_decision_trace({
                "trace_id": hashlib.md5(
                    f"before|{tool_name}|{server_name}|{_iso_utc_now()}|{guard.id}".encode("utf-8")
                ).hexdigest()[:HASH_TRUNCATE_LEN],
                "phase": "before_tool_call",
                "decision": "blocked",
                "tool_name": tool_name,
                "server_name": server_name,
                "arguments_schema": RecipeStore._build_parameter_schema(arguments),
                "guard_id": guard.id,
                "error_type": guard.error_type,
                "failure_cause": guard.failure_cause,
                "posterior_failure_prob": round(guard.posterior_failure_prob, 3),
                "effective_alpha": round(guard.effective_alpha, 3),
                "effective_beta": round(guard.effective_beta, 3),
                "suggestion": guard.alternative_suggestion,
                "guard_evidence": evidence,
                "recipe_preflight": recipe_preflight,
            })
            return {
                "blocked": True,
                "block_source": "guard",
                "guard_id": guard.id,
                "tool_name": guard.tool_name,
                "error_type": guard.error_type,
                "failure_cause": guard.failure_cause,
                "trace_id": trace["trace_id"],
                "reason": (
                    f"Guard blocked the tool call: estimated failure probability "
                    f"{guard.posterior_failure_prob:.1%} "
                    f"(alpha={guard.effective_alpha:.1f}, beta={guard.effective_beta:.1f})"
                ),
                "suggestion": guard.alternative_suggestion,
                "context_hint": guard.context_hint,
                "guard_evidence": evidence,
                "recipe_preflight": recipe_preflight,
                "counterfactual": {
                    "type": "guard_failure_counterfactual",
                    "suggested_action": guard.alternative_suggestion,
                    "guard_id": guard.id,
                    "failure_cause": guard.failure_cause,
                    "match_evidence": evidence,
                    "estimated_failure_probability": round(guard.posterior_failure_prob, 3),
                },
            }
        return None

    def after_tool_call(
        self,
        client_id: str,
        tool_name: str,
        arguments: dict,
        result: Any,
        success: bool,
        error_type: str = "",
        error_message: str = "",
        latency_ms: float = 0.0,
        server_name: str = "",
        task_description: str = "",
    ) -> dict:
        """Tool Execution Memory for MCP Mirror."""
        event: dict[str, Any] = {
            "tool_name": tool_name,
            "success": success,
            "latency_ms": latency_ms,
            "arguments_schema": RecipeStore._build_parameter_schema(arguments),
        }

        if success:
            result_summary = ""
            if isinstance(result, dict):
                result_summary = json.dumps(result, ensure_ascii=False)[:RESULT_SUMMARY_MAX_LEN]
            elif isinstance(result, str):
                result_summary = result[:RESULT_SUMMARY_MAX_LEN]
            else:
                result_summary = str(result)[:RESULT_SUMMARY_MAX_LEN]

            if self._mode_flags["enable_recipe_learning"]:
                step = ToolStep(
                    tool_name=tool_name,
                    arguments=arguments,
                    result_summary=result_summary,
                    success=True,
                    latency_ms=latency_ms,
                    server_name=server_name,
                )

                if client_id not in self._pending_steps:
                    self._pending_steps[client_id] = []
                self._pending_steps[client_id].append(step)
                self._pending_steps[client_id] = self.recipes.prune_pending_steps(
                    self._pending_steps[client_id]
                )

                recipe = self.recipes.extract_recipe(
                    self._pending_steps[client_id],
                    task_description=task_description,
                )
                if recipe:
                    event["recipe_learned"] = {
                        "id": recipe.id,
                        "name": recipe.name,
                        "success_count": recipe.success_count,
                        "success_rate": round(recipe.success_rate, 3),
                        "quality_score": round(recipe.quality_score, 3),
                        "promotion_state": recipe.promotion_state,
                        "contamination_risk": round(recipe.contamination_risk, 3),
                    }
            if self._mode_flags["enable_guard_learning"]:
                self.guards.record_success(tool_name, arguments, server_name)
            trace = self._append_decision_trace({
                "trace_id": hashlib.md5(
                    f"after|{client_id}|{tool_name}|{server_name}|{_iso_utc_now()}".encode("utf-8")
                ).hexdigest()[:HASH_TRUNCATE_LEN],
                "phase": "after_tool_call",
                "decision": "success",
                "mode": self.mode,
                "client_id": client_id,
                "tool_name": tool_name,
                "server_name": server_name,
                "task_description": task_description[:CONTEXT_HINT_MAX_LEN],
                "arguments_schema": event["arguments_schema"],
                "latency_ms": latency_ms,
                "recipe_id": event.get("recipe_learned", {}).get("id", ""),
            })
            event["decision_trace_id"] = trace["trace_id"]
        else:
            guard = None
            suggestion = ""
            affected_recipe_ids = self.recipes.record_tool_failure(
                tool_name=tool_name,
                arguments=arguments,
                server_name=server_name,
                failure_context=f"tool_failure:{error_type or 'UnknownError'}",
            )
            if affected_recipe_ids:
                event["recipe_penalties"] = affected_recipe_ids
            if self._mode_flags["enable_guard_learning"]:
                suggestion = self.guards.suggest_alternative_from_recipes(
                    tool_name,
                    arguments,
                    self.recipes if self._mode_flags["enable_recipe_context"] else None,
                )
                guard = self.guards.record_failure(
                    tool_name=tool_name,
                    arguments=arguments,
                    error_type=error_type or "UnknownError",
                    error_message=error_message,
                    server_name=server_name,
                    context_hint=task_description,
                    alternative_suggestion=suggestion,
                )
                event["guard_created"] = {
                    "id": guard.id,
                    "tool_name": guard.tool_name,
                    "error_type": guard.error_type,
                    "failure_cause": guard.failure_cause,
                    "suggestion": guard.alternative_suggestion,
                    "block_count": guard.block_count,
                    "posterior_failure_prob": round(guard.posterior_failure_prob, 3),
                }
            trace = self._append_decision_trace({
                "trace_id": hashlib.md5(
                    f"after|{client_id}|{tool_name}|{server_name}|{_iso_utc_now()}".encode("utf-8")
                ).hexdigest()[:HASH_TRUNCATE_LEN],
                "phase": "after_tool_call",
                "decision": "failure",
                "mode": self.mode,
                "client_id": client_id,
                "tool_name": tool_name,
                "server_name": server_name,
                "task_description": task_description[:CONTEXT_HINT_MAX_LEN],
                "arguments_schema": event["arguments_schema"],
                "latency_ms": latency_ms,
                "error_type": error_type or "UnknownError",
                "error_message": error_message[:CONTEXT_HINT_MAX_LEN],
                "guard_id": guard.id if guard else "",
                "failure_cause": guard.failure_cause if guard else "",
                "suggestion": guard.alternative_suggestion if guard else suggestion,
            })
            event["decision_trace_id"] = trace["trace_id"]

        return event

    def clear_pending_steps(self, client_id: str):
        """Tool Execution Memory for MCP Mirror."""
        self._pending_steps.pop(client_id, None)

    def get_recipes_for_context(self, task_description: str = "",
                                tool_names: Optional[list[str]] = None) -> str:
        """Build recipe-memory context for the LLM prompt."""
        if not self._mode_flags["enable_recipe_context"]:
            return ""
        snapshot = self.get_context_snapshot(task_description, tool_names)
        matched = self.recipes.match_recipes(task_description, snapshot["relevant_tools"])
        if not matched:
            return ""

        lines = ["Available Recipe memory (retrieved for the current task):"]
        if snapshot["relevant_tools"]:
            lines.append(f"- Relevant tools: {', '.join(snapshot['relevant_tools'])}")
        for recipe in matched[:RECIPE_CONTEXT_MAX_ITEMS]:
            steps_desc = " -> ".join(step["tool_name"] for step in recipe.steps)
            lines.append(
                f"- [{recipe.name}] {steps_desc} "
                f"(success={recipe.success_rate:.0%}, evidence={recipe.success_count}, freshness={recipe.freshness:.0%})"
            )
        return "\n".join(lines)

    def get_guards_for_context(self,
                               tool_names: Optional[list[str]] = None) -> str:
        """Build guard-memory context for the LLM prompt."""
        if not self._mode_flags["enable_guard_blocking"]:
            return ""
        guards = self.guards.get_guards_for_context(tool_names)
        if not guards:
            return ""

        lines = ["High-risk Guard memory (used before tool calls):"]
        for guard in guards:
            lines.append(
                f"- Tool {guard['tool']} failure probability {guard['failure_prob']:.0%} "
                f"({guard['error']}, cause={guard['cause']}). Suggestion: {guard['suggestion']}"
            )
        return "\n".join(lines)
    def get_stats(self) -> dict:
        """Tool Execution Memory for MCP Mirror."""
        cause_dist: dict[str, int] = {}
        for g in self.guards.guards.values():
            c = g.failure_cause
            cause_dist[c] = cause_dist.get(c, 0) + g.block_count

        recipe_state_dist: dict[str, int] = {}
        for recipe in self.recipes.recipes.values():
            self.recipes._refresh_quality_state(recipe)
            state = recipe.promotion_state
            recipe_state_dist[state] = recipe_state_dist.get(state, 0) + 1

        return {
            "mode": self.mode,
            "mode_flags": dict(self._mode_flags),
            "total_recipes": len(self.recipes.recipes),
            "total_guards": len(self.guards.guards),
            "total_blocks": sum(g.block_count for g in self.guards.guards.values()),
            "failure_cause_distribution": cause_dist,
            "recipe_state_distribution": recipe_state_dist,
            "decision_trace_path": str(TEM_TRACE_PATH),
            "recent_decisions": self.get_recent_decisions(TOP_STATS_LIMIT),
            "top_recipes": [r.to_dict() for r in sorted(
                self.recipes.recipes.values(), key=lambda r: r.quality_score, reverse=True
            )[:TOP_STATS_LIMIT]],
            "top_guards": [g.to_dict() for g in sorted(
                self.guards.guards.values(), key=lambda g: g.block_count, reverse=True
            )[:TOP_STATS_LIMIT]],
        }


tem = ToolExecutionMemory()


def reload_tem_parameters() -> dict:
    """Tool Execution Memory for MCP Mirror."""
    global _error_classifier
    _apply_tem_params(load_required_params("tool_execution_memory", _TEM_PARAM_KEYS))
    _error_classifier = SemanticErrorClassifier()
    return {
        "NGRAM_SIZE": NGRAM_SIZE,
        "CENTROID_LEARNING_RATE": CENTROID_LEARNING_RATE,
        "EVIDENCE_HALF_LIFE_DAYS": EVIDENCE_HALF_LIFE_DAYS,
        "BAYESIAN_BLOCK_CONFIDENCE": BAYESIAN_BLOCK_CONFIDENCE,
        "DANGER_THRESHOLD": DANGER_THRESHOLD,
    }
