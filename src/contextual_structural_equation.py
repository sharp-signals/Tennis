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
EQUATION_VERSION_V2 = "structural-context-v2"
EQUATION_VERSION_V3 = "structural-context-v3-components"
EQUATION_VERSION_V4 = "structural-context-v4-rank-bands"
EQUATION_VERSION_V5 = "structural-context-v5-points-residual"


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


@dataclass(frozen=True)
class StructuralEquationV2Config:
    rank_ratio_full_signal: float = 8.0
    points_ratio_full_signal: float = 3.0
    rank_share_when_points_available: float = 0.70
    recovery_max_adjustment: float = 0.08
    recovery_saturation_log: float = 0.80
    inactivity_full_reliability_days: float = 45.0
    inactivity_floor_days: float = 240.0
    minimum_representativeness: float = 0.72
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


def _continuous_ratio_signal(
    a: Any, b: Any, *, lower_is_better: bool, full_signal_ratio: float,
) -> float | None:
    left, right = _positive(a), _positive(b)
    if left is None or right is None:
        return None
    raw = math.log(right / left) if lower_is_better else math.log(left / right)
    return max(-1.0, min(1.0, raw / math.log(full_signal_ratio)))


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


def _trajectory_v2(
    player: dict[str, Any], config: StructuralEquationV2Config,
) -> float | None:
    history = int(_positive(player.get("historical_observation_count")) or 0)
    if history < config.minimum_history_for_trajectory:
        return None
    six = _finite(player.get("ranking_strength_change_6m"))
    twelve = _finite(player.get("ranking_strength_change_12m"))
    if six is not None and twelve is not None:
        return 0.65 * six + 0.35 * twelve
    return six if six is not None else twelve


def _representativeness_v2(
    player: dict[str, Any], config: StructuralEquationV2Config,
) -> float:
    days = _positive(player.get("days_since_last_match"))
    if days is None or days <= config.inactivity_full_reliability_days:
        inactivity = 1.0
    else:
        span = config.inactivity_floor_days - config.inactivity_full_reliability_days
        inactivity = max(
            config.minimum_representativeness,
            1.0 - (days - config.inactivity_full_reliability_days)
            / span * (1.0 - config.minimum_representativeness),
        )
    trajectory = _trajectory_v2(player, config)
    # A rapidly moving ranking is less representative, regardless of direction.
    volatility = min(1.0, abs(trajectory or 0.0) / config.recovery_saturation_log)
    trajectory_reliability = 1.0 - 0.12 * volatility
    return max(
        config.minimum_representativeness,
        min(1.0, inactivity * trajectory_reliability),
    )


def _supported_recovery_v2(
    player: dict[str, Any], config: StructuralEquationV2Config,
) -> float:
    current = _positive(player.get("current_rank"))
    best_365 = _positive(player.get("observed_best_rank_365d"))
    trajectory = _trajectory_v2(player, config)
    if current is None or best_365 is None or trajectory is None or trajectory <= 0:
        return 0.0
    gap = max(0.0, math.log(current / best_365))
    supported = min(gap, trajectory) / config.recovery_saturation_log
    return min(1.0, supported) * _representativeness_v2(player, config)


def evaluate_structural_strength_v2(
    player_a: dict[str, Any], player_b: dict[str, Any],
    *, config: StructuralEquationV2Config | None = None,
) -> dict[str, Any]:
    """Continuous structural curve with context acting on representativeness."""
    cfg = config or StructuralEquationV2Config()
    rank_signal = _continuous_ratio_signal(
        player_a.get("current_rank"), player_b.get("current_rank"),
        lower_is_better=True, full_signal_ratio=cfg.rank_ratio_full_signal,
    )
    points_signal = _continuous_ratio_signal(
        player_a.get("current_points"), player_b.get("current_points"),
        lower_is_better=False, full_signal_ratio=cfg.points_ratio_full_signal,
    )
    if rank_signal is None and points_signal is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "equation_version": EQUATION_VERSION_V2,
            "status": "INSUFFICIENT_BILATERAL_LEVEL",
            "family_signal": None,
            "market_used": False,
            "production_effect": False,
        }
    if rank_signal is not None and points_signal is not None:
        level = (
            cfg.rank_share_when_points_available * rank_signal
            + (1.0 - cfg.rank_share_when_points_available) * points_signal
        )
    else:
        level = rank_signal if rank_signal is not None else points_signal

    representative_a = _representativeness_v2(player_a, cfg)
    representative_b = _representativeness_v2(player_b, cfg)
    trajectory_a = _trajectory_v2(player_a, cfg)
    trajectory_b = _trajectory_v2(player_b, cfg)
    pair_representativeness = math.sqrt(representative_a * representative_b)
    recovery = (
        _supported_recovery_v2(player_a, cfg)
        - _supported_recovery_v2(player_b, cfg)
    )
    signal = float(level) * pair_representativeness
    signal += cfg.recovery_max_adjustment * recovery
    signal = max(-1.0, min(1.0, signal))

    return {
        "schema_version": SCHEMA_VERSION,
        "equation_version": EQUATION_VERSION_V2,
        "status": "READY",
        "direction": "a" if signal > 0 else "b" if signal < 0 else "neutral",
        "magnitude": round(abs(signal), 6),
        "reliability": round(pair_representativeness, 6),
        "applicability": 1.0,
        "family_signal": round(signal, 6),
        "components": {
            "continuous_rank": None if rank_signal is None else round(rank_signal, 6),
            "continuous_points": None if points_signal is None else round(points_signal, 6),
            "current_level": round(float(level), 6),
            "representativeness_a": round(representative_a, 6),
            "representativeness_b": round(representative_b, 6),
            "trajectory_a": None if trajectory_a is None else round(trajectory_a, 6),
            "trajectory_b": None if trajectory_b is None else round(trajectory_b, 6),
            "days_since_last_match_a": _positive(player_a.get("days_since_last_match")),
            "days_since_last_match_b": _positive(player_b.get("days_since_last_match")),
            "supported_recovery": round(recovery, 6),
        },
        "governance": {
            "no_hard_rank_deadzone": True,
            "current_level_is_anchor": True,
            "trajectory_mainly_controls_representativeness": True,
            "historical_peak_is_not_direct_vote": True,
            "recovery_adjustment_is_capped": True,
        },
        "candidate_parameters": asdict(cfg),
        "market_used": False,
        "production_effect": False,
    }


def _inactivity_penalty_v3(player: dict[str, Any]) -> float | None:
    days = _positive(player.get("days_since_last_match"))
    if days is None:
        return None
    if days <= 45.0:
        return 0.0
    return min(1.0, (days - 45.0) / 195.0)


def evaluate_structural_strength_v3(
    player_a: dict[str, Any], player_b: dict[str, Any],
    *, config: StructuralEquationV2Config | None = None,
) -> dict[str, Any]:
    """Expose independent structural components; calibration combines them later."""
    cfg = config or StructuralEquationV2Config()
    rank_a = _positive(player_a.get("current_rank"))
    rank_b = _positive(player_b.get("current_rank"))
    if rank_a is None or rank_b is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "equation_version": EQUATION_VERSION_V3,
            "status": "INSUFFICIENT_BILATERAL_LEVEL",
            "candidate_features": {},
            "market_used": False,
            "production_effect": False,
        }

    # Preserve the complete current-ranking distance. No saturation: a 20x gap
    # remains larger than an 8x gap and calibration determines its probability.
    rank_core = math.log(rank_b / rank_a)
    trajectory_a = _trajectory_v2(player_a, cfg)
    trajectory_b = _trajectory_v2(player_b, cfg)
    trajectory_margin = (
        trajectory_a - trajectory_b
        if trajectory_a is not None and trajectory_b is not None else None
    )
    inactivity_a = _inactivity_penalty_v3(player_a)
    inactivity_b = _inactivity_penalty_v3(player_b)
    # Positive means B carries more inactivity uncertainty, therefore relative
    # evidence in favour of A. It never changes rank_core directly.
    inactivity_margin = (
        inactivity_b - inactivity_a
        if inactivity_a is not None and inactivity_b is not None else None
    )
    recovery_a = _supported_recovery_v2(player_a, cfg)
    recovery_b = _supported_recovery_v2(player_b, cfg)
    recovery_margin = recovery_a - recovery_b
    features = {
        "contextual_structural_rank_core_v3": rank_core,
        "contextual_structural_trajectory_margin_v3": trajectory_margin,
        "contextual_structural_inactivity_margin_v3": inactivity_margin,
        "contextual_structural_recovery_margin_v3": recovery_margin,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "equation_version": EQUATION_VERSION_V3,
        "status": "READY",
        "candidate_features": {
            key: None if value is None else round(float(value), 6)
            for key, value in features.items()
        },
        "components": {
            "rank_core_log_ratio": round(rank_core, 6),
            "trajectory_a": None if trajectory_a is None else round(trajectory_a, 6),
            "trajectory_b": None if trajectory_b is None else round(trajectory_b, 6),
            "days_since_last_match_a": _positive(player_a.get("days_since_last_match")),
            "days_since_last_match_b": _positive(player_b.get("days_since_last_match")),
            "inactivity_penalty_a": inactivity_a,
            "inactivity_penalty_b": inactivity_b,
            "supported_recovery_a": round(recovery_a, 6),
            "supported_recovery_b": round(recovery_b, 6),
            "supported_recovery": round(recovery_margin, 6),
        },
        "governance": {
            "current_rank_is_unsaturated_anchor": True,
            "modifiers_are_separate_features": True,
            "historical_peak_is_not_direct_vote": True,
            "market_is_forbidden": True,
            "requires_chronological_calibration": True,
        },
        "market_used": False,
        "production_effect": False,
    }


def _rank_band_v4(rank: float) -> int:
    if rank <= 10:
        return 5
    if rank <= 20:
        return 4
    if rank <= 50:
        return 3
    if rank <= 100:
        return 2
    if rank <= 200:
        return 1
    return 0


def evaluate_structural_strength_v4(
    player_a: dict[str, Any], player_b: dict[str, Any],
    *, config: StructuralEquationV2Config | None = None,
) -> dict[str, Any]:
    """Add one auditable rank-band residual to the unsaturated v3 components."""
    base = evaluate_structural_strength_v3(player_a, player_b, config=config)
    if base.get("status") != "READY":
        return {
            **base,
            "equation_version": EQUATION_VERSION_V4,
        }
    rank_a = float(_positive(player_a.get("current_rank")))
    rank_b = float(_positive(player_b.get("current_rank")))
    band_a = _rank_band_v4(rank_a)
    band_b = _rank_band_v4(rank_b)
    raw_gap = band_a - band_b
    # Adjacent bands are deliberately neutral: #40 vs #60 must not receive a
    # second vote merely because they sit on opposite sides of the top-50 cut.
    material_gap = 0.0 if abs(raw_gap) < 2 else raw_gap / 5.0
    features = dict(base["candidate_features"])
    features["contextual_structural_material_band_gap_v4"] = round(material_gap, 6)
    return {
        **base,
        "equation_version": EQUATION_VERSION_V4,
        "candidate_features": features,
        "components": {
            **base["components"],
            "rank_band_a": band_a,
            "rank_band_b": band_b,
            "raw_rank_band_gap": raw_gap,
            "material_rank_band_gap": round(material_gap, 6),
        },
        "governance": {
            **base["governance"],
            "rank_bands_are_residual_not_replacement": True,
            "adjacent_rank_bands_are_neutral": True,
        },
    }


def evaluate_structural_strength_v5(
    player_a: dict[str, Any], player_b: dict[str, Any],
    *, config: StructuralEquationV2Config | None = None,
) -> dict[str, Any]:
    """Test ranking points as a separate residual beyond the v3 rank anchor."""
    base = evaluate_structural_strength_v3(player_a, player_b, config=config)
    if base.get("status") != "READY":
        return {**base, "equation_version": EQUATION_VERSION_V5}
    points_a = _positive(player_a.get("current_points"))
    points_b = _positive(player_b.get("current_points"))
    points_margin = (
        math.log(points_a / points_b)
        if points_a is not None and points_b is not None else None
    )
    features = dict(base["candidate_features"])
    features["contextual_structural_points_log_ratio_v5"] = (
        None if points_margin is None else round(points_margin, 6)
    )
    return {
        **base,
        "equation_version": EQUATION_VERSION_V5,
        "candidate_features": features,
        "components": {
            **base["components"],
            "points_a": points_a,
            "points_b": points_b,
            "points_log_ratio": (
                None if points_margin is None else round(points_margin, 6)
            ),
        },
        "governance": {
            **base["governance"],
            "points_are_residual_not_rank_replacement": True,
            "missing_points_do_not_change_rank_core": True,
        },
    }
