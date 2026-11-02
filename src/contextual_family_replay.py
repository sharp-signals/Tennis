"""Leakage-safe chronological replay of the five contextual families.

The replay creates factual, pre-match feature rows.  It deliberately does not
fit weights, probabilities, fair odds or edges.  Player A/B orientation is
alphabetical and therefore independent of the eventual winner.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import math
from typing import Any

import pandas as pd

from .contextual_factor_orchestrator import build_contextual_family_vector
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
FEATURE_FAMILIES = {
    "recent_result_balance_90d": "recent_form",
    "recent_game_margin_balance_90d": "recent_form",
    "recent_win_opponent_strength_90d": "recent_form",
    "recent_loss_opponent_strength_90d": "recent_form",
    "current_rank_log_ratio": "structural_strength",
    "rank_change_from_last_observation": "structural_strength",
    "same_surface_result_balance_90d": "surface_conditions",
    "career_surface_win_rate_margin": "surface_conditions",
    "h2h_win_share_margin": "matchup_h2h",
    "same_surface_h2h_win_share_margin": "matchup_h2h",
    "service_points_won_surface_margin": "serve_return",
    "return_points_won_surface_margin": "serve_return",
    "hold_surface_margin": "serve_return",
    "break_surface_margin": "serve_return",
    "service_points_won_recent_margin": "serve_return",
    "return_points_won_recent_margin": "serve_return",
}


def _surface(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    return text or None


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
    material["_surface"] = _column(frame, "surface").map(_surface)
    material["_winner_rank"] = _column(frame, "winner_rank")
    material["_loser_rank"] = _column(frame, "loser_rank")
    material["_score"] = _column(frame, "score")
    material["_non_standard"] = _is_non_standard_completion(frame)
    return material[
        material["_event_date"].notna()
        & material["_winner"].notna()
        & material["_loser"].notna()
        & (material["_winner"] != "")
        & (material["_loser"] != "")
    ].sort_values("_event_date")


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


def build_contextual_family_replay_rows(
    frame: pd.DataFrame, *, universe: str,
) -> list[dict[str, Any]]:
    """Build ex-ante rows; an entire event date is evaluated before ingestion."""
    material = _material(frame)
    match_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rank_history: dict[str, list[tuple[date, float]]] = defaultdict(list)
    service_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pair_history: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    replay: list[dict[str, Any]] = []

    for event_date, day in material.groupby("_event_date", sort=True):
        for _, match in day.iterrows():
            if bool(match["_non_standard"]):
                continue
            winner = _name_key(match["_winner"])
            loser = _name_key(match["_loser"])
            if not winner or not loser or winner == loser:
                continue
            player_a, player_b = sorted((winner, loser))
            a_won = winner == player_a
            surface = match["_surface"]
            rank_w = _positive_rank(match["_winner_rank"])
            rank_l = _positive_rank(match["_loser_rank"])
            rank_a = rank_w if a_won else rank_l
            rank_b = rank_l if a_won else rank_w

            recent_a = _summarize_player_history(
                match_history[player_a], cutoff=event_date, target_surface=surface,
                half_life_days=None, window_days=WINDOW_DAYS,
            )
            recent_b = _summarize_player_history(
                match_history[player_b], cutoff=event_date, target_surface=surface,
                half_life_days=None, window_days=WINDOW_DAYS,
            )
            surface_rate_a, surface_sample_a = _surface_record(
                match_history[player_a], surface,
            )
            surface_rate_b, surface_sample_b = _surface_record(
                match_history[player_b], surface,
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
                "features": features,
                "samples": {
                    "recent_a": recent_a["sample"], "recent_b": recent_b["sample"],
                    "surface_a": surface_sample_a, "surface_b": surface_sample_b,
                    "h2h": h2h_sample, "same_surface_h2h": h2h_surface_sample,
                    "service_surface_a": (service_surface_a or {}).get("matches", 0),
                    "service_surface_b": (service_surface_b or {}).get("matches", 0),
                },
                "family_states": {
                    row["key"]: {
                        "data_state": row["data_state"],
                        "signal_state": row["signal_state"],
                    }
                    for row in vector["families"]
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
            rank_w = _positive_rank(match["_winner_rank"])
            rank_l = _positive_rank(match["_loser_rank"])
            winner_margin = _game_margin(match["_score"], won=True)
            loser_margin = -winner_margin if winner_margin is not None else None
            match_history[winner].append(_player_observation(
                event_date=event_date, surface=surface, won=True,
                player_rank=rank_w, opponent_rank=rank_l, game_margin=winner_margin,
            ))
            match_history[loser].append(_player_observation(
                event_date=event_date, surface=surface, won=False,
                player_rank=rank_l, opponent_rank=rank_w, game_margin=loser_margin,
            ))
            if rank_w:
                rank_history[winner].append((event_date, rank_w))
            if rank_l:
                rank_history[loser].append((event_date, rank_l))
            for player, won in ((winner, True), (loser, False)):
                service = _extract_match(match, player_won=won)
                if service is not None:
                    service_history[player].append({
                        **service, "event_date": event_date, "surface": surface,
                    })
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
