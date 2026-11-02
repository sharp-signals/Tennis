"""Leakage-safe replay for the future contextual recent-form family.

CHANGE-2026-11-02-175.  This module does not feed production pricing.  It
reconstructs, for each historical match day, only the observations that were
available before that day and compares candidate recency decays without
inventing a final family weight.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Iterable

import pandas as pd

from .recent_form_audit import (
    CHANGE_ID,
    DEFAULT_WINDOW_DAYS,
    _column,
    _is_non_standard_completion,
    _parse_history_dates,
)


SCHEMA_VERSION = 1
DEFAULT_HALF_LIFE_CANDIDATES: tuple[int | None, ...] = (None, 21, 30, 45, 60, 90)
FEATURES = (
    "result_balance",
    "ranking_quality_balance",
    "same_surface_result_balance",
)


def _name_key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _surface_key(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    return text or None


def _positive_rank(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) and numeric > 0 else None


def _decay_weight(days_ago: int, half_life_days: int | None) -> float:
    if half_life_days is None:
        return 1.0
    return 0.5 ** (max(0, int(days_ago)) / int(half_life_days))


def _player_observation(
    *,
    event_date: date,
    surface: str | None,
    won: bool,
    player_rank: float | None,
    opponent_rank: float | None,
) -> dict[str, Any]:
    ranking_context = None
    if player_rank is not None and opponent_rank is not None:
        ranking_context = math.log(opponent_rank / player_rank)
    return {
        "event_date": event_date,
        "surface": surface,
        "result": 1.0 if won else -1.0,
        "ranking_available": ranking_context is not None,
        "quality_win": (
            max(0.0, -ranking_context)
            if won and ranking_context is not None else 0.0
        ),
        "quality_loss": (
            max(0.0, ranking_context)
            if not won and ranking_context is not None else 0.0
        ),
    }


def _summarize_player_history(
    observations: Iterable[dict[str, Any]],
    *,
    cutoff: date,
    target_surface: str | None,
    half_life_days: int | None,
    window_days: int,
) -> dict[str, float | int | None]:
    start = cutoff - timedelta(days=int(window_days))
    eligible = [
        item for item in observations
        if start <= item["event_date"] < cutoff
    ]
    if not eligible:
        return {
            "sample": 0,
            "ranked_sample": 0,
            "same_surface_sample": 0,
            **{feature: None for feature in FEATURES},
        }

    weights = [
        _decay_weight((cutoff - item["event_date"]).days, half_life_days)
        for item in eligible
    ]
    weight_total = sum(weights)
    result_balance = sum(
        weight * item["result"] for weight, item in zip(weights, eligible)
    ) / weight_total

    ranked = [
        (weight, item) for weight, item in zip(weights, eligible)
        if item["ranking_available"]
    ]
    if ranked:
        ranked_weight = sum(weight for weight, _ in ranked)
        ranking_quality = sum(
            weight * (item["quality_win"] - item["quality_loss"])
            for weight, item in ranked
        ) / ranked_weight
    else:
        ranking_quality = None

    same_surface = [
        (weight, item) for weight, item in zip(weights, eligible)
        if target_surface is not None and item["surface"] == target_surface
    ]
    if same_surface:
        surface_weight = sum(weight for weight, _ in same_surface)
        surface_balance = sum(
            weight * item["result"] for weight, item in same_surface
        ) / surface_weight
    else:
        surface_balance = None

    return {
        "sample": len(eligible),
        "ranked_sample": len(ranked),
        "same_surface_sample": len(same_surface),
        "result_balance": result_balance,
        "ranking_quality_balance": ranking_quality,
        "same_surface_result_balance": surface_balance,
    }


def build_recent_form_replay_rows(
    frame: pd.DataFrame,
    *,
    universe: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    half_life_candidates: Iterable[int | None] = DEFAULT_HALF_LIFE_CANDIDATES,
) -> list[dict[str, Any]]:
    """Build target rows using only observations from earlier calendar days."""
    if int(window_days) <= 0:
        raise ValueError("window_days tem de ser positivo")
    candidates = tuple(half_life_candidates)
    if not candidates or any(value is not None and int(value) <= 0 for value in candidates):
        raise ValueError("half_life_candidates inválidos")

    dates = _parse_history_dates(_column(frame, "event_date"))
    winners = _column(frame, "winner_name").astype("string").str.strip()
    losers = _column(frame, "loser_name").astype("string").str.strip()
    surfaces = _column(frame, "surface")
    winner_ranks = _column(frame, "winner_rank")
    loser_ranks = _column(frame, "loser_rank")
    non_standard = _is_non_standard_completion(frame)

    material = pd.DataFrame({
        "event_date": dates.dt.date,
        "winner_name": winners,
        "loser_name": losers,
        "surface": surfaces,
        "winner_rank": winner_ranks,
        "loser_rank": loser_ranks,
        "non_standard": non_standard,
    }, index=frame.index)
    material = material[
        material["event_date"].notna()
        & material["winner_name"].notna()
        & material["loser_name"].notna()
        & (material["winner_name"] != "")
        & (material["loser_name"] != "")
    ].sort_values("event_date")

    history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    replay_rows: list[dict[str, Any]] = []
    for event_date, day in material.groupby("event_date", sort=True):
        # Evaluate the whole day before adding any result from that day.  This
        # is conservative for sources that contain dates but no start times.
        for _, match in day.iterrows():
            if bool(match["non_standard"]):
                continue
            winner_key = _name_key(match["winner_name"])
            loser_key = _name_key(match["loser_name"])
            if not winner_key or not loser_key or winner_key == loser_key:
                continue
            target_surface = _surface_key(match["surface"])
            candidate_values = {}
            for half_life in candidates:
                label = "uniform_90d" if half_life is None else f"half_life_{int(half_life)}d"
                winner_summary = _summarize_player_history(
                    history[winner_key], cutoff=event_date,
                    target_surface=target_surface, half_life_days=half_life,
                    window_days=window_days,
                )
                loser_summary = _summarize_player_history(
                    history[loser_key], cutoff=event_date,
                    target_surface=target_surface, half_life_days=half_life,
                    window_days=window_days,
                )
                margins = {}
                for feature in FEATURES:
                    a = winner_summary[feature]
                    b = loser_summary[feature]
                    margins[feature] = (
                        float(a) - float(b)
                        if a is not None and b is not None else None
                    )
                candidate_values[label] = {
                    "winner": winner_summary,
                    "loser": loser_summary,
                    "winner_minus_loser": margins,
                }
            replay_rows.append({
                "event_date": event_date.isoformat(),
                "universe": str(universe).strip().casefold(),
                "winner_name": str(match["winner_name"]),
                "loser_name": str(match["loser_name"]),
                "surface": target_surface,
                "candidates": candidate_values,
            })

        # Only after every target from the date was evaluated may its results
        # become history for a later date.
        for _, match in day.iterrows():
            if bool(match["non_standard"]):
                continue
            winner_key = _name_key(match["winner_name"])
            loser_key = _name_key(match["loser_name"])
            winner_rank = _positive_rank(match["winner_rank"])
            loser_rank = _positive_rank(match["loser_rank"])
            surface = _surface_key(match["surface"])
            history[winner_key].append(_player_observation(
                event_date=event_date, surface=surface, won=True,
                player_rank=winner_rank, opponent_rank=loser_rank,
            ))
            history[loser_key].append(_player_observation(
                event_date=event_date, surface=surface, won=False,
                player_rank=loser_rank, opponent_rank=winner_rank,
            ))
    return replay_rows


def _metric(rows: list[dict[str, Any]], candidate: str, feature: str) -> dict[str, Any]:
    margins = [
        row["candidates"][candidate]["winner_minus_loser"][feature]
        for row in rows
    ]
    material = [float(value) for value in margins if value is not None]
    if not material:
        return {
            "targets": len(rows), "covered": 0, "coverage_pct": 0.0,
            "correct": 0, "incorrect": 0, "ties": 0,
            "directional_accuracy_with_half_ties_pct": None,
            "mean_winner_minus_loser": None,
        }
    epsilon = 1e-12
    correct = sum(value > epsilon for value in material)
    incorrect = sum(value < -epsilon for value in material)
    ties = len(material) - correct - incorrect
    accuracy = 100.0 * (correct + 0.5 * ties) / len(material)
    return {
        "targets": len(rows),
        "covered": len(material),
        "coverage_pct": round(100.0 * len(material) / max(1, len(rows)), 1),
        "correct": correct,
        "incorrect": incorrect,
        "ties": ties,
        "directional_accuracy_with_half_ties_pct": round(accuracy, 2),
        "mean_winner_minus_loser": round(sum(material) / len(material), 6),
    }


def _chronological_split(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    dates = sorted({row["event_date"] for row in rows})
    if len(dates) < 5:
        return {"train": rows, "validation": [], "holdout": []}
    counts = {
        event_date: sum(row["event_date"] == event_date for row in rows)
        for event_date in dates
    }
    train_limit = len(rows) * 0.60
    validation_limit = len(rows) * 0.80
    train_dates: set[str] = set()
    validation_dates: set[str] = set()
    holdout_dates: set[str] = set()
    cumulative = 0
    for event_date in dates:
        # The complete date stays in one partition.  Thresholds are based on
        # target volume rather than number of distinct dates because legacy
        # seasons only expose tournament dates while the current feed has
        # finer date precision.
        if cumulative < train_limit:
            train_dates.add(event_date)
        elif cumulative < validation_limit:
            validation_dates.add(event_date)
        else:
            holdout_dates.add(event_date)
        cumulative += counts[event_date]
    return {
        "train": [row for row in rows if row["event_date"] in train_dates],
        "validation": [row for row in rows if row["event_date"] in validation_dates],
        "holdout": [row for row in rows if row["event_date"] in holdout_dates],
    }


def evaluate_recent_form_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Select decay per raw signal on validation and report untouched holdout."""
    if not rows:
        return {"status": "INSUFFICIENT", "targets": 0, "features": {}}
    candidate_names = tuple(rows[0]["candidates"])
    split = _chronological_split(rows)
    features = {}
    for feature in FEATURES:
        candidates = {
            candidate: {
                part: _metric(part_rows, candidate, feature)
                for part, part_rows in split.items()
            }
            for candidate in candidate_names
        }
        usable = [
            candidate for candidate in candidate_names
            if candidates[candidate]["validation"]["covered"] > 0
        ]
        selected = max(
            usable,
            key=lambda candidate: (
                candidates[candidate]["validation"]["directional_accuracy_with_half_ties_pct"],
                candidates[candidate]["validation"]["covered"],
                -candidate_names.index(candidate),
            ),
        ) if usable else None
        features[feature] = {
            "selected_on_validation": selected,
            "selection_rule": "highest validation directional accuracy; ties count as half",
            "candidates": candidates,
            "selected_holdout": candidates[selected]["holdout"] if selected else None,
        }
    return {
        "status": "OBSERVATIONAL_ONLY",
        "targets": len(rows),
        "date_range": [rows[0]["event_date"], rows[-1]["event_date"]],
        "split_targets": {name: len(items) for name, items in split.items()},
        "features": features,
    }


def replay_recent_form(
    frame: pd.DataFrame,
    *,
    universe: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    half_life_candidates: Iterable[int | None] = DEFAULT_HALF_LIFE_CANDIDATES,
) -> dict[str, Any]:
    rows = build_recent_form_replay_rows(
        frame, universe=universe, window_days=window_days,
        half_life_candidates=half_life_candidates,
    )
    result = evaluate_recent_form_replay(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "universe": str(universe).strip().casefold(),
        "window_days": int(window_days),
        "market_used": False,
        "production_effect": False,
        "same_day_policy": "all matches on cutoff date excluded from prior history",
        "result": result,
    }
