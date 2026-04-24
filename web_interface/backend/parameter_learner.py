"""
Online parameter learner for algorithm_params.json.

Purpose:
- Remove manual parameter tuning workflow.
- Continuously collect runtime feedback.
- Use Thompson sampling on parameter candidates.
- Write next parameter recommendation to artifacts/algorithm_params.json.

Note:
- Existing modules read params at import/startup.
- Applied recommendations are hot-reloaded by app.py runtime endpoints.
"""

import json
import logging
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probabilistic_params import PARAMS_PATH, load_required_params

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts"
LEARNER_STATE_PATH = ARTIFACTS_DIR / "param_learner_state.json"
FEEDBACK_LOG_PATH = ARTIFACTS_DIR / "param_feedback.jsonl"

_LEARNER_PARAM_KEYS = [
    "MIN_FEEDBACK_FOR_UPDATE",
    "AUTO_APPLY_INTERVAL",
    "EXPLORATION_PROBABILITY",
    "SUCCESS_REWARD_WEIGHT",
    "EFFICIENCY_REWARD_WEIGHT",
    "MAX_COMPRESSION_RATIO_FOR_REWARD",
    "ARM_PRIOR_ALPHA",
    "ARM_PRIOR_BETA",
    "BLOCKED_REWARD",
    "FAILURE_REWARD",
    "LATENCY_PENALTY_DIVISOR",
    "LATENCY_PENALTY_MAX",
    "NUMERIC_EPSILON",
    "TUNABLES",
]
_LEARNER_CFG = load_required_params("param_learner", _LEARNER_PARAM_KEYS)


@dataclass
class ArmState:
    alpha: float = float(_LEARNER_CFG["ARM_PRIOR_ALPHA"])
    beta: float = float(_LEARNER_CFG["ARM_PRIOR_BETA"])
    observations: int = 0
    last_updated: str = ""


def _arm_key(section: str, key: str, value: Any) -> str:
    return f"{section}.{key}={value}"


class OnlineParameterLearner:
    def __init__(self):
        cfg = _LEARNER_CFG
        self.min_feedback_for_update = int(cfg["MIN_FEEDBACK_FOR_UPDATE"])
        self.auto_apply_interval = int(cfg["AUTO_APPLY_INTERVAL"])
        self.exploration_probability = float(cfg["EXPLORATION_PROBABILITY"])
        self.success_reward_weight = float(cfg["SUCCESS_REWARD_WEIGHT"])
        self.efficiency_reward_weight = float(cfg["EFFICIENCY_REWARD_WEIGHT"])
        self.max_compression_ratio_for_reward = float(cfg["MAX_COMPRESSION_RATIO_FOR_REWARD"])
        self.arm_prior_alpha = float(cfg["ARM_PRIOR_ALPHA"])
        self.arm_prior_beta = float(cfg["ARM_PRIOR_BETA"])
        self.blocked_reward = float(cfg["BLOCKED_REWARD"])
        self.failure_reward = float(cfg["FAILURE_REWARD"])
        self.latency_penalty_divisor = float(cfg["LATENCY_PENALTY_DIVISOR"])
        self.latency_penalty_max = float(cfg["LATENCY_PENALTY_MAX"])
        self.numeric_epsilon = float(cfg["NUMERIC_EPSILON"])
        self.tunables = cfg["TUNABLES"]

        self._feedback_count = 0
        self._state = self._load_state()
        self._ensure_arm_state_initialized()

    def _ensure_arm_state_initialized(self):
        changed = False
        for t in self.tunables:
            section = t["section"]
            key = t["key"]
            for value in t["values"]:
                ak = _arm_key(section, key, value)
                if ak not in self._state["arms"]:
                    self._state["arms"][ak] = asdict(ArmState())
                    changed = True
        if changed:
            self._save_state()

    def _load_state(self) -> dict[str, Any]:
        if LEARNER_STATE_PATH.exists():
            try:
                with open(LEARNER_STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if "arms" in state and isinstance(state["arms"], dict):
                    return state
            except Exception as e:
                logger.warning(
                    "Parameter learner state is unreadable, fallback to new state: %s",
                    e,
                )
        return {
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "updated_at": "",
            "feedback_count": 0,
            "last_applied_recommendation": {},
            "arms": {},
        }

    def _save_state(self):
        self._state["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        with open(LEARNER_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def _append_feedback(self, payload: dict[str, Any]):
        payload["ts"] = datetime.now(tz=timezone.utc).isoformat()
        with open(FEEDBACK_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _update_current_arm_reward(self, reward: float):
        """
        Reward updates currently active arms (the parameters currently in use).
        """
        reward = max(0.0, min(1.0, reward))
        current_params = self._load_params()
        for t in self.tunables:
            section = t["section"]
            key = t["key"]
            value = current_params[section][key]
            ak = _arm_key(section, key, value)
            if ak not in self._state["arms"]:
                self._state["arms"][ak] = asdict(ArmState())
            arm = self._state["arms"][ak]
            arm["alpha"] += reward
            arm["beta"] += 1.0 - reward
            arm["observations"] += 1
            arm["last_updated"] = datetime.now(tz=timezone.utc).isoformat()

    def _load_params(self) -> dict[str, Any]:
        with open(PARAMS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def record_context_feedback(
        self,
        response_ok: bool,
        compression_ratio: float,
        compressed_tokens: int,
        original_tokens: int,
    ):
        ratio_clipped = min(
            max(compression_ratio, 0.0),
            self.max_compression_ratio_for_reward,
        )
        efficiency_reward = ratio_clipped / max(self.max_compression_ratio_for_reward, self.numeric_epsilon)
        reward = (
            self.success_reward_weight * (1.0 if response_ok else 0.0)
            + self.efficiency_reward_weight * efficiency_reward
        )
        self._update_current_arm_reward(reward)
        self._feedback_count += 1
        self._state["feedback_count"] = int(self._state.get("feedback_count", 0)) + 1
        self._append_feedback(
            {
                "kind": "context",
                "response_ok": bool(response_ok),
                "compression_ratio": float(compression_ratio),
                "compressed_tokens": int(compressed_tokens),
                "original_tokens": int(original_tokens),
                "reward": reward,
            }
        )
        self._save_state()
        self._maybe_auto_apply()

    def record_tool_feedback(self, success: bool, blocked: bool, latency_ms: float):
        # blocked but not executed -> partial reward; success -> full reward.
        if success:
            reward = 1.0
        elif blocked:
            reward = self.blocked_reward
        else:
            reward = self.failure_reward
        # latency regularization: slightly penalize very slow outcomes.
        latency_penalty = min(latency_ms / max(self.latency_penalty_divisor, self.numeric_epsilon), self.latency_penalty_max)
        reward = max(0.0, min(1.0, reward - latency_penalty))
        self._update_current_arm_reward(reward)
        self._feedback_count += 1
        self._state["feedback_count"] = int(self._state.get("feedback_count", 0)) + 1
        self._append_feedback(
            {
                "kind": "tool",
                "success": bool(success),
                "blocked": bool(blocked),
                "latency_ms": float(latency_ms),
                "reward": reward,
            }
        )
        self._save_state()
        self._maybe_auto_apply()

    def _sample_arm(self, section: str, key: str, values: list[Any]) -> Any:
        sampled: list[tuple[float, Any]] = []
        for value in values:
            ak = _arm_key(section, key, value)
            arm = self._state["arms"].get(ak, asdict(ArmState()))
            s = random.betavariate(
                max(arm["alpha"], self.numeric_epsilon),
                max(arm["beta"], self.numeric_epsilon),
            )
            sampled.append((s, value))
        sampled.sort(key=lambda x: x[0], reverse=True)
        return sampled[0][1]

    def recommend_next_params(self) -> dict[str, Any]:
        params = self._load_params()
        recommendation = {"changes": []}
        for t in self.tunables:
            section = t["section"]
            key = t["key"]
            values = t["values"]
            current_val = params[section][key]

            if random.random() < self.exploration_probability:
                candidate_values = [v for v in values if v != current_val]
                if candidate_values:
                    next_val = random.choice(candidate_values)
                else:
                    next_val = current_val
            else:
                next_val = self._sample_arm(section, key, values)

            recommendation["changes"].append(
                {
                    "section": section,
                    "key": key,
                    "current": current_val,
                    "recommended": next_val,
                }
            )
        recommendation["ts"] = datetime.now(tz=timezone.utc).isoformat()
        return recommendation

    def apply_recommendation(self, recommendation: dict[str, Any]) -> dict[str, Any]:
        params = self._load_params()
        applied = []
        for c in recommendation.get("changes", []):
            section = c["section"]
            key = c["key"]
            if section in params and key in params[section]:
                old = params[section][key]
                new = c["recommended"]
                params[section][key] = new
                if old != new:
                    applied.append({"section": section, "key": key, "old": old, "new": new})
        params["metadata"]["calibrated_at"] = datetime.now(tz=timezone.utc).isoformat()
        params["metadata"]["last_calibration_mode"] = "online_thompson_sampling"

        with open(PARAMS_PATH, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

        self._state["last_applied_recommendation"] = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "applied": applied,
        }
        self._save_state()
        return {"applied": applied, "count": len(applied)}

    def _maybe_auto_apply(self):
        total_feedback = int(self._state.get("feedback_count", 0))
        if total_feedback < self.min_feedback_for_update:
            return
        if self.auto_apply_interval <= 0:
            return
        if total_feedback % self.auto_apply_interval != 0:
            return
        rec = self.recommend_next_params()
        self.apply_recommendation(rec)

    def get_status(self) -> dict[str, Any]:
        return {
            "feedback_count": int(self._state.get("feedback_count", 0)),
            "min_feedback_for_update": self.min_feedback_for_update,
            "auto_apply_interval": self.auto_apply_interval,
            "exploration_probability": self.exploration_probability,
            "last_applied_recommendation": self._state.get("last_applied_recommendation", {}),
            "state_file": str(LEARNER_STATE_PATH),
            "feedback_log_file": str(FEEDBACK_LOG_PATH),
        }


parameter_learner = OnlineParameterLearner()

