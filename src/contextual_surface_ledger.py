"""Factual four-context surface ledger for the contextual model.

This module does not score a player and does not calculate probabilities.  It
normalizes the provider's career and year aggregates into four mutually
exclusive tennis contexts without summing overlapping sources.
"""

from __future__ import annotations

from datetime import date, datetime
import re
import unicodedata
from typing import Any, Mapping


SCHEMA_VERSION = 1
SURFACE_CONTEXTS = (
    "hard_outdoor",
    "hard_indoor",
    "clay",
    "grass",
)
PROVIDER_COURT_KEYS = {
    "hard_outdoor": "1",
    "clay": "2",
    "hard_indoor": "3",
    "grass": "5",
}
PROVIDER_AGGREGATE_KEYS = {
    "hard_outdoor": "hard",
    "hard_indoor": "hard_indoor",
    "clay": "clay",
    "grass": "grass",
}


def _text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def exact_surface_context(
    surface: Any, *, venue: Any = None, indoor: Any = None,
) -> str | None:
    """Return one exact context; ambiguous hard courts fail closed."""
    surface_text = _text(surface)
    venue_text = _text(venue)
    explicit_indoor = indoor if isinstance(indoor, bool) else None
    if "clay" in surface_text or "terra" in surface_text:
        return "clay"
    if "grass" in surface_text or "relva" in surface_text:
        return "grass"
    if not any(token in surface_text for token in ("hard", "dur", "duro")):
        return None
    if any(token in surface_text for token in ("indoor", "interior", "i hard")):
        return "hard_indoor"
    if explicit_indoor is True or venue_text in {"indoor", "interior", "inside"}:
        return "hard_indoor"
    if explicit_indoor is False or venue_text in {"outdoor", "exterior", "outside"}:
        return "hard_outdoor"
    return None


def _record(wins: Any, losses: Any) -> dict[str, Any] | None:
    try:
        wins_int, losses_int = int(wins or 0), int(losses or 0)
    except (TypeError, ValueError):
        return None
    matches = wins_int + losses_int
    if wins_int < 0 or losses_int < 0 or matches <= 0:
        return None
    return {
        "wins": wins_int,
        "losses": losses_int,
        "matches": matches,
        "win_pct": round(100.0 * wins_int / matches, 1),
    }

def _aggregate_record(cell: Any) -> dict[str, Any] | None:
    if not isinstance(cell, Mapping):
        return None
    return _record(cell.get("wins"), cell.get("losses"))


def _year_record(year_data: Any, context: str) -> dict[str, Any] | None:
    if not isinstance(year_data, Mapping):
        return None
    court = year_data.get("court")
    if not isinstance(court, Mapping):
        return None
    cell = court.get(PROVIDER_COURT_KEYS[context])
    if not isinstance(cell, Mapping):
        return None
    return _record(cell.get("aw"), cell.get("al"))


def build_provider_surface_ledger(
    performance: Mapping[str, Any] | None,
    *,
    as_of: date,
) -> dict[str, Any]:
    """Normalize provider aggregates for career/current/previous seasons."""
    payload = performance if isinstance(performance, Mapping) else {}
    by_surface = payload.get("by_surface")
    by_year = payload.get("by_year")
    by_surface = by_surface if isinstance(by_surface, Mapping) else {}
    by_year = by_year if isinstance(by_year, Mapping) else {}
    current_year, previous_year = as_of.year, as_of.year - 1
    contexts: dict[str, Any] = {}
    for context in SURFACE_CONTEXTS:
        career = _aggregate_record(
            by_surface.get(PROVIDER_AGGREGATE_KEYS[context])
        )
        current = _year_record(by_year.get(str(current_year)), context)
        previous = _year_record(by_year.get(str(previous_year)), context)
        delta = None
        if current is not None and previous is not None:
            delta = round(current["win_pct"] - previous["win_pct"], 1)
        contexts[context] = {
            "status": "AVAILABLE" if career is not None else "UNAVAILABLE",
            "career": career,
            "current_season": current,
            "previous_season": previous,
            "current_vs_previous_win_pct_pp": delta,
            "source": "rapidapi_perf_breakdown_aggregate",
            "source_overlap_policy": "SELECT_ONE_SOURCE_NEVER_SUM",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of.isoformat(),
        "current_year": current_year,
        "previous_year": previous_year,
        "contexts": contexts,
        "available_contexts": sum(
            row["status"] == "AVAILABLE" for row in contexts.values()
        ),
        "market_used": False,
        "production_effect": False,
    }

def _observation_date(row: Mapping[str, Any]) -> date | None:
    value = row.get("event_date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _observation_record(rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    wins = sum(bool(row.get("won")) for row in rows)
    return _record(wins, len(rows) - wins)


def build_chronological_surface_ledger(
    observations: list[Mapping[str, Any]],
    *,
    context: str,
    cutoff: date,
) -> dict[str, Any]:
    """Build a leakage-safe ledger from match-level observations.

    Every row must already carry an exact ``surface_context``.  Unknown or
    ambiguous hard courts remain excluded instead of being guessed.
    """
    if context not in SURFACE_CONTEXTS:
        raise ValueError(f"unknown surface context: {context}")
    eligible: list[tuple[date, Mapping[str, Any]]] = []
    for row in observations:
        observed = _observation_date(row)
        if (
            observed is not None
            and observed < cutoff
            and row.get("surface_context") == context
        ):
            eligible.append((observed, row))
    career_rows = [row for _, row in eligible]
    current_rows = [row for day, row in eligible if day.year == cutoff.year]
    previous_rows = [row for day, row in eligible if day.year == cutoff.year - 1]
    career = _observation_record(career_rows)
    current = _observation_record(current_rows)
    previous = _observation_record(previous_rows)
    delta = None
    if current is not None and previous is not None:
        delta = round(current["win_pct"] - previous["win_pct"], 1)
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": cutoff.isoformat(),
        "context": context,
        "status": "AVAILABLE" if career is not None else "UNAVAILABLE",
        "career": career,
        "current_season": current,
        "previous_season": previous,
        "current_vs_previous_win_pct_pp": delta,
        "source": "chronological_match_history",
        "future_matches_excluded": True,
        "ambiguous_hard_excluded": True,
        "market_used": False,
        "production_effect": False,
    }
# End of factual ledger helpers.
