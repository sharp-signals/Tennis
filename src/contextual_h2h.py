"""Ex-ante, factual head-to-head context for the next-generation model."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import unicodedata
from typing import Any

import pandas as pd


SCHEMA_VERSION = 1
_NON_STANDARD = re.compile(r"\b(?:RET|W/O|WO|DEF|ABD|ABN|CANC)\b", re.I)


def _name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _dates(frame: pd.DataFrame) -> pd.Series:
    source = frame.get("event_date")
    if source is None:
        source = frame.get("tourney_date", pd.Series(index=frame.index, dtype="object"))
    raw = source.astype("string").str.strip()
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    return compact.fillna(pd.to_datetime(raw, errors="coerce", utc=True))


def _surface(value: Any) -> str | None:
    text = _name(value)
    if not text:
        return None
    if "clay" in text or "terra" in text:
        return "clay"
    if "grass" in text or "relva" in text:
        return "grass"
    if "hard" in text or "carpet" in text or "duro" in text:
        return "hard"
    return None


def _row_context(row: pd.Series) -> str | None:
    scope = _name(row.get("_history_competition_scope"))
    tier = _name(row.get("tier") or row.get("tourney_level"))
    tour = _name(row.get("tour") or row.get("tour_type"))
    if "challenger" in scope or "challenger" in tier:
        return "challenger"
    if tour == "wta" or scope == "wta main":
        return "wta_main"
    if tour == "atp" or scope == "atp main" or scope == "main":
        return "atp_main"
    return None


def _rank_change(current: float | None, historical: float | None) -> float | None:
    if current is None or historical is None:
        return None
    # Positive means stronger now than at the prior encounter.
    return math.log(historical / current)


def build_contextual_h2h(
    history: pd.DataFrame,
    player_a: str,
    player_b: str,
    *,
    cutoff: datetime,
    current_surface: Any = None,
    current_context: str | None = None,
    current_best_of: Any = None,
    current_rank_a: Any = None,
    current_rank_b: Any = None,
) -> dict[str, Any]:
    """Preserve H2H evidence without converting it into a vote or weight."""
    base = {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "player_a": player_a,
        "player_b": player_b,
        "cutoff": cutoff.isoformat(),
        "current_surface": _surface(current_surface),
        "current_context": current_context,
        "current_best_of": _number(current_best_of),
        "score": None,
        "leader": None,
        "weight": None,
        "family_contribution": None,
        "market_used": False,
        "production_effect": False,
    }
    if history is None or history.empty or not {
        "winner_name", "loser_name",
    }.issubset(history.columns):
        return {**base, "status": "SOURCE_UNAVAILABLE", "matches": []}

    cutoff_utc = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    cutoff_utc = cutoff_utc.astimezone(timezone.utc)
    dates = _dates(history)
    before = dates.dt.date < cutoff_utc.date()
    winner_names = history["winner_name"].map(_name)
    loser_names = history["loser_name"].map(_name)
    a_key, b_key = _name(player_a), _name(player_b)
    identity_a = bool(((winner_names == a_key) | (loser_names == a_key))[before].any())
    identity_b = bool(((winner_names == b_key) | (loser_names == b_key))[before].any())
    if not identity_a or not identity_b:
        return {
            **base,
            "status": "IDENTITY_UNRESOLVED",
            "identity_a_observed": identity_a,
            "identity_b_observed": identity_b,
            "matches": [],
        }

    pair = (
        ((winner_names == a_key) & (loser_names == b_key))
        | ((winner_names == b_key) & (loser_names == a_key))
    )
    rows = history[before & pair].copy()
    if rows.empty:
        return {
            **base,
            "status": "OBSERVED_NONE",
            "identity_a_observed": True,
            "identity_b_observed": True,
            "coverage_complete": True,
            "observed_matches": 0,
            "matches": [],
        }

    rows["_date"] = _dates(rows)
    rank_a_now, rank_b_now = _number(current_rank_a), _number(current_rank_b)
    surface_now = _surface(current_surface)
    format_now = _number(current_best_of)
    matches: list[dict[str, Any]] = []
    for _, row in rows.sort_values("_date").iterrows():
        a_won = _name(row.get("winner_name")) == a_key
        historical_rank_a = _number(
            row.get("winner_rank") if a_won else row.get("loser_rank")
        )
        historical_rank_b = _number(
            row.get("loser_rank") if a_won else row.get("winner_rank")
        )
        match_surface = _surface(row.get("surface") or row.get("court"))
        match_context = _row_context(row)
        match_format = _number(row.get("best_of"))
        score = str(row.get("score") or "").strip() or None
        standard = not bool(score and _NON_STANDARD.search(score))
        match_date = row["_date"].date()
        matches.append({
            "event_date": match_date.isoformat(),
            "days_before_cutoff": (cutoff_utc.date() - match_date).days,
            "winner_side": "a" if a_won else "b",
            "score": score,
            "competitively_eligible": standard,
            "surface": match_surface,
            "same_surface": (
                match_surface == surface_now
                if match_surface is not None and surface_now is not None else None
            ),
            "competition_context": match_context,
            "same_competition_context": (
                match_context == current_context
                if match_context is not None and current_context is not None else None
            ),
            "best_of": match_format,
            "same_format": (
                match_format == format_now
                if match_format is not None and format_now is not None else None
            ),
            "round": row.get("round"),
            "rank_a_at_match": historical_rank_a,
            "rank_b_at_match": historical_rank_b,
            "ranking_strength_change_a_since_match": _rank_change(
                rank_a_now, historical_rank_a,
            ),
            "ranking_strength_change_b_since_match": _rank_change(
                rank_b_now, historical_rank_b,
            ),
        })

    eligible = [item for item in matches if item["competitively_eligible"]]
    a_wins = sum(item["winner_side"] == "a" for item in eligible)
    b_wins = sum(item["winner_side"] == "b" for item in eligible)
    same_surface = [item for item in eligible if item["same_surface"] is True]
    same_context = [
        item for item in eligible if item["same_competition_context"] is True
    ]
    return {
        **base,
        "status": "AVAILABLE",
        "identity_a_observed": True,
        "identity_b_observed": True,
        "coverage_complete": True,
        "observed_matches": len(matches),
        "eligible_matches": len(eligible),
        "non_standard_matches": len(matches) - len(eligible),
        "a_wins": a_wins,
        "b_wins": b_wins,
        "a_win_share": a_wins / len(eligible) if eligible else None,
        "direction_consistency": (
            max(a_wins, b_wins) / len(eligible) if eligible else None
        ),
        "same_surface_matches": len(same_surface),
        "same_context_matches": len(same_context),
        "most_recent_days_before_cutoff": min(
            (item["days_before_cutoff"] for item in eligible), default=None,
        ),
        "matches": matches,
    }
