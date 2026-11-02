"""Factual, ex-ante ranking context for the next-generation model.

This module deliberately produces observations, not a factor score.  It does
not know market prices and is not connected to the production index.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import unicodedata
from typing import Any

import pandas as pd


SCHEMA_VERSION = 1


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _dates(frame: pd.DataFrame) -> pd.Series:
    source = frame.get("event_date")
    if source is None:
        source = frame.get("tourney_date", pd.Series(index=frame.index, dtype="object"))
    raw = source.astype("string").str.strip()
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    generic = pd.to_datetime(raw, errors="coerce", utc=True)
    return compact.fillna(generic)


def _player_observations(
    history: pd.DataFrame,
    player: str,
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    if history is None or history.empty:
        return []
    cutoff_utc = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    cutoff_utc = cutoff_utc.astimezone(timezone.utc)
    # Provider history has day precision.  Excluding the whole cutoff day is
    # the only leakage-safe choice when match time is unknown.
    before = _dates(history).dt.date < cutoff_utc.date()
    wanted = _name(player)
    winners = history.get("winner_name", pd.Series(index=history.index, dtype="object")).map(_name)
    losers = history.get("loser_name", pd.Series(index=history.index, dtype="object")).map(_name)
    rows = history[before & ((winners == wanted) | (losers == wanted))].copy()
    if rows.empty:
        return []
    rows["_date"] = _dates(rows)
    observations: list[dict[str, Any]] = []
    for _, row in rows.sort_values("_date").iterrows():
        won = _name(row.get("winner_name")) == wanted
        rank = _number(row.get("winner_rank") if won else row.get("loser_rank"))
        points = _number(
            row.get("winner_rank_points") if won else row.get("loser_rank_points")
        )
        if rank is None and points is None:
            continue
        observations.append({
            "observed_at": row["_date"].date().isoformat(),
            "rank": rank,
            "points": points,
        })
    return observations


def _nearest_anchor(
    observations: list[dict[str, Any]],
    *,
    cutoff: datetime,
    days_ago: int,
    tolerance_days: int,
) -> dict[str, Any] | None:
    target = cutoff.date() - pd.Timedelta(days=days_ago)
    candidates = []
    for item in observations:
        observed = pd.Timestamp(item["observed_at"]).date()
        distance = abs((observed - target).days)
        if distance <= tolerance_days and item.get("rank") is not None:
            candidates.append((distance, observed, item))
    if not candidates:
        return None
    distance, _, item = min(candidates, key=lambda value: (value[0], value[1]))
    return {**item, "anchor_offset_days": distance}


def build_player_ranking_context(
    history: pd.DataFrame,
    player: str,
    *,
    cutoff: datetime,
    current_rank: Any,
    current_points: Any = None,
    days_since_last_match: Any = None,
) -> dict[str, Any]:
    """Build raw ranking evidence known strictly before ``cutoff``."""
    rank = _number(current_rank)
    points = _number(current_points)
    observations = _player_observations(history, player, cutoff=cutoff)
    ranked = [item for item in observations if item.get("rank") is not None]
    observed_peak = min((item["rank"] for item in ranked), default=None)
    last = ranked[-1] if ranked else None
    recent_start = cutoff.date() - pd.Timedelta(days=365)
    recent = [
        item for item in ranked
        if pd.Timestamp(item["observed_at"]).date() >= recent_start
    ]
    anchor_6m = _nearest_anchor(
        ranked, cutoff=cutoff, days_ago=182, tolerance_days=60,
    )
    anchor_12m = _nearest_anchor(
        ranked, cutoff=cutoff, days_ago=365, tolerance_days=90,
    )

    def strength_change(anchor: dict[str, Any] | None) -> float | None:
        anchor_rank = _number((anchor or {}).get("rank"))
        if rank is None or anchor_rank is None:
            return None
        # Positive means the current position is stronger than the anchor.
        return math.log(anchor_rank / rank)

    inactivity = _number(days_since_last_match)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "player": player,
        "cutoff": cutoff.isoformat(),
        "current_rank": rank,
        "current_points": points,
        "historical_observation_count": len(ranked),
        "observed_peak_rank": observed_peak,
        "observed_best_rank_365d": min(
            (item["rank"] for item in recent), default=None,
        ),
        "last_observed_rank": (last or {}).get("rank"),
        "last_rank_observed_at": (last or {}).get("observed_at"),
        "current_vs_observed_peak_log_ratio": (
            math.log(rank / observed_peak)
            if rank is not None and observed_peak is not None else None
        ),
        "anchor_6m": anchor_6m,
        "anchor_12m": anchor_12m,
        "ranking_strength_change_6m": strength_change(anchor_6m),
        "ranking_strength_change_12m": strength_change(anchor_12m),
        "days_since_last_match": inactivity,
        "evidence_status": (
            "COMPLETE_CURRENT_AND_HISTORY" if rank is not None and ranked
            else "CURRENT_ONLY" if rank is not None
            else "HISTORY_ONLY" if ranked
            else "MISSING"
        ),
        "production_effect": False,
        "market_used": False,
    }


def build_pair_ranking_context(
    player_a: dict[str, Any],
    player_b: dict[str, Any],
) -> dict[str, Any]:
    """Compare two factual contexts without thresholds, votes or weights."""
    rank_a = _number(player_a.get("current_rank"))
    rank_b = _number(player_b.get("current_rank"))
    points_a = _number(player_a.get("current_points"))
    points_b = _number(player_b.get("current_points"))
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "player_a": player_a.get("player"),
        "player_b": player_b.get("player"),
        "current_rank_a": rank_a,
        "current_rank_b": rank_b,
        "absolute_rank_gap": abs(rank_a - rank_b) if rank_a and rank_b else None,
        # Positive favours A, negative favours B.  The logarithm recognises
        # that ranking positions are not a linear strength scale.
        "current_rank_log_ratio_a_minus_b": (
            math.log(rank_b / rank_a) if rank_a and rank_b else None
        ),
        "ranking_points_log_ratio_a_minus_b": (
            math.log(points_a / points_b) if points_a and points_b else None
        ),
        "history_available_bilateral": bool(
            player_a.get("historical_observation_count")
            and player_b.get("historical_observation_count")
        ),
        "evidence_status": "BILATERAL" if rank_a and rank_b else "PARTIAL",
        "score": None,
        "leader": None,
        "weight": None,
        "production_effect": False,
        "market_used": False,
    }
