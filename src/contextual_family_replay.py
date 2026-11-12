"""Leakage-safe chronological replay of the five contextual families.

The replay creates factual, pre-match feature rows.  It deliberately does not
fit weights, probabilities, fair odds or edges.  Player A/B orientation is
alphabetical and therefore independent of the eventual winner.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import math
import threading
from typing import Any, Mapping
import weakref

import pandas as pd

from .contextual_factor_orchestrator import build_contextual_family_vector
from .contextual_structural_equation import (
    evaluate_structural_strength,
    evaluate_structural_strength_v2,
    evaluate_structural_strength_v3,
    evaluate_structural_strength_v4,
    evaluate_structural_strength_v5,
    evaluate_structural_strength_v6,
    evaluate_structural_strength_v7,
)
from .contextual_ranking import summarize_return_context, summarize_weekly_rank_history
from .contextual_surface import (
    _surface as _canonical_surface,
    _pace as _surface_pace,
    _row_pace,
    _row_venue,
    _venue as _surface_venue,
)
from .contextual_surface_equation import (
    evaluate_surface_conditions,
    evaluate_surface_conditions_v2,
    evaluate_surface_conditions_v3,
)
from .contextual_surface_ledger import (
    build_chronological_surface_ledger,
    exact_surface_context,
)
from .recent_form_audit import _column, _is_non_standard_completion, _parse_history_dates
from .recent_form_replay import (
    _game_margin,
    _name_key,
    _player_observation,
    _positive_rank,
    _summarize_player_history,
)
from .contextual_serve_return import _aggregate, _extract_match


SCHEMA_VERSION = 1
WINDOW_DAYS = 90
RECENT_RELIABILITY_MIN_MATCHES = 4.0
RECENT_MAIN_RELIABILITY_MIN_MATCHES = 2.0
_MAX_TOURNAMENT_POINTS = 2000.0
_COMPETITION_CHAMPION_POINTS = {
    0: 100.0,
    1: 250.0,
    2: 500.0,
    3: 1000.0,
    4: 2000.0,
}
_COMPETITION_LEVEL_STRENGTH = {
    "c": 0,
    "challenger": 0,
    "challenger 50": 0,
    "challenger 75": 0,
    "challenger 100": 0,
    "challenger 125": 0,
    "250": 1,
    "atp 250": 1,
    "wta 250": 1,
    "500": 2,
    "atp 500": 2,
    "wta 500": 2,
    "a": 2,
    "d": 2,
    "m": 3,
    "masters 1000": 3,
    "atp masters 1000": 3,
    "wta 1000": 3,
    "g": 4,
    "grand slam": 4,
    "f": 4,
    "championships": 4,
    "atp finals": 4,
    "wta finals": 4,
}
FEATURE_FAMILIES = {
    "recent_result_balance_90d": "recent_form",
    "recent_game_margin_balance_90d": "recent_form",
    "recent_win_opponent_strength_90d": "recent_form",
    "recent_loss_opponent_strength_90d": "recent_form",
    "contextual_recent_result_core_v1": "recent_form",
    "contextual_recent_competitiveness_v1": "recent_form",
    "contextual_recent_win_quality_v1": "recent_form",
    "contextual_recent_loss_context_v1": "recent_form",
    "contextual_recent_bad_loss_penalty_v2": "recent_form",
    "contextual_recent_result_peer_higher_v5": "recent_form",
    "contextual_recent_competitiveness_peer_higher_v5": "recent_form",
    "contextual_recent_win_quality_peer_higher_v5": "recent_form",
    "contextual_recent_result_lower_main_v5": "recent_form",
    "contextual_recent_competitiveness_lower_main_v5": "recent_form",
    "contextual_recent_win_quality_lower_main_v5": "recent_form",
    "contextual_recent_result_challenger_v5": "recent_form",
    "contextual_recent_competitiveness_challenger_v5": "recent_form",
    "contextual_recent_win_quality_challenger_v5": "recent_form",
    "contextual_recent_result_main_v7": "recent_form",
    "contextual_recent_competitiveness_main_v7": "recent_form",
    "contextual_recent_win_quality_main_v7": "recent_form",
    "contextual_recent_tier_win_credit_v7": "recent_form",
    "contextual_recent_circuit_downshift_v8": "recent_form",
    "current_rank_log_ratio": "structural_strength",
    "rank_change_from_last_observation": "structural_strength",
    "contextual_structural_signal_v1": "structural_strength",
    "contextual_structural_signal_v2": "structural_strength",
    "contextual_structural_rank_core_v3": "structural_strength",
    "contextual_structural_trajectory_margin_v3": "structural_strength",
    "contextual_structural_inactivity_margin_v3": "structural_strength",
    "contextual_structural_recovery_margin_v3": "structural_strength",
    "contextual_structural_material_band_gap_v4": "structural_strength",
    "contextual_structural_points_log_ratio_v5": "structural_strength",
    "contextual_structural_material_rank_core_v6": "structural_strength",
    "contextual_structural_representative_rank_core_v6": "structural_strength",
    "contextual_structural_points_log_ratio_v6": "structural_strength",
    "contextual_structural_return_rank_contraction_v7": "structural_strength",
    "contextual_structural_return_points_contraction_v7": "structural_strength",
    "contextual_structural_return_friction_margin_v7": "structural_strength",
    "same_surface_result_balance_90d": "surface_conditions",
    "career_surface_win_rate_margin": "surface_conditions",
    "contextual_surface_signal_v1": "surface_conditions",
    "contextual_surface_signal_v2": "surface_conditions",
    "contextual_surface_signal_v3": "surface_conditions",
    "exact_surface_career_margin_raw": "surface_conditions",
    "exact_surface_previous_margin_raw": "surface_conditions",
    "exact_surface_current_margin_raw": "surface_conditions",
    "exact_surface_career_margin_shrunk": "surface_conditions",
    "exact_surface_previous_margin_shrunk": "surface_conditions",
    "exact_surface_current_margin_shrunk": "surface_conditions",
    "exact_surface_tier_win_credit_career_v8": "surface_conditions",
    "exact_surface_tier_win_credit_previous_v8": "surface_conditions",
    "exact_surface_tier_win_credit_current_v8": "surface_conditions",
    "h2h_win_share_margin": "matchup_h2h",
    "same_surface_h2h_win_share_margin": "matchup_h2h",
    "contextual_h2h_global_shrunk_v1": "matchup_h2h",
    "service_points_won_surface_margin": "serve_return",
    "return_points_won_surface_margin": "serve_return",
    "hold_surface_margin": "serve_return",
    "break_surface_margin": "serve_return",
    "service_points_won_recent_margin": "serve_return",
    "return_points_won_recent_margin": "serve_return",
    "service_points_won_surface_margin_shrunk_v1": "serve_return",
    "return_points_won_surface_margin_shrunk_v1": "serve_return",
    "hold_surface_margin_shrunk_v1": "serve_return",
    "break_surface_margin_shrunk_v1": "serve_return",
    "service_points_won_recent_deviation_v1": "serve_return",
    "return_points_won_recent_deviation_v1": "serve_return",
}
RECENT_FORM_DECAYS_V1 = {
    "atp": {
        "result": None, "competitiveness": 45,
        "win_quality": 60, "loss_context": 45,
    },
    "wta": {
        "result": None, "competitiveness": 90,
        "win_quality": 60, "loss_context": 90,
    },
}
RECENT_LOSS_CONTEXT_GRID_V2 = (0.0, 0.10, 0.25, 0.50, 1.0)


def recent_loss_context_feature(alpha: float) -> str:
    return f"contextual_recent_adjusted_result_loss_{int(round(alpha * 100)):03d}_v5"


for _alpha in RECENT_LOSS_CONTEXT_GRID_V2:
    FEATURE_FAMILIES[recent_loss_context_feature(_alpha)] = "recent_form"


def adjust_recent_result_for_loss_context(
    result_balance: float | None,
    *,
    bad_loss_penalty: float | None,
    strong_loss_relief: float | None,
    alpha: float,
) -> float | None:
    """Apply loss context without ever rewarding a strong-opponent loss."""
    if result_balance is None:
        return None
    if not 0.0 <= float(alpha) <= 1.0:
        raise ValueError("alpha must be between zero and one")
    value = (
        float(result_balance)
        - float(alpha) * float(bad_loss_penalty or 0.0)
    )
    relief_room = max(0.0, -value)
    relief = min(
        float(alpha) * float(strong_loss_relief or 0.0), relief_room,
    )
    return value + relief
_MATERIAL_CACHE: dict[int, tuple[weakref.ReferenceType[pd.DataFrame], pd.DataFrame]] = {}
_MATERIAL_CACHE_LOCK = threading.Lock()


def _surface(value: Any) -> str | None:
    """Canonicalise provider and historical surface labels identically."""
    return _canonical_surface(value)


def _surface_from_context(context: Any) -> str | None:
    if context in {"hard_outdoor", "hard_indoor"}:
        return "hard"
    if context in {"clay", "grass"}:
        return str(context)
    return None


def _material(frame: pd.DataFrame) -> pd.DataFrame:
    fallback_dates = _parse_history_dates(_column(frame, "event_date"))
    if "date" in frame.columns:
        exact_dates = _parse_history_dates(frame["date"])
        dates = exact_dates.fillna(fallback_dates)
        date_source = pd.Series(
            ["match_date" if pd.notna(value) else "tournament_date_fallback"
             for value in exact_dates],
            index=frame.index,
        )
    else:
        dates = fallback_dates
        date_source = pd.Series("tournament_date_fallback", index=frame.index)
    material = frame.copy()
    material["_event_date"] = dates.dt.date
    material["_date_source"] = date_source
    material["_winner"] = _column(frame, "winner_name").astype("string").str.strip()
    material["_loser"] = _column(frame, "loser_name").astype("string").str.strip()
    material["_winner_key"] = material["_winner"].map(_name_key)
    material["_loser_key"] = material["_loser"].map(_name_key)
    material["_surface"] = _column(frame, "surface").map(_surface)
    material["_winner_rank"] = _column(frame, "winner_rank")
    material["_loser_rank"] = _column(frame, "loser_rank")
    material["_winner_points"] = frame.get(
        "winner_rank_points", pd.Series(index=frame.index, dtype="float64"),
    )
    material["_loser_points"] = frame.get(
        "loser_rank_points", pd.Series(index=frame.index, dtype="float64"),
    )
    material["_venue"] = frame.apply(_row_venue, axis=1)
    material["_surface_context"] = frame.apply(
        lambda row: (
            row.get("surface_context")
            if row.get("surface_context") in {
                "hard_outdoor", "hard_indoor", "clay", "grass",
            }
            else exact_surface_context(
                row.get("surface"), venue=_row_venue(row),
            )
        ),
        axis=1,
    )
    recovered_surface = material["_surface_context"].map(_surface_from_context)
    material["_surface"] = material["_surface"].fillna(recovered_surface)
    material["_pace"] = frame.apply(_row_pace, axis=1)
    material["_score"] = _column(frame, "score")
    material["_tournament"] = frame.get(
        "tourney_name",
        frame.get(
            "tournament_name",
            pd.Series(index=frame.index, dtype="string"),
        ),
    ).astype("string").str.strip()
    material["_round"] = frame.get(
        "round", pd.Series(index=frame.index, dtype="string"),
    ).astype("string").str.strip()
    material["_non_standard"] = _is_non_standard_completion(frame)
    material["_competition_scope"] = frame.get(
        "_history_competition_scope",
        pd.Series("main", index=frame.index),
    ).fillna("main").astype("string").str.strip().str.casefold()
    material["_competition_level"] = frame.get(
        "tier",
        frame.get(
            "tourney_level",
            pd.Series(index=frame.index, dtype="string"),
        ),
    ).astype("string").str.strip().str.casefold()
    return material[
        material["_event_date"].notna()
        & material["_winner"].notna()
        & material["_loser"].notna()
        & (material["_winner"] != "")
        & (material["_loser"] != "")
    ].sort_values("_event_date")


def _cached_material(frame: pd.DataFrame) -> pd.DataFrame:
    """Reuse parsed history inside one bot run; never persist provider data."""
    key = id(frame)
    with _MATERIAL_CACHE_LOCK:
        cached = _MATERIAL_CACHE.get(key)
        if cached is not None and cached[0]() is frame:
            return cached[1]
        material = _material(frame)
        _MATERIAL_CACHE[key] = (weakref.ref(frame), material)
        stale = [item for item, (reference, _) in _MATERIAL_CACHE.items() if reference() is None]
        for item in stale:
            _MATERIAL_CACHE.pop(item, None)
        return material


def _optional_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _difference(a: Any, b: Any) -> float | None:
    if a is None or b is None:
        return None
    try:
        left, right = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(left) or not math.isfinite(right):
        return None
    return left - right


def _competition_strength(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    text = " ".join(str(value).strip().casefold().split())
    if not text:
        return None
    if text in _COMPETITION_LEVEL_STRENGTH:
        return _COMPETITION_LEVEL_STRENGTH[text]
    if "challenger" in text:
        return 0
    if "grand slam" in text:
        return 4
    if "masters" in text or "1000" in text:
        return 3
    if "500" in text:
        return 2
    if "250" in text:
        return 1
    return None


def _recent_competition_bucket(
    observation: dict[str, Any], *, target_level: Any,
) -> str:
    scope = str(observation.get("competition_scope") or "").casefold()
    source_level = _competition_strength(observation.get("competition_level"))
    if "challenger" in scope or source_level == 0:
        return "challenger"
    target_strength = _competition_strength(target_level)
    if source_level is None or target_strength is None:
        return "peer_higher"
    return "peer_higher" if source_level >= target_strength else "lower_main"


def _shrunk_recent_value(
    summary: dict[str, Any], value_key: str, sample_key: str,
    *, full_reliability_from: float = RECENT_RELIABILITY_MIN_MATCHES,
) -> tuple[float, int]:
    sample = int(summary.get(sample_key) or 0)
    value = summary.get(value_key)
    if sample <= 0 or value is None:
        return 0.0, 0
    reliability = min(1.0, sample / full_reliability_from)
    return float(value) * reliability, sample


def _tier_recent_summary(
    observations: list[dict[str, Any]], *, cutoff: date,
) -> dict[str, float | int | None]:
    """Compute the three v5 components in one bounded 90-day pass."""
    start = cutoff - timedelta(days=WINDOW_DAYS)
    eligible = [
        row for row in observations if start <= row["event_date"] < cutoff
    ]
    if not eligible:
        return {
            "result_balance": None, "sample": 0,
            "game_margin_balance": None, "game_margin_sample": 0,
            "win_opponent_strength": None, "wins_sample": 0,
        }
    result_balance = sum(float(row["result"]) for row in eligible) / len(eligible)
    margins = [row for row in eligible if row.get("game_margin") is not None]
    margin_weights = [
        0.5 ** (max(0, (cutoff - row["event_date"]).days) / 45.0)
        for row in margins
    ]
    game_margin_balance = (
        sum(weight * float(row["game_margin"]) for weight, row in zip(margin_weights, margins))
        / sum(margin_weights)
        if margins else None
    )
    wins = [
        row for row in eligible
        if row.get("won") and row.get("opponent_rank") is not None
    ]
    win_weights = [
        0.5 ** (max(0, (cutoff - row["event_date"]).days) / 60.0)
        for row in wins
    ]
    win_opponent_strength = (
        sum(
            weight * -math.log(float(row["opponent_rank"]))
            for weight, row in zip(win_weights, wins)
        ) / sum(win_weights)
        if wins else None
    )
    return {
        "result_balance": result_balance,
        "sample": len(eligible),
        "game_margin_balance": game_margin_balance,
        "game_margin_sample": len(margins),
        "win_opponent_strength": win_opponent_strength,
        "wins_sample": len(wins),
    }


def _tier_win_credit_summary(
    observations: list[dict[str, Any]], *, cutoff: date,
) -> tuple[float | None, int]:
    """Recent wins weighted by the objective hierarchy of the competition.

    The scale mirrors the maximum ranking points of the category.  A win in a
    Masters therefore carries ten times the category credit of a generic
    Challenger win.  Losses contribute zero rather than a negative tier
    penalty, so merely playing a stronger event cannot damage the player.
    """
    start = cutoff - timedelta(days=WINDOW_DAYS)
    eligible = [
        row for row in observations if start <= row["event_date"] < cutoff
    ]
    if not eligible:
        return None, 0
    weighted_credit = 0.0
    total_weight = 0.0
    for row in eligible:
        weight = 0.5 ** (
            max(0, (cutoff - row["event_date"]).days) / 60.0
        )
        total_weight += weight
        if not row.get("won"):
            continue
        strength = _competition_strength(row.get("competition_level"))
        points = _COMPETITION_CHAMPION_POINTS.get(strength or 0, 100.0)
        weighted_credit += weight * points / _MAX_TOURNAMENT_POINTS
    return weighted_credit / total_weight if total_weight else None, len(eligible)


def _competition_level_average(
    observations: list[dict[str, Any]], *, start: date, end: date,
) -> tuple[float | None, int]:
    """Average competition level normalized to the Slam/Finals ceiling."""
    material = []
    for row in observations:
        if not start <= row["event_date"] < end:
            continue
        strength = _competition_strength(row.get("competition_level"))
        if strength is not None:
            material.append(float(strength) / 4.0)
    return (sum(material) / len(material), len(material)) if material else (None, 0)


def _recent_circuit_downshift(
    observations: list[dict[str, Any]], *, cutoff: date,
) -> tuple[float | None, dict[str, Any]]:
    """Penalize a supported circuit downgrade without rewarding mere entry."""
    recent_level, recent_sample = _competition_level_average(
        observations, start=cutoff - timedelta(days=WINDOW_DAYS), end=cutoff,
    )
    reference_level, reference_sample = _competition_level_average(
        observations,
        start=cutoff - timedelta(days=365),
        end=cutoff - timedelta(days=WINDOW_DAYS),
    )
    if recent_level is None or reference_level is None:
        return None, {
            "recent_sample": recent_sample,
            "reference_sample": reference_sample,
            "status": "INSUFFICIENT_BILATERAL_WINDOWS",
        }
    reliability = min(1.0, recent_sample / 4.0, reference_sample / 8.0)
    penalty = max(0.0, reference_level - recent_level) * reliability
    return penalty, {
        "recent_level": round(recent_level, 6),
        "reference_level": round(reference_level, 6),
        "recent_sample": recent_sample,
        "reference_sample": reference_sample,
        "reliability": round(reliability, 6),
        "penalty": round(penalty, 6),
        "status": "READY",
    }


def _tier_reliable_recent_features(
    observations_a: list[dict[str, Any]],
    observations_b: list[dict[str, Any]],
    *, cutoff: date, surface: str | None, target_level: Any,
    universe: str,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """Separate recent evidence by competition level and shrink tiny samples.

    A missing bucket is the neutral prior, not evidence against a player.  The
    three bucket coefficients are subsequently learned on chronological data;
    Challenger performance can inform an ATP match without being treated as
    equivalent to main-tour performance.
    """
    result: dict[str, float | None] = {}
    audit: dict[str, Any] = {
        "status": "READY",
        "full_reliability_from_matches": RECENT_RELIABILITY_MIN_MATCHES,
        "target_level": (
            None if target_level is None or pd.isna(target_level)
            else str(target_level).strip() or None
        ),
        "buckets": {},
    }
    start = cutoff - timedelta(days=WINDOW_DAYS)
    recent_a = [
        row for row in observations_a if start <= row["event_date"] < cutoff
    ]
    recent_b = [
        row for row in observations_b if start <= row["event_date"] < cutoff
    ]
    metrics = (
        ("result", "result_balance", "sample"),
        ("competitiveness", "game_margin_balance", "game_margin_sample"),
        ("win_quality", "win_opponent_strength", "wins_sample"),
    )
    for bucket in ("peer_higher", "lower_main", "challenger", "main"):
        selected_a = [
            row for row in recent_a
            if (
                _recent_competition_bucket(row, target_level=target_level) != "challenger"
                if bucket == "main"
                else _recent_competition_bucket(row, target_level=target_level) == bucket
            )
        ]
        selected_b = [
            row for row in recent_b
            if (
                _recent_competition_bucket(row, target_level=target_level) != "challenger"
                if bucket == "main"
                else _recent_competition_bucket(row, target_level=target_level) == bucket
            )
        ]
        summaries = {
            "a": _tier_recent_summary(selected_a, cutoff=cutoff),
            "b": _tier_recent_summary(selected_b, cutoff=cutoff),
        }
        bucket_audit: dict[str, Any] = {}
        for label, value_key, sample_key in metrics:
            summary_a = summaries["a"]
            summary_b = summaries["b"]
            if label == "win_quality":
                sample_a = int(summary_a.get(sample_key) or 0)
                sample_b = int(summary_b.get(sample_key) or 0)
                raw_a = summary_a.get(value_key)
                raw_b = summary_b.get(value_key)
                if sample_a and sample_b and raw_a is not None and raw_b is not None:
                    threshold = (
                        RECENT_MAIN_RELIABILITY_MIN_MATCHES
                        if bucket == "main" else RECENT_RELIABILITY_MIN_MATCHES
                    )
                    reliability = min(
                        min(1.0, sample_a / threshold),
                        min(1.0, sample_b / threshold),
                    )
                    margin = (float(raw_a) - float(raw_b)) * reliability
                    value_a, value_b = margin, 0.0
                else:
                    value_a = value_b = 0.0
            else:
                value_a, sample_a = _shrunk_recent_value(
                    summary_a, value_key, sample_key,
                    full_reliability_from=(
                        RECENT_MAIN_RELIABILITY_MIN_MATCHES
                        if bucket == "main" else RECENT_RELIABILITY_MIN_MATCHES
                    ),
                )
                value_b, sample_b = _shrunk_recent_value(
                    summary_b, value_key, sample_key,
                    full_reliability_from=(
                        RECENT_MAIN_RELIABILITY_MIN_MATCHES
                        if bucket == "main" else RECENT_RELIABILITY_MIN_MATCHES
                    ),
                )
            suffix = "v7" if bucket == "main" else "v5"
            feature = f"contextual_recent_{label}_{bucket}_{suffix}"
            result[feature] = (
                value_a - value_b
                if (sample_a and sample_b if label == "win_quality" else sample_a or sample_b)
                else None
            )
            bucket_audit[label] = {
                "a_sample": sample_a,
                "b_sample": sample_b,
                "a_shrunk": round(value_a, 6),
                "b_shrunk": round(value_b, 6),
            }
        audit["buckets"][bucket] = bucket_audit
    tier_credit_a, tier_credit_sample_a = _tier_win_credit_summary(
        recent_a, cutoff=cutoff,
    )
    tier_credit_b, tier_credit_sample_b = _tier_win_credit_summary(
        recent_b, cutoff=cutoff,
    )
    reliability = max(
        min(1.0, tier_credit_sample_a / RECENT_RELIABILITY_MIN_MATCHES),
        min(1.0, tier_credit_sample_b / RECENT_RELIABILITY_MIN_MATCHES),
    )
    result["contextual_recent_tier_win_credit_v7"] = (
        (float(tier_credit_a or 0.0) - float(tier_credit_b or 0.0))
        * reliability
        if tier_credit_sample_a or tier_credit_sample_b else None
    )
    audit["tier_win_credit"] = {
        "a_sample": tier_credit_sample_a,
        "b_sample": tier_credit_sample_b,
        "a_credit": round(float(tier_credit_a or 0.0), 6),
        "b_credit": round(float(tier_credit_b or 0.0), 6),
        "category_scale": "champion_points_over_2000",
        "challenger_default_points": 100,
    }
    downshift_a, downshift_audit_a = _recent_circuit_downshift(
        observations_a, cutoff=cutoff,
    )
    downshift_b, downshift_audit_b = _recent_circuit_downshift(
        observations_b, cutoff=cutoff,
    )
    result["contextual_recent_circuit_downshift_v8"] = (
        float(downshift_b or 0.0) - float(downshift_a or 0.0)
        if downshift_a is not None or downshift_b is not None else None
    )
    audit["circuit_downshift"] = {
        "a": downshift_audit_a,
        "b": downshift_audit_b,
        "direction": "positive_favours_a_when_b_has_larger_downshift",
        "upgrades_never_receive_positive_credit": True,
    }
    return result, audit


def _last_rank_change(history: list[tuple[date, float]], current: float | None) -> float | None:
    if current is None or not history:
        return None
    previous = history[-1][1]
    return math.log(previous / current) if previous > 0 else None


def _surface_record(
    observations: list[dict[str, Any]], surface: str | None,
) -> tuple[float | None, int]:
    rows = [row for row in observations if surface is not None and row["surface"] == surface]
    if not rows:
        return None, 0
    wins = sum(row["result"] > 0 for row in rows)
    return wins / len(rows), len(rows)


def _ledger_rate(ledger: dict[str, Any] | None, period: str) -> float | None:
    record = (ledger or {}).get(period)
    if not isinstance(record, dict) or not record.get("matches"):
        return None
    return float(record["wins"]) / float(record["matches"])


def _ledger_shrunk_rate(
    ledger: dict[str, Any] | None, period: str, *, prior_matches: float,
) -> float | None:
    record = (ledger or {}).get(period)
    if not isinstance(record, dict) or not record.get("matches"):
        return None
    return (
        float(record["wins"]) + 0.5 * float(prior_matches)
    ) / (float(record["matches"]) + float(prior_matches))


def _exact_surface_features(
    observations_a: list[dict[str, Any]],
    observations_b: list[dict[str, Any]],
    *,
    context: str | None,
    cutoff: date,
    tier_observations_a: list[dict[str, Any]] | None = None,
    tier_observations_b: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    names = (
        "exact_surface_career_margin_raw",
        "exact_surface_previous_margin_raw",
        "exact_surface_current_margin_raw",
        "exact_surface_career_margin_shrunk",
        "exact_surface_previous_margin_shrunk",
        "exact_surface_current_margin_shrunk",
        "exact_surface_tier_win_credit_career_v8",
        "exact_surface_tier_win_credit_previous_v8",
        "exact_surface_tier_win_credit_current_v8",
    )
    if context not in {
        "hard_outdoor", "hard_indoor", "clay", "grass",
    }:
        return {name: None for name in names}, {
            "status": "EXACT_CONTEXT_UNRESOLVED",
        }
    ledger_a = build_chronological_surface_ledger(
        observations_a, context=context, cutoff=cutoff,
    )
    ledger_b = build_chronological_surface_ledger(
        observations_b, context=context, cutoff=cutoff,
    )

    def tier_credit(
        observations: list[dict[str, Any]], period: str,
    ) -> tuple[float | None, int]:
        rows = [
            row for row in observations
            if row.get("surface_context") == context
            and row["event_date"] < cutoff
            and (
                period == "career"
                or period == "current_season" and row["event_date"].year == cutoff.year
                or period == "previous_season" and row["event_date"].year == cutoff.year - 1
            )
        ]
        if not rows:
            return None, 0
        credit = 0.0
        for row in rows:
            if not row.get("won"):
                continue
            strength = _competition_strength(row.get("competition_level"))
            points = _COMPETITION_CHAMPION_POINTS.get(strength or 0, 100.0)
            credit += points / _MAX_TOURNAMENT_POINTS
        return credit / len(rows), len(rows)

    tier_periods = ("career", "previous_season", "current_season")
    tier_source_a = observations_a if tier_observations_a is None else tier_observations_a
    tier_source_b = observations_b if tier_observations_b is None else tier_observations_b
    tier_a = {period: tier_credit(tier_source_a, period) for period in tier_periods}
    tier_b = {period: tier_credit(tier_source_b, period) for period in tier_periods}
    features = {
        names[0]: _difference(
            _ledger_rate(ledger_a, "career"), _ledger_rate(ledger_b, "career"),
        ),
        names[1]: _difference(
            _ledger_rate(ledger_a, "previous_season"),
            _ledger_rate(ledger_b, "previous_season"),
        ),
        names[2]: _difference(
            _ledger_rate(ledger_a, "current_season"),
            _ledger_rate(ledger_b, "current_season"),
        ),
        names[3]: _difference(
            _ledger_shrunk_rate(ledger_a, "career", prior_matches=10.0),
            _ledger_shrunk_rate(ledger_b, "career", prior_matches=10.0),
        ),
        names[4]: _difference(
            _ledger_shrunk_rate(
                ledger_a, "previous_season", prior_matches=8.0,
            ),
            _ledger_shrunk_rate(
                ledger_b, "previous_season", prior_matches=8.0,
            ),
        ),
        names[5]: _difference(
            _ledger_shrunk_rate(
                ledger_a, "current_season", prior_matches=8.0,
            ),
            _ledger_shrunk_rate(
                ledger_b, "current_season", prior_matches=8.0,
            ),
        ),
        names[6]: _difference(tier_a["career"][0], tier_b["career"][0]),
        names[7]: _difference(
            tier_a["previous_season"][0], tier_b["previous_season"][0],
        ),
        names[8]: _difference(
            tier_a["current_season"][0], tier_b["current_season"][0],
        ),
    }
    return features, {
        "status": "READY",
        "context": context,
        "a": ledger_a,
        "b": ledger_b,
        "tier_adjusted_win_credit": {
            "a": {key: {"credit": value[0], "sample": value[1]} for key, value in tier_a.items()},
            "b": {key: {"credit": value[0], "sample": value[1]} for key, value in tier_b.items()},
            "scale": "champion_points_over_2000_per_match",
            "mere_entry_never_receives_positive_credit": True,
        },
    }


def _record(rows: list[dict[str, Any]]) -> dict[str, int] | None:
    if not rows:
        return None
    wins = sum(row["result"] > 0 for row in rows)
    return {"matches": len(rows), "wins": wins, "losses": len(rows) - wins}


def _nearest_rank(
    history: list[tuple[date, float]], *, cutoff: date, days_ago: int,
    tolerance_days: int,
) -> float | None:
    target = cutoff - timedelta(days=days_ago)
    candidates = [
        (abs((observed - target).days), observed, rank)
        for observed, rank in history
        if abs((observed - target).days) <= tolerance_days
    ]
    return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _ranking_equation_context(
    *, current_rank: float | None, current_points: float | None,
    rank_history: list[tuple[date, float]],
    match_history: list[dict[str, Any]], cutoff: date,
) -> dict[str, Any]:
    ranked = [(day, rank) for day, rank in rank_history if day < cutoff and rank > 0]
    recent = [(day, rank) for day, rank in ranked if day >= cutoff - timedelta(days=365)]
    anchor_6m = _nearest_rank(
        ranked, cutoff=cutoff, days_ago=182, tolerance_days=60,
    )
    anchor_12m = _nearest_rank(
        ranked, cutoff=cutoff, days_ago=365, tolerance_days=90,
    )

    def change(anchor: float | None) -> float | None:
        return math.log(anchor / current_rank) if anchor and current_rank else None

    last_match = max(
        (row["event_date"] for row in match_history if row["event_date"] < cutoff),
        default=None,
    )
    weekly_summary = summarize_weekly_rank_history(
        [
            {"observed_at": day, "rank": rank}
            for day, rank in ranked
        ],
        cutoff=datetime.combine(cutoff, datetime.min.time(), tzinfo=timezone.utc),
        current_rank=current_rank,
    )
    days_since_last_match = (cutoff - last_match).days if last_match else None
    return_context = summarize_return_context(
        [
            {"observed_at": day, "rank": rank}
            for day, rank in ranked
        ],
        [row["event_date"] for row in match_history if row["event_date"] < cutoff],
        cutoff=datetime.combine(cutoff, datetime.min.time(), tzinfo=timezone.utc),
        days_since_last_match=days_since_last_match,
    )
    return {
        "current_rank": current_rank,
        "current_points": current_points,
        "historical_observation_count": len(ranked),
        "observed_peak_rank": min((rank for _, rank in ranked), default=None),
        "observed_best_rank_365d": min((rank for _, rank in recent), default=None),
        "ranking_strength_change_6m": change(anchor_6m),
        "ranking_strength_change_12m": change(anchor_12m),
        "days_since_last_match": days_since_last_match,
        **weekly_summary,
        **return_context,
    }


def _surface_equation_pair(
    *, observations_a: list[dict[str, Any]], observations_b: list[dict[str, Any]],
    cutoff: date, surface: str | None, venue: str | None, pace: str | None,
) -> dict[str, Any]:
    def context(observations: list[dict[str, Any]]) -> dict[str, Any]:
        same_surface = [row for row in observations if surface and row.get("surface") == surface]
        same_venue = [
            row for row in same_surface if venue and row.get("venue") == venue
        ]
        same_pace = [
            row for row in same_surface if pace and row.get("pace_bucket") == pace
        ]
        recent_35 = [
            row for row in observations
            if cutoff - timedelta(days=35) <= row["event_date"] < cutoff
        ]
        recent_surfaces = [
            row.get("surface") for row in recent_35
            if isinstance(row.get("surface"), str) and row.get("surface")
        ]
        counts = Counter(recent_surfaces)
        most_recent = recent_surfaces[-1] if recent_surfaces else None
        dominant = max(
            counts, key=lambda item: (counts[item], item == most_recent, item),
        ) if counts else None
        transition = bool(
            surface and dominant and dominant != surface
            and not any(row.get("surface") == surface for row in recent_35)
        )
        return {
            "surface": _record(same_surface),
            "venue": _record(same_venue),
            "pace": _record(same_pace),
            "transition": transition,
        }

    a, b = context(observations_a), context(observations_b)
    return {
        "status": "READY",
        "context_consistent": True,
        "surface_component": {"a": a["surface"], "b": b["surface"]},
        "venue_component": {"a": a["venue"], "b": b["venue"]},
        "pace_component": {"a": a["pace"], "b": b["pace"]},
        "transition_component": {"a": a["transition"], "b": b["transition"]},
    }


def _candidate_equation_features(
    *, rank_a: float | None, rank_b: float | None,
    points_a: float | None, points_b: float | None,
    rank_history_a: list[tuple[date, float]], rank_history_b: list[tuple[date, float]],
    match_history_a: list[dict[str, Any]], match_history_b: list[dict[str, Any]],
    cutoff: date, surface: str | None, venue: str | None, pace: str | None,
    universe: str, target_level: Any = None,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    context_a = _ranking_equation_context(
        current_rank=rank_a, current_points=points_a,
        rank_history=rank_history_a, match_history=match_history_a, cutoff=cutoff,
    )
    context_b = _ranking_equation_context(
        current_rank=rank_b, current_points=points_b,
        rank_history=rank_history_b, match_history=match_history_b, cutoff=cutoff,
    )
    structural = evaluate_structural_strength(context_a, context_b)
    structural_v2 = evaluate_structural_strength_v2(context_a, context_b)
    structural_v3 = evaluate_structural_strength_v3(context_a, context_b)
    structural_v4 = evaluate_structural_strength_v4(context_a, context_b)
    structural_v5 = evaluate_structural_strength_v5(context_a, context_b)
    structural_v6 = evaluate_structural_strength_v6(context_a, context_b)
    structural_v7 = evaluate_structural_strength_v7(context_a, context_b)
    tier_recent_features, tier_recent_audit = _tier_reliable_recent_features(
        match_history_a, match_history_b,
        cutoff=cutoff, surface=surface, target_level=target_level,
        universe=universe,
    )
    surface_result = evaluate_surface_conditions(_surface_equation_pair(
        observations_a=match_history_a, observations_b=match_history_b,
        cutoff=cutoff, surface=surface, venue=venue, pace=pace,
    ))
    surface_result_v2 = evaluate_surface_conditions_v2(_surface_equation_pair(
        observations_a=match_history_a, observations_b=match_history_b,
        cutoff=cutoff, surface=surface, venue=venue, pace=pace,
    ))
    surface_result_v3 = evaluate_surface_conditions_v3(_surface_equation_pair(
        observations_a=match_history_a, observations_b=match_history_b,
        cutoff=cutoff, surface=surface, venue=venue, pace=pace,
    ))
    recent_decays = RECENT_FORM_DECAYS_V1.get(str(universe).strip().casefold())
    recent_features: dict[str, float | None] = {}
    recent_audit: dict[str, Any]
    if recent_decays is None:
        recent_audit = {
            "status": "OBSERVATIONAL_UNIVERSE_ONLY",
            "reason": "ATP_WTA_DECAYS_NOT_AUTHORIZED",
        }
    else:
        summaries_a = {
            key: _summarize_player_history(
                match_history_a, cutoff=cutoff, target_surface=surface,
                half_life_days=half_life, window_days=WINDOW_DAYS,
            )
            for key, half_life in recent_decays.items()
        }
        summaries_b = {
            key: _summarize_player_history(
                match_history_b, cutoff=cutoff, target_surface=surface,
                half_life_days=half_life, window_days=WINDOW_DAYS,
            )
            for key, half_life in recent_decays.items()
        }
        recent_features = {
            "contextual_recent_result_core_v1": _difference(
                summaries_a["result"]["result_balance"],
                summaries_b["result"]["result_balance"],
            ),
            "contextual_recent_competitiveness_v1": _difference(
                summaries_a["competitiveness"]["game_margin_balance"],
                summaries_b["competitiveness"]["game_margin_balance"],
            ),
            "contextual_recent_win_quality_v1": _difference(
                summaries_a["win_quality"]["win_opponent_strength"],
                summaries_b["win_quality"]["win_opponent_strength"],
            ),
            "contextual_recent_loss_context_v1": _difference(
                summaries_a["loss_context"]["loss_opponent_strength"],
                summaries_b["loss_context"]["loss_opponent_strength"],
            ),
            # Positive favours A: B has accumulated the larger penalty from
            # defeats against structurally weaker opponents.
            "contextual_recent_bad_loss_penalty_v2": _difference(
                summaries_b["loss_context"]["bad_loss_penalty"],
                summaries_a["loss_context"]["bad_loss_penalty"],
            ),
        }
        for alpha in RECENT_LOSS_CONTEXT_GRID_V2:
            def adjusted(
                result_summary: dict[str, Any], loss_summary: dict[str, Any],
            ) -> float | None:
                return adjust_recent_result_for_loss_context(
                    result_summary.get("result_balance"),
                    bad_loss_penalty=loss_summary.get("bad_loss_penalty"),
                    strong_loss_relief=loss_summary.get("strong_loss_relief"),
                    alpha=alpha,
                )

            recent_features[recent_loss_context_feature(alpha)] = _difference(
                adjusted(summaries_a["result"], summaries_a["loss_context"]),
                adjusted(summaries_b["result"], summaries_b["loss_context"]),
            )
        recent_audit = {
            "status": "READY",
            "equation_stage": "COMPONENTS_ONLY",
            "decay_days": {
                key: (90 if value is None else value)
                for key, value in recent_decays.items()
            },
            "uniform_result_window": recent_decays["result"] is None,
            "loss_context_rule": (
                "diagnostic only; strong losses may reduce a penalty but must "
                "not create standalone positive credit"
            ),
            "bad_loss_rule": (
                "only losses against a lower-ranked opponent are penalized; "
                "strong-opponent losses contribute zero"
            ),
            "capped_loss_context_grid": list(RECENT_LOSS_CONTEXT_GRID_V2),
            "strong_loss_relief_cannot_cross_zero": True,
            "same_surface_excluded_to_avoid_double_counting": True,
        }
    features = {
        "contextual_structural_signal_v1": structural.get("family_signal"),
        "contextual_structural_signal_v2": structural_v2.get("family_signal"),
        "contextual_surface_signal_v1": surface_result.get("family_signal"),
        "contextual_surface_signal_v2": surface_result_v2.get("family_signal"),
        "contextual_surface_signal_v3": surface_result_v3.get("family_signal"),
        **recent_features,
        **tier_recent_features,
    }
    features.update(structural_v3.get("candidate_features", {}))
    features.update(structural_v4.get("candidate_features", {}))
    features.update(structural_v5.get("candidate_features", {}))
    features.update(structural_v6.get("candidate_features", {}))
    features.update(structural_v7.get("candidate_features", {}))
    return features, {
        "structural_strength": structural,
        "structural_strength_v2": structural_v2,
        "structural_strength_v3": structural_v3,
        "structural_strength_v4": structural_v4,
        "structural_strength_v5": structural_v5,
        "structural_strength_v6": structural_v6,
        "structural_strength_v7": structural_v7,
        "surface_conditions": surface_result,
        "surface_conditions_v2": surface_result_v2,
        "surface_conditions_v3": surface_result_v3,
        "recent_form_v1": recent_audit,
        "recent_form_tier_reliable_v5": tier_recent_audit,
    }


def _h2h_feature(
    rows: list[dict[str, Any]], *, player_a: str, surface: str | None,
) -> tuple[float | None, float | None, int, int]:
    if not rows:
        return None, None, 0, 0
    a_wins = sum(row["winner"] == player_a for row in rows)
    global_margin = 2.0 * a_wins / len(rows) - 1.0
    same = [row for row in rows if surface is not None and row["surface"] == surface]
    if same:
        same_a_wins = sum(row["winner"] == player_a for row in same)
        surface_margin = 2.0 * same_a_wins / len(same) - 1.0
    else:
        surface_margin = None
    return global_margin, surface_margin, len(rows), len(same)


def apply_h2h_override(
    row: dict[str, Any], override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Reconcile the model H2H with a more complete factual provider sample.

    Non-competitive/exhibition rows remain factual audit evidence but never
    vote in the contextual family.  A provider failure leaves the local,
    chronological sample untouched.
    """
    if not override:
        return row
    total = int(override.get("eligible_matches") or 0)
    current = int((row.get("samples") or {}).get("h2h") or 0)
    if total < current or total <= 0:
        return row
    a_wins = int(override.get("eligible_a_wins") or 0)
    surface_total = int(override.get("eligible_surface_matches") or 0)
    surface_a_wins = int(override.get("eligible_surface_a_wins") or 0)
    features = row.setdefault("features", {})
    global_margin = 2.0 * a_wins / total - 1.0
    surface_margin = (
        2.0 * surface_a_wins / surface_total - 1.0
        if surface_total > 0 else None
    )
    features["h2h_win_share_margin"] = global_margin
    features["same_surface_h2h_win_share_margin"] = surface_margin
    features["contextual_h2h_global_shrunk_v1"] = (
        global_margin * total / (total + 2.0)
    )
    row.setdefault("samples", {}).update({
        "h2h": total,
        "same_surface_h2h": surface_total,
    })
    row.setdefault("family_states", {})["matchup_h2h"] = {
        "data_state": "OBSERVED", "signal_state": "AVAILABLE",
    }
    row.setdefault("candidate_equation_audit", {})["matchup_h2h"] = {
        **dict(override),
        "local_eligible_matches_before_reconciliation": current,
        "source_selected_for_model": str(override.get("source") or "provider_h2h"),
    }
    return row


def _service_view(
    observations: list[dict[str, Any]], *, cutoff: date, surface: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    surface_rows = [
        row for row in observations
        if surface is not None and row.get("surface") == surface
    ]
    start = cutoff - timedelta(days=WINDOW_DAYS)
    recent_rows = [row for row in observations if start <= row["event_date"] < cutoff]
    recent_surface = [
        row for row in recent_rows
        if surface is not None and row.get("surface") == surface
    ]
    return _aggregate(surface_rows), _aggregate(recent_surface or recent_rows)


def _metric_margin(
    a: dict[str, Any] | None, b: dict[str, Any] | None, key: str,
) -> float | None:
    return _difference((a or {}).get(key), (b or {}).get(key))


def _metric_margin_shrunk(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
    key: str,
    sample_key: str,
    *,
    prior_sample: float,
) -> float | None:
    margin = _metric_margin(a, b, key)
    sample_a = _positive_rank((a or {}).get(sample_key))
    sample_b = _positive_rank((b or {}).get(sample_key))
    if margin is None or sample_a is None or sample_b is None:
        return None
    reliability = min(
        sample_a / (sample_a + prior_sample),
        sample_b / (sample_b + prior_sample),
    )
    return margin * reliability


def _recent_metric_deviation(
    surface_a: dict[str, Any] | None,
    surface_b: dict[str, Any] | None,
    recent_a: dict[str, Any] | None,
    recent_b: dict[str, Any] | None,
    key: str,
    sample_key: str,
    *,
    prior_sample: float,
) -> float | None:
    surface_margin = _metric_margin(surface_a, surface_b, key)
    recent_margin = _metric_margin(recent_a, recent_b, key)
    recent_sample_a = _positive_rank((recent_a or {}).get(sample_key))
    recent_sample_b = _positive_rank((recent_b or {}).get(sample_key))
    if (
        surface_margin is None or recent_margin is None
        or recent_sample_a is None or recent_sample_b is None
    ):
        return None
    reliability = min(
        recent_sample_a / (recent_sample_a + prior_sample),
        recent_sample_b / (recent_sample_b + prior_sample),
    )
    return (recent_margin - surface_margin) * reliability


def _family_payloads(
    *, recent_a: dict[str, Any], recent_b: dict[str, Any],
    rank_a: float | None, rank_b: float | None,
    surface_sample_a: int, surface_sample_b: int,
    h2h_sample: int, service_a: dict[str, Any] | None,
    service_b: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    return {
        "recent_form": {
            "status": "AVAILABLE" if recent_a["sample"] and recent_b["sample"]
            else "INSUFFICIENT_SAMPLE",
        },
        "structural_strength": {
            "status": "BILATERAL" if rank_a and rank_b else "PARTIAL",
        },
        "surface_conditions": {
            "status": "READY" if surface_sample_a and surface_sample_b
            else "INSUFFICIENT_SAMPLE",
        },
        "matchup_h2h": {
            "status": "AVAILABLE" if h2h_sample else "OBSERVED_NONE",
        },
        "serve_return": {
            "status": "READY" if service_a and service_b else "INSUFFICIENT_SAMPLE",
        },
    }


def build_contextual_target_row(
    frame: pd.DataFrame,
    *,
    universe: str,
    player_a: str,
    player_b: str,
    cutoff: date,
    surface: str | None,
    rank_a: float | None,
    rank_b: float | None,
    points_a: float | None = None,
    points_b: float | None = None,
    venue: str | None = None,
    pace_bucket: str | None = None,
    target_tier: str | None = None,
) -> dict[str, Any]:
    """Build one future, market-free row with the exact replay definitions.

    Only completed matches strictly before ``cutoff`` are visible.  The
    alphabetical model orientation is returned explicitly so callers can map
    it back to the provider's left/right orientation without changing the
    learned equation.
    """
    names = {_name_key(player_a): (player_a, rank_a), _name_key(player_b): (player_b, rank_b)}
    if None in names or "" in names or len(names) != 2:
        raise ValueError("two distinct resolved player names are required")
    model_a, model_b = sorted(names)
    current_ranks = {key: _positive_rank(value[1]) for key, value in names.items()}
    target_surface = _surface(surface)
    target_venue = _surface_venue(venue)
    target_surface_context = exact_surface_context(
        surface, venue=target_venue,
    )
    target_pace = _surface_pace(pace_bucket)
    material = _cached_material(frame)
    material = material[material["_event_date"] < cutoff]

    match_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    primary_match_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rank_history: dict[str, list[tuple[date, float]]] = defaultdict(list)
    service_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pair_history: list[dict[str, Any]] = []
    wanted = {model_a, model_b}
    material = material[
        material["_winner_key"].isin(wanted)
        | material["_loser_key"].isin(wanted)
    ]
    for _, match in material.iterrows():
        if bool(match["_non_standard"]):
            continue
        winner, loser = _name_key(match["_winner"]), _name_key(match["_loser"])
        if not winner or not loser or winner == loser:
            continue
        event_date, match_surface = match["_event_date"], match["_surface"]
        competition_scope = match["_competition_scope"]
        competition_level = match["_competition_level"]
        is_primary = "challenger" not in str(competition_scope)
        match_surface_context = match["_surface_context"]
        match_venue, match_pace = match["_venue"], match["_pace"]
        rank_w = _positive_rank(match["_winner_rank"])
        rank_l = _positive_rank(match["_loser_rank"])
        winner_margin = _game_margin(match["_score"], won=True)
        loser_margin = -winner_margin if winner_margin is not None else None
        if winner in wanted:
            observation = {**_player_observation(
                event_date=event_date, surface=match_surface, won=True,
                player_rank=rank_w, opponent_rank=rank_l, game_margin=winner_margin,
                competition_scope=competition_scope,
                competition_level=competition_level,
            ), "venue": match_venue, "pace_bucket": match_pace,
                "surface_context": match_surface_context}
            match_history[winner].append(observation)
            if is_primary:
                primary_match_history[winner].append(observation)
            if rank_w:
                rank_history[winner].append((event_date, rank_w))
            service = _extract_match(match, player_won=True)
            if service is not None and is_primary:
                service_history[winner].append({
                    **service, "event_date": event_date, "surface": match_surface,
                })
        if loser in wanted:
            observation = {**_player_observation(
                event_date=event_date, surface=match_surface, won=False,
                player_rank=rank_l, opponent_rank=rank_w, game_margin=loser_margin,
                competition_scope=competition_scope,
                competition_level=competition_level,
            ), "venue": match_venue, "pace_bucket": match_pace,
                "surface_context": match_surface_context}
            match_history[loser].append(observation)
            if is_primary:
                primary_match_history[loser].append(observation)
            if rank_l:
                rank_history[loser].append((event_date, rank_l))
            service = _extract_match(match, player_won=False)
            if service is not None and is_primary:
                service_history[loser].append({
                    **service, "event_date": event_date, "surface": match_surface,
                })
        if is_primary and {winner, loser} == wanted:
            pair_history.append({
                "event_date": event_date, "surface": match_surface, "winner": winner,
                "surface_context": match_surface_context,
                "tournament": _optional_text(match["_tournament"]),
                "score": _optional_text(match["_score"]),
                "round": _optional_text(match["_round"]),
            })

    recent_a = _summarize_player_history(
        match_history[model_a], cutoff=cutoff, target_surface=target_surface,
        half_life_days=None, window_days=WINDOW_DAYS,
    )
    recent_b = _summarize_player_history(
        match_history[model_b], cutoff=cutoff, target_surface=target_surface,
        half_life_days=None, window_days=WINDOW_DAYS,
    )
    surface_rate_a, surface_sample_a = _surface_record(primary_match_history[model_a], target_surface)
    surface_rate_b, surface_sample_b = _surface_record(primary_match_history[model_b], target_surface)
    h2h_global, h2h_surface, h2h_sample, h2h_surface_sample = _h2h_feature(
        pair_history, player_a=model_a, surface=target_surface,
    )
    service_surface_a, service_recent_a = _service_view(
        service_history[model_a], cutoff=cutoff, surface=target_surface,
    )
    service_surface_b, service_recent_b = _service_view(
        service_history[model_b], cutoff=cutoff, surface=target_surface,
    )
    exact_surface_features, exact_surface_audit = _exact_surface_features(
        primary_match_history[model_a], primary_match_history[model_b],
        context=target_surface_context, cutoff=cutoff,
        tier_observations_a=match_history[model_a],
        tier_observations_b=match_history[model_b],
    )
    model_rank_a, model_rank_b = current_ranks[model_a], current_ranks[model_b]
    candidate_features, equation_audit = _candidate_equation_features(
        rank_a=model_rank_a, rank_b=model_rank_b,
        points_a=points_a if _name_key(player_a) == model_a else points_b,
        points_b=points_b if _name_key(player_b) == model_b else points_a,
        rank_history_a=rank_history[model_a], rank_history_b=rank_history[model_b],
        match_history_a=match_history[model_a], match_history_b=match_history[model_b],
        cutoff=cutoff, surface=target_surface, venue=target_venue, pace=target_pace,
        universe=universe, target_level=target_tier,
    )
    features = {
        "recent_result_balance_90d": _difference(recent_a["result_balance"], recent_b["result_balance"]),
        "recent_game_margin_balance_90d": _difference(recent_a["game_margin_balance"], recent_b["game_margin_balance"]),
        "recent_win_opponent_strength_90d": _difference(recent_a["win_opponent_strength"], recent_b["win_opponent_strength"]),
        "recent_loss_opponent_strength_90d": _difference(recent_a["loss_opponent_strength"], recent_b["loss_opponent_strength"]),
        "current_rank_log_ratio": math.log(model_rank_b / model_rank_a) if model_rank_a and model_rank_b else None,
        "rank_change_from_last_observation": _difference(
            _last_rank_change(rank_history[model_a], model_rank_a),
            _last_rank_change(rank_history[model_b], model_rank_b),
        ),
        "same_surface_result_balance_90d": _difference(recent_a["same_surface_result_balance"], recent_b["same_surface_result_balance"]),
        "career_surface_win_rate_margin": _difference(surface_rate_a, surface_rate_b),
        "h2h_win_share_margin": h2h_global,
        "same_surface_h2h_win_share_margin": h2h_surface,
        "contextual_h2h_global_shrunk_v1": (
            h2h_global * h2h_sample / (h2h_sample + 2.0)
            if h2h_global is not None and h2h_sample > 0 else None
        ),
        "service_points_won_surface_margin": _metric_margin(service_surface_a, service_surface_b, "service_points_won_pct"),
        "return_points_won_surface_margin": _metric_margin(service_surface_a, service_surface_b, "return_points_won_pct"),
        "hold_surface_margin": _metric_margin(service_surface_a, service_surface_b, "hold_pct"),
        "break_surface_margin": _metric_margin(service_surface_a, service_surface_b, "break_pct"),
        "service_points_won_recent_margin": _metric_margin(service_recent_a, service_recent_b, "service_points_won_pct"),
        "return_points_won_recent_margin": _metric_margin(service_recent_a, service_recent_b, "return_points_won_pct"),
        "service_points_won_surface_margin_shrunk_v1": _metric_margin_shrunk(
            service_surface_a, service_surface_b,
            "service_points_won_pct", "service_points_sample",
            prior_sample=1_000.0,
        ),
        "return_points_won_surface_margin_shrunk_v1": _metric_margin_shrunk(
            service_surface_a, service_surface_b,
            "return_points_won_pct", "return_points_sample",
            prior_sample=1_000.0,
        ),
        "hold_surface_margin_shrunk_v1": _metric_margin_shrunk(
            service_surface_a, service_surface_b,
            "hold_pct", "service_games_sample", prior_sample=100.0,
        ),
        "break_surface_margin_shrunk_v1": _metric_margin_shrunk(
            service_surface_a, service_surface_b,
            "break_pct", "return_games_sample", prior_sample=100.0,
        ),
        "service_points_won_recent_deviation_v1": _recent_metric_deviation(
            service_surface_a, service_surface_b, service_recent_a, service_recent_b,
            "service_points_won_pct", "service_points_sample", prior_sample=500.0,
        ),
        "return_points_won_recent_deviation_v1": _recent_metric_deviation(
            service_surface_a, service_surface_b, service_recent_a, service_recent_b,
            "return_points_won_pct", "return_points_sample", prior_sample=500.0,
        ),
        **exact_surface_features,
        **candidate_features,
    }
    vector = build_contextual_family_vector(_family_payloads(
        recent_a=recent_a, recent_b=recent_b, rank_a=model_rank_a, rank_b=model_rank_b,
        surface_sample_a=surface_sample_a, surface_sample_b=surface_sample_b,
        h2h_sample=h2h_sample, service_a=service_surface_a or service_recent_a,
        service_b=service_surface_b or service_recent_b,
    ))
    return {
        "event_date": cutoff.isoformat(), "date_source": "prospective_cutoff",
        "universe": str(universe).strip().casefold(),
        "player_a": model_a, "player_b": model_b, "target_a_win": False,
        "surface": target_surface, "features": features,
        "diagnostics": {
            "rank_a": model_rank_a, "rank_b": model_rank_b,
            "venue": target_venue, "pace": target_pace,
            "surface_context": target_surface_context,
            "target_tier": target_tier,
        },
        "samples": {
            "recent_a": recent_a["sample"], "recent_b": recent_b["sample"],
            "surface_a": surface_sample_a, "surface_b": surface_sample_b,
            "h2h": h2h_sample, "same_surface_h2h": h2h_surface_sample,
            "service_surface_a": (service_surface_a or {}).get("matches", 0),
            "service_surface_b": (service_surface_b or {}).get("matches", 0),
            "exact_surface_career_a": (
                (exact_surface_audit.get("a") or {}).get("career") or {}
            ).get("matches", 0),
            "exact_surface_career_b": (
                (exact_surface_audit.get("b") or {}).get("career") or {}
            ).get("matches", 0),
        },
        "family_states": {
            row["key"]: {"data_state": row["data_state"], "signal_state": row["signal_state"]}
            for row in vector["families"]
        },
        "candidate_equation_audit": {
            **equation_audit,
            "matchup_h2h": {
                "source": "chronological_history",
                "raw_matches": h2h_sample,
                "eligible_matches": h2h_sample,
                "eligible_a_wins": sum(
                    row["winner"] == model_a for row in pair_history
                ),
                "eligible_surface_matches": h2h_surface_sample,
                "eligible_surface_a_wins": sum(
                    row["winner"] == model_a
                    for row in pair_history
                    if target_surface is not None
                    and row.get("surface") == target_surface
                ),
                "excluded_non_competitive": 0,
                "matches": [
                    {
                        "event_date": row["event_date"].isoformat(),
                        "tournament": row.get("tournament"),
                        "surface": row.get("surface_context") or row.get("surface"),
                        "winner_side": (
                            "a" if row["winner"] == model_a else "b"
                        ),
                        "score": row.get("score"),
                        "round": row.get("round"),
                    }
                    for row in sorted(
                        pair_history,
                        key=lambda item: item["event_date"],
                        reverse=True,
                    )
                ],
            },
            "exact_surface_ledger": exact_surface_audit,
        },
        "orientation": {
            "model_a_input_side": "a" if _name_key(player_a) == model_a else "b",
            "model_b_input_side": "b" if _name_key(player_b) == model_b else "a",
        },
        "market_used": False,
    }


def build_contextual_family_replay_rows(
    frame: pd.DataFrame, *, universe: str, target_scope: str | None = None,
) -> list[dict[str, Any]]:
    """Build ex-ante rows; an entire event date is evaluated before ingestion."""
    material = _material(frame)
    match_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    primary_match_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rank_history: dict[str, list[tuple[date, float]]] = defaultdict(list)
    service_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pair_history: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    replay: list[dict[str, Any]] = []

    for event_date, day in material.groupby("_event_date", sort=True):
        for _, match in day.iterrows():
            if bool(match["_non_standard"]):
                continue
            if (
                target_scope is not None
                and str(match["_competition_scope"]) != str(target_scope).casefold()
            ):
                continue
            winner = _name_key(match["_winner"])
            loser = _name_key(match["_loser"])
            if not winner or not loser or winner == loser:
                continue
            player_a, player_b = sorted((winner, loser))
            a_won = winner == player_a
            surface = match["_surface"]
            surface_context = match["_surface_context"]
            venue = match["_venue"]
            pace = match["_pace"]
            target_level = match["_competition_level"]
            rank_w = _positive_rank(match["_winner_rank"])
            rank_l = _positive_rank(match["_loser_rank"])
            points_w = _positive_rank(match["_winner_points"])
            points_l = _positive_rank(match["_loser_points"])
            rank_a = rank_w if a_won else rank_l
            rank_b = rank_l if a_won else rank_w
            points_a = points_w if a_won else points_l
            points_b = points_l if a_won else points_w

            recent_a = _summarize_player_history(
                match_history[player_a], cutoff=event_date, target_surface=surface,
                half_life_days=None, window_days=WINDOW_DAYS,
            )
            recent_b = _summarize_player_history(
                match_history[player_b], cutoff=event_date, target_surface=surface,
                half_life_days=None, window_days=WINDOW_DAYS,
            )
            surface_rate_a, surface_sample_a = _surface_record(
                primary_match_history[player_a], surface,
            )
            surface_rate_b, surface_sample_b = _surface_record(
                primary_match_history[player_b], surface,
            )
            h2h_global, h2h_surface, h2h_sample, h2h_surface_sample = _h2h_feature(
                pair_history[(player_a, player_b)], player_a=player_a, surface=surface,
            )
            service_surface_a, service_recent_a = _service_view(
                service_history[player_a], cutoff=event_date, surface=surface,
            )
            service_surface_b, service_recent_b = _service_view(
                service_history[player_b], cutoff=event_date, surface=surface,
            )
            exact_surface_features, exact_surface_audit = _exact_surface_features(
                primary_match_history[player_a], primary_match_history[player_b],
                context=surface_context, cutoff=event_date,
                tier_observations_a=match_history[player_a],
                tier_observations_b=match_history[player_b],
            )

            candidate_features, equation_audit = _candidate_equation_features(
                rank_a=rank_a, rank_b=rank_b, points_a=points_a, points_b=points_b,
                rank_history_a=rank_history[player_a],
                rank_history_b=rank_history[player_b],
                match_history_a=match_history[player_a],
                match_history_b=match_history[player_b],
                cutoff=event_date, surface=surface, venue=venue, pace=pace,
                universe=universe, target_level=target_level,
            )
            features = {
                "recent_result_balance_90d": _difference(
                    recent_a["result_balance"], recent_b["result_balance"],
                ),
                "recent_game_margin_balance_90d": _difference(
                    recent_a["game_margin_balance"], recent_b["game_margin_balance"],
                ),
                "recent_win_opponent_strength_90d": _difference(
                    recent_a["win_opponent_strength"], recent_b["win_opponent_strength"],
                ),
                "recent_loss_opponent_strength_90d": _difference(
                    recent_a["loss_opponent_strength"], recent_b["loss_opponent_strength"],
                ),
                "current_rank_log_ratio": (
                    math.log(rank_b / rank_a) if rank_a and rank_b else None
                ),
                "rank_change_from_last_observation": _difference(
                    _last_rank_change(rank_history[player_a], rank_a),
                    _last_rank_change(rank_history[player_b], rank_b),
                ),
                "same_surface_result_balance_90d": _difference(
                    recent_a["same_surface_result_balance"],
                    recent_b["same_surface_result_balance"],
                ),
                "career_surface_win_rate_margin": _difference(surface_rate_a, surface_rate_b),
                "h2h_win_share_margin": h2h_global,
                "same_surface_h2h_win_share_margin": h2h_surface,
                "contextual_h2h_global_shrunk_v1": (
                    h2h_global * h2h_sample / (h2h_sample + 2.0)
                    if h2h_global is not None and h2h_sample > 0 else None
                ),
                "service_points_won_surface_margin": _metric_margin(
                    service_surface_a, service_surface_b, "service_points_won_pct",
                ),
                "return_points_won_surface_margin": _metric_margin(
                    service_surface_a, service_surface_b, "return_points_won_pct",
                ),
                "hold_surface_margin": _metric_margin(
                    service_surface_a, service_surface_b, "hold_pct",
                ),
                "break_surface_margin": _metric_margin(
                    service_surface_a, service_surface_b, "break_pct",
                ),
                "service_points_won_recent_margin": _metric_margin(
                    service_recent_a, service_recent_b, "service_points_won_pct",
                ),
                "return_points_won_recent_margin": _metric_margin(
                    service_recent_a, service_recent_b, "return_points_won_pct",
                ),
                "service_points_won_surface_margin_shrunk_v1": _metric_margin_shrunk(
                    service_surface_a, service_surface_b,
                    "service_points_won_pct", "service_points_sample",
                    prior_sample=1_000.0,
                ),
                "return_points_won_surface_margin_shrunk_v1": _metric_margin_shrunk(
                    service_surface_a, service_surface_b,
                    "return_points_won_pct", "return_points_sample",
                    prior_sample=1_000.0,
                ),
                "hold_surface_margin_shrunk_v1": _metric_margin_shrunk(
                    service_surface_a, service_surface_b,
                    "hold_pct", "service_games_sample", prior_sample=100.0,
                ),
                "break_surface_margin_shrunk_v1": _metric_margin_shrunk(
                    service_surface_a, service_surface_b,
                    "break_pct", "return_games_sample", prior_sample=100.0,
                ),
                "service_points_won_recent_deviation_v1": _recent_metric_deviation(
                    service_surface_a, service_surface_b,
                    service_recent_a, service_recent_b,
                    "service_points_won_pct", "service_points_sample",
                    prior_sample=500.0,
                ),
                "return_points_won_recent_deviation_v1": _recent_metric_deviation(
                    service_surface_a, service_surface_b,
                    service_recent_a, service_recent_b,
                    "return_points_won_pct", "return_points_sample",
                    prior_sample=500.0,
                ),
                **exact_surface_features,
                **candidate_features,
            }
            vector = build_contextual_family_vector(_family_payloads(
                recent_a=recent_a, recent_b=recent_b, rank_a=rank_a, rank_b=rank_b,
                surface_sample_a=surface_sample_a, surface_sample_b=surface_sample_b,
                h2h_sample=h2h_sample, service_a=service_surface_a or service_recent_a,
                service_b=service_surface_b or service_recent_b,
            ))
            replay.append({
                "event_date": event_date.isoformat(),
                "date_source": match["_date_source"],
                "universe": str(universe).strip().casefold(),
                "player_a": player_a,
                "player_b": player_b,
                "target_a_win": a_won,
                "surface": surface,
                "diagnostics": {
                    "rank_a": rank_a, "rank_b": rank_b,
                    "venue": venue, "pace": pace,
                    "surface_context": surface_context,
                    "target_tier": target_level,
                },
                "features": features,
                "samples": {
                    "recent_a": recent_a["sample"], "recent_b": recent_b["sample"],
                    "surface_a": surface_sample_a, "surface_b": surface_sample_b,
                    "h2h": h2h_sample, "same_surface_h2h": h2h_surface_sample,
                    "service_surface_a": (service_surface_a or {}).get("matches", 0),
                    "service_surface_b": (service_surface_b or {}).get("matches", 0),
                    "exact_surface_career_a": (
                        (exact_surface_audit.get("a") or {}).get("career") or {}
                    ).get("matches", 0),
                    "exact_surface_career_b": (
                        (exact_surface_audit.get("b") or {}).get("career") or {}
                    ).get("matches", 0),
                },
                "family_states": {
                    row["key"]: {
                        "data_state": row["data_state"],
                        "signal_state": row["signal_state"],
                    }
                    for row in vector["families"]
                },
                "candidate_equation_audit": {
                    **equation_audit,
                    "exact_surface_ledger": exact_surface_audit,
                },
                "market_used": False,
            })

        # Only now may matches from this date enter later targets.
        for _, match in day.iterrows():
            if bool(match["_non_standard"]):
                continue
            winner = _name_key(match["_winner"])
            loser = _name_key(match["_loser"])
            if not winner or not loser or winner == loser:
                continue
            surface = match["_surface"]
            surface_context = match["_surface_context"]
            venue = match["_venue"]
            pace = match["_pace"]
            competition_scope = match["_competition_scope"]
            competition_level = match["_competition_level"]
            is_primary = "challenger" not in str(competition_scope)
            rank_w = _positive_rank(match["_winner_rank"])
            rank_l = _positive_rank(match["_loser_rank"])
            winner_margin = _game_margin(match["_score"], won=True)
            loser_margin = -winner_margin if winner_margin is not None else None
            winner_observation = {**_player_observation(
                event_date=event_date, surface=surface, won=True,
                player_rank=rank_w, opponent_rank=rank_l, game_margin=winner_margin,
                competition_scope=competition_scope,
                competition_level=competition_level,
            ), "venue": venue, "pace_bucket": pace,
                "surface_context": surface_context}
            loser_observation = {**_player_observation(
                event_date=event_date, surface=surface, won=False,
                player_rank=rank_l, opponent_rank=rank_w, game_margin=loser_margin,
                competition_scope=competition_scope,
                competition_level=competition_level,
            ), "venue": venue, "pace_bucket": pace,
                "surface_context": surface_context}
            match_history[winner].append(winner_observation)
            match_history[loser].append(loser_observation)
            if is_primary:
                primary_match_history[winner].append(winner_observation)
                primary_match_history[loser].append(loser_observation)
            if rank_w:
                rank_history[winner].append((event_date, rank_w))
            if rank_l:
                rank_history[loser].append((event_date, rank_l))
            for player, won in ((winner, True), (loser, False)):
                service = _extract_match(match, player_won=won)
                if service is not None and is_primary:
                    service_history[player].append({
                        **service, "event_date": event_date, "surface": surface,
                    })
            if is_primary:
                pair = tuple(sorted((winner, loser)))
                pair_history[pair].append({
                    "event_date": event_date, "surface": surface, "winner": winner,
                })
    return replay


def _split(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    dates = sorted({row["event_date"] for row in rows})
    if len(dates) < 5:
        return {"train": rows, "validation": [], "holdout": []}
    counts = {day: sum(row["event_date"] == day for row in rows) for day in dates}
    limits = (len(rows) * 0.60, len(rows) * 0.80)
    buckets: dict[str, set[str]] = {"train": set(), "validation": set(), "holdout": set()}
    cumulative = 0
    for day in dates:
        bucket = "train" if cumulative < limits[0] else "validation" if cumulative < limits[1] else "holdout"
        buckets[bucket].add(day)
        cumulative += counts[day]
    return {
        name: [row for row in rows if row["event_date"] in wanted]
        for name, wanted in buckets.items()
    }


def _direction_metric(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    material = [row for row in rows if row["features"].get(feature) is not None]
    correct = incorrect = ties = 0
    for row in material:
        value = float(row["features"][feature])
        if abs(value) <= 1e-12:
            ties += 1
        elif (value > 0) == bool(row["target_a_win"]):
            correct += 1
        else:
            incorrect += 1
    accuracy = (
        100.0 * (correct + 0.5 * ties) / len(material) if material else None
    )
    return {
        "targets": len(rows),
        "covered": len(material),
        "coverage_pct": round(100.0 * len(material) / max(1, len(rows)), 2),
        "correct": correct,
        "incorrect": incorrect,
        "ties": ties,
        "directional_accuracy_with_half_ties_pct": (
            round(accuracy, 2) if accuracy is not None else None
        ),
    }


def evaluate_contextual_family_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "INSUFFICIENT", "targets": 0, "features": {}}
    split = _split(rows)
    features = {
        feature: {
            "family": family,
            "orientation": "positive favours player_a",
            "partitions": {
                name: _direction_metric(part, feature) for name, part in split.items()
            },
        }
        for feature, family in FEATURE_FAMILIES.items()
    }
    family_coverage = {}
    for family in {value for value in FEATURE_FAMILIES.values()}:
        family_features = [key for key, value in FEATURE_FAMILIES.items() if value == family]
        family_coverage[family] = {
            name: {
                "targets": len(part),
                "with_any_component": sum(
                    any(row["features"].get(key) is not None for key in family_features)
                    for row in part
                ),
            }
            for name, part in split.items()
        }
    return {
        "status": "OBSERVATIONAL_ONLY",
        "targets": len(rows),
        "date_range": [rows[0]["event_date"], rows[-1]["event_date"]],
        "split_targets": {name: len(part) for name, part in split.items()},
        "player_orientation": "alphabetical_name_order_independent_of_result",
        "same_day_policy": "whole event date evaluated before ingestion",
        "features": features,
        "family_coverage": family_coverage,
        "weights_fitted": False,
        "probabilities_fitted": False,
        "market_used": False,
    }


def replay_contextual_families(frame: pd.DataFrame, *, universe: str) -> dict[str, Any]:
    rows = build_contextual_family_replay_rows(frame, universe=universe)
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "production_effect": False,
        "market_used": False,
        "result": evaluate_contextual_family_replay(rows),
    }
