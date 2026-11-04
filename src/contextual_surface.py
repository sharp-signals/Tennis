"""Factual surface-and-conditions family for the next-generation model."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
import unicodedata
from typing import Any

import pandas as pd


SCHEMA_VERSION = 1


def _name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _surface(value: Any) -> str | None:
    text = _name(value)
    if not text:
        return None
    if "clay" in text or "terra" in text:
        return "clay"
    if "grass" in text or "relva" in text:
        return "grass"
    if "carpet" in text:
        return "carpet"
    if "hard" in text or "duro" in text:
        return "hard"
    return None


def _venue(value: Any) -> str | None:
    if isinstance(value, bool):
        return "indoor" if value else "outdoor"
    text = _name(value)
    if text in {"i", "indoor", "inside", "interior", "true", "1"}:
        return "indoor"
    if text in {"o", "outdoor", "outside", "exterior", "false", "0"}:
        return "outdoor"
    if text.startswith("i ") or "indoor" in text:
        return "indoor"
    if "outdoor" in text:
        return "outdoor"
    return None


def _pace(value: Any) -> str | None:
    text = _name(value).replace(" ", "_")
    aliases = {
        "slow": "slow", "lento": "slow",
        "medium_slow": "medium_slow", "medio_lento": "medium_slow",
        "medium": "medium", "medio": "medium",
        "medium_fast": "medium_fast", "medio_rapido": "medium_fast",
        "fast": "fast", "rapido": "fast",
    }
    return aliases.get(text)


def _dates(frame: pd.DataFrame) -> pd.Series:
    source = frame.get("event_date")
    if source is None:
        source = frame.get("tourney_date", pd.Series(index=frame.index, dtype="object"))
    raw = source.astype("string").str.strip()
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    return compact.fillna(pd.to_datetime(raw, errors="coerce", utc=True))


def _row_venue(row: pd.Series) -> str | None:
    for key in ("indoor", "is_indoor", "isIndoor", "venue_context"):
        if key in row and not pd.isna(row.get(key)):
            resolved = _venue(row.get(key))
            if resolved:
                return resolved
    # Only explicit indoor/outdoor text is accepted.  A plain physical
    # surface is not silently assumed to be outdoor.
    for key in ("court", "Court", "surface", "Surface"):
        resolved = _venue(row.get(key))
        if resolved:
            return resolved
    return None


def _row_pace(row: pd.Series) -> str | None:
    for key in ("court_pace_bucket", "pace_bucket", "_court_pace_bucket"):
        if key in row:
            resolved = _pace(row.get(key))
            if resolved:
                return resolved
    return None


def _record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matches = len(rows)
    wins = sum(bool(row["won"]) for row in rows)
    return {
        "matches": matches,
        "wins": wins,
        "losses": matches - wins,
        "win_share": wins / matches if matches else None,
    }


def build_player_surface_context(
    history: pd.DataFrame,
    player: str,
    *,
    cutoff: datetime,
    current_surface: Any,
    current_venue: Any = None,
    current_pace_bucket: Any = None,
) -> dict[str, Any]:
    """Build one factual family; components are not independent votes."""
    surface_now = _surface(current_surface)
    venue_now = _venue(current_venue)
    pace_now = _pace(current_pace_bucket)
    base = {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "player": player,
        "cutoff": cutoff.isoformat(),
        "current_surface": surface_now,
        "current_venue": venue_now,
        "current_pace_bucket": pace_now,
        "dependency_family": "surface_and_conditions",
        "component_independence": False,
        "score": None,
        "weight": None,
        "family_contribution": None,
        "market_used": False,
        "production_effect": False,
    }
    required = {"winner_name", "loser_name"}
    if history is None or history.empty or not required.issubset(history.columns):
        return {**base, "status": "SOURCE_UNAVAILABLE"}

    cutoff_utc = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    cutoff_utc = cutoff_utc.astimezone(timezone.utc)
    dates = _dates(history)
    before = dates.dt.date < cutoff_utc.date()
    winners = history["winner_name"].map(_name)
    losers = history["loser_name"].map(_name)
    wanted = _name(player)
    played = history[before & ((winners == wanted) | (losers == wanted))].copy()
    if played.empty:
        return {**base, "status": "IDENTITY_UNRESOLVED"}
    played["_date"] = _dates(played)

    observations: list[dict[str, Any]] = []
    for _, row in played.sort_values("_date").iterrows():
        surface = _surface(row.get("surface") or row.get("court"))
        observations.append({
            "event_date": row["_date"].date().isoformat(),
            "days_before_cutoff": (cutoff_utc.date() - row["_date"].date()).days,
            "won": _name(row.get("winner_name")) == wanted,
            "surface": surface,
            "venue": _row_venue(row),
            "pace_bucket": _row_pace(row),
        })

    same_surface = [row for row in observations if row["surface"] == surface_now]
    same_venue = [row for row in observations if row["venue"] == venue_now] if venue_now else []
    same_pace = [row for row in observations if row["pace_bucket"] == pace_now] if pace_now else []
    same_surface_venue = [
        row for row in observations
        if row["surface"] == surface_now and row["venue"] == venue_now
    ] if venue_now else []

    recent_90 = [row for row in observations if row["days_before_cutoff"] <= 90]
    recent_35 = [row for row in observations if row["days_before_cutoff"] <= 35]
    recent_surface_counts = Counter(
        row["surface"] for row in recent_35 if row["surface"] is not None
    )
    most_recent_surface = next((
        row["surface"] for row in reversed(observations)
        if row["surface"] is not None
    ), None)
    dominant_recent_surface = None
    if recent_surface_counts:
        dominant_recent_surface = max(
            recent_surface_counts,
            key=lambda item: (
                recent_surface_counts[item], item == most_recent_surface,
            ),
        )
    latest_on_current = next((
        row for row in reversed(observations) if row["surface"] == surface_now
    ), None)

    pace_applicable = surface_now == "hard" and pace_now is not None
    return {
        **base,
        "status": "AVAILABLE",
        "historical_matches": len(observations),
        "surface_record": _record(same_surface) if surface_now else None,
        "venue_record": _record(same_venue) if venue_now else None,
        "pace_record": _record(same_pace) if pace_applicable else None,
        "same_surface_and_venue_matches": len(same_surface_venue),
        "overlap_matches_surface_venue": len(same_surface_venue),
        "surface_observation_coverage": sum(
            row["surface"] is not None for row in observations
        ) / len(observations),
        "venue_observation_coverage": sum(
            row["venue"] is not None for row in observations
        ) / len(observations),
        "pace_observation_coverage": sum(
            row["pace_bucket"] is not None for row in observations
        ) / len(observations),
        "recent_90d_surface_sequence": [row["surface"] for row in recent_90],
        "recent_35d_surface_counts": dict(recent_surface_counts),
        "recent_dominant_surface": dominant_recent_surface,
        "most_recent_surface": most_recent_surface,
        "matches_on_current_surface_last_35d": sum(
            row["surface"] == surface_now for row in recent_35
        ) if surface_now else None,
        "days_since_current_surface": (
            latest_on_current["days_before_cutoff"] if latest_on_current else None
        ),
        "transition_observed": bool(
            surface_now and dominant_recent_surface
            and dominant_recent_surface != surface_now
            and not any(row["surface"] == surface_now for row in recent_35)
        ),
        "pace_applicability": (
            "APPLICABLE" if pace_applicable
            else "NOT_APPLICABLE_NON_HARD" if surface_now not in {None, "hard"}
            else "UNCLASSIFIED"
        ),
    }


def build_pair_surface_context(
    player_a: dict[str, Any],
    player_b: dict[str, Any],
) -> dict[str, Any]:
    """Pair two player contexts while enforcing a single-family boundary."""
    context_keys = ("current_surface", "current_venue", "current_pace_bucket")
    context_consistent = all(
        player_a.get(key) == player_b.get(key) for key in context_keys
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "family": "surface_and_conditions",
        "player_a": player_a.get("player"),
        "player_b": player_b.get("player"),
        "current_surface": player_a.get("current_surface"),
        "current_venue": player_a.get("current_venue"),
        "current_pace_bucket": player_a.get("current_pace_bucket"),
        "status": "READY" if context_consistent else "CONTEXT_MISMATCH",
        "context_consistent": context_consistent,
        "surface_component": {
            "a": player_a.get("surface_record"),
            "b": player_b.get("surface_record"),
        },
        "venue_component": {
            "a": player_a.get("venue_record"),
            "b": player_b.get("venue_record"),
        },
        "pace_component": {
            "a": player_a.get("pace_record"),
            "b": player_b.get("pace_record"),
        },
        "transition_component": {
            "a": player_a.get("transition_observed"),
            "b": player_b.get("transition_observed"),
        },
        "dependency_policy": "ONE_FAMILY_CONTRIBUTION_NOT_COMPONENT_SUM",
        "score": None,
        "leader": None,
        "weight": None,
        "family_contribution": None,
        "market_used": False,
        "production_effect": False,
    }
