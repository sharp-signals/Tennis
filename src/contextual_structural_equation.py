"""Candidate internal equation for the structural-strength family.

The equation is market-free and SHADOW-only.  Constants are human priors that
must later be challenged by chronological replay; they are not production
weights and cannot mutate the current index or pricing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


SCHEMA_VERSION = 1
EQUATION_VERSION = "structural-context-v1"


@dataclass(frozen=True)
class StructuralEquationConfig:
    # A ratio of 1.5 represents nearby competitive positions such as #40/#60.
    rank_ratio_deadzone: float = 1.5
    rank_ratio_saturation: float = 8.0
    points_ratio_deadzone: float = 1.10
    points_ratio_saturation: float = 3.0
    trajectory_saturation_log: float = 0.80
    trajectory_max_adjustment: float = 0.25
    recovery_max_adjustment: float = 0.12
    inactivity_full_reliability_days: float = 45.0
    inactivity_zero_recovery_days: float = 180.0
    minimum_history_for_trajectory: int = 4


def _positive(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _signed_ratio_signal(
    a: Any, b: Any, *, lower_is_better: bool,
    deadzone: float, saturation: float,
) -> float | None:
    left, right = _positive(a), _positive(b)
    if left is None or right is None:
        return None
    raw = math.log(right / left) if lower_is_better else math.log(left / right)
    magnitude = abs(raw)
    floor, ceiling = math.log(deadzone), math.log(saturation)
    if magnitude <= floor:
        return 0.0
    scaled = min(1.0, (magnitude - floor) / max(1e-9, ceiling - floor))
    return math.copysign(scaled, raw)


def _trajectory(player: dict[str, Any], config: StructuralEquationConfig) -> float | None:
    history = int(_positive(player.get("historical_observation_count")) or 0)
    if history < config.minimum_history_for_trajectory:
        return None
    value_6m = _finite(player.get("ranking_strength_change_6m"))
    value_12m = _finite(player.get("ranking_strength_change_12m"))
    if value_6m is not None and value_12m is not None:
        return 0.65 * value_6m + 0.35 * value_12m
    return value_6m if value_6m is not None else value_12m


def _inactivity_reliability(player: dict[str, Any], config: StructuralEquationConfig) -> float:
    days = _positive(player.get("days_since_last_match"))
    if days is None or days <= config.inactivity_full_reliability_days:
        return 1.0
    span = config.inactivity_zero_recovery_days - config.inactivity_full_reliability_days
    return max(0.0, 1.0 - (days - config.inactivity_full_reliability_days) / span)


def _recovery_evidence(player: dict[str, Any], config: StructuralEquationConfig) -> float:
    """Recognise a return towards recent level without restoring old reputation."""
    current = _positive(player.get("current_rank"))
    best_365 = _positive(player.get("observed_best_rank_365d"))
    trajectory = _trajectory(player, config)
    if current is None or best_365 is None or trajectory is None or trajectory <= 0:
        return 0.0
    gap = max(0.0, math.log(current / best_365))
    supported_recovery = min(gap, trajectory)
    inactivity = _inactivity_reliability(player, config)
    return min(1.0, supported_recovery / config.trajectory_saturation_log) * inactivity


def evaluate_structural_strength(
    player_a: dict[str, Any], player_b: dict[str, Any],
    *, config: StructuralEquationConfig | None = None,
) -> dict[str, Any]:
    """Transform structural facts into one bounded, auditable family signal."""
    cfg = config or StructuralEquationConfig()
    rank_signal = _signed_ratio_signal(
        player_a.get("current_rank"), player_b.get("current_rank"),
        lower_is_better=True, deadzone=cfg.rank_ratio_deadzone,
        saturation=cfg.rank_ratio_saturation,
    )
    points_signal = _signed_ratio_signal(
        player_a.get("current_points"), player_b.get("current_points"),
        lower_is_better=False, deadzone=cfg.points_ratio_deadzone,
        saturation=cfg.points_ratio_saturation,
    )
    level_parts = [value for value in (rank_signal, points_signal) if value is not None]
    if not level_parts:
        return {
            "schema_version": SCHEMA_VERSION,
            "equation_version": EQUATION_VERSION,
            "status": "INSUFFICIENT_BILATERAL_LEVEL",
            "family_signal": None,
            "market_used": False,
            "production_effect": False,
        }
    # Rank and points are two views of the same current level, not two votes.
    current_level_signal = sum(level_parts) / len(level_parts)

    trajectory_a, trajectory_b = _trajectory(player_a, cfg), _trajectory(player_b, cfg)
    trajectory_signal = None
    if trajectory_a is not None and trajectory_b is not None:
        trajectory_signal = max(
            -1.0, min(1.0, (trajectory_a - trajectory_b) / cfg.trajectory_saturation_log),
        )
    recovery_signal = _recovery_evidence(player_a, cfg) - _recovery_evidence(player_b, cfg)

    # Current competitive level remains the anchor.  Trajectory and supported
    # recovery can adjust it, but never replace it with historical reputation.
    signal = current_level_signal
    if trajectory_signal is not None:
        signal += cfg.trajectory_max_adjustment * trajectory_signal
    signal += cfg.recovery_max_adjustment * recovery_signal
    signal = max(-1.0, min(1.0, signal))

    history_a = int(_positive(player_a.get("historical_observation_count")) or 0)
    history_b = int(_positive(player_b.get("historical_observation_count")) or 0)
    history_reliability = min(1.0, min(history_a, history_b) / 12.0)
    bilateral_level = 1.0 if len(level_parts) == 2 else 0.75
    reliability = max(0.0, min(1.0, 0.7 * bilateral_level + 0.3 * history_reliability))

    return {
        "schema_version": SCHEMA_VERSION,
        "equation_version": EQUATION_VERSION,
        "status": "READY",
        "direction": "a" if signal > 0 else "b" if signal < 0 else "neutral",
        "magnitude": round(abs(signal), 6),
        "reliability": round(reliability, 6),
        "applicability": 1.0,
        "family_signal": round(signal, 6),
        "components": {
            "current_level": round(current_level_signal, 6),
            "rank": None if rank_signal is None else round(rank_signal, 6),
            "points": None if points_signal is None else round(points_signal, 6),
            "trajectory": None if trajectory_signal is None else round(trajectory_signal, 6),
            "supported_recovery": round(recovery_signal, 6),
        },
        "governance": {
            "current_level_is_anchor": True,
            "rank_and_points_are_dependent_views": True,
            "historical_peak_is_not_direct_vote": True,
            "trajectory_cannot_replace_current_level": True,
        },
        "candidate_parameters": asdict(cfg),
        "market_used": False,
        "production_effect": False,
    }
