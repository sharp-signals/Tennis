"""Season-aware tournament context recovery for factual match history.

The registry fills venue metadata only.  It never reads odds, winners, scores,
rankings or any other predictive field.  A tournament name is propagated to
older rows only when every observed occurrence of that exact normalized name
has one unambiguous four-context classification.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

import pandas as pd

from .contextual_surface_ledger import SURFACE_CONTEXTS, exact_surface_context


SCHEMA_VERSION = 1

# User-confirmed ATP calendar for 2026.  The year is part of the key on
# purpose: Lyon 2026 is indoor, while historical Lyon editions must not be
# reclassified without their own season-specific evidence.
ATP_2026_INDOOR_TOURNAMENTS = {
    "open occitanie montpellier",
    "dallas open dallas",
    "abn amro open rotterdam",
    "almaty open almaty",
    "european open brussels",
    "grand prix auvergne rhone alpes lyon",
    "erste bank open vienna",
    "swiss indoors basel basel",
    "rolex paris masters paris",
    "stockholm open stockholm",
    "atp finals turin",
    "nitto atp finals turin",
}


def normalize_tournament_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def _year(value: Any) -> int | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else int(parsed.year)


def _row_context(row: Mapping[str, Any]) -> str | None:
    indoor = row.get("indoor")
    if not isinstance(indoor, bool):
        indoor = None
    venue = row.get("venue") or row.get("Court") or row.get("court")
    return exact_surface_context(
        row.get("surface"), venue=venue, indoor=indoor,
    )


def _tournament_name(row: Mapping[str, Any]) -> Any:
    return row.get("tourney_name") or row.get("Tournament")


def _event_date(row: Mapping[str, Any]) -> Any:
    value = row.get("date")
    if value is None or pd.isna(value):
        value = row.get("tourney_date") or row.get("Date")
    return value


def season_registry_context(
    tournament: Any, *, event_date: Any,
) -> str | None:
    """Resolve only explicitly registered tournament-season facts."""
    if _year(event_date) != 2026:
        return None
    name = normalize_tournament_name(tournament)
    if name in ATP_2026_INDOOR_TOURNAMENTS:
        return "hard_indoor"
    return None


def build_exact_tournament_context_reference(
    frame: pd.DataFrame,
) -> dict[str, str]:
    """Build a conflict-free reference from rows with observed context."""
    contexts: dict[str, set[str]] = {}
    for _, row in frame.iterrows():
        name = normalize_tournament_name(_tournament_name(row))
        context = _row_context(row)
        if name and context in SURFACE_CONTEXTS:
            contexts.setdefault(name, set()).add(context)
    return {
        name: next(iter(values))
        for name, values in contexts.items()
        if len(values) == 1
    }


def enrich_tournament_surface_contexts(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach exact context and provenance without mutating raw fields."""
    enriched = frame.copy()
    reference = build_exact_tournament_context_reference(enriched)
    contexts: list[str | None] = []
    sources: list[str] = []
    recovered_names: set[str] = set()
    counts = {
        "observed_fields": 0,
        "season_registry": 0,
        "exact_tournament_reference": 0,
        "unresolved": 0,
    }
    for _, row in enriched.iterrows():
        context = _row_context(row)
        source = "observed_fields"
        name = normalize_tournament_name(_tournament_name(row))
        if context is None:
            context = season_registry_context(
                _tournament_name(row), event_date=_event_date(row),
            )
            source = "season_registry"
        if context is None and name in reference:
            context = reference[name]
            source = "exact_tournament_reference"
            recovered_names.add(name)
        if context is None:
            source = "unresolved"
        contexts.append(context)
        sources.append(source)
        counts[source] += 1
    enriched["surface_context"] = contexts
    enriched["surface_context_source"] = sources
    return enriched, {
        "schema_version": SCHEMA_VERSION,
        "rows": int(len(enriched)),
        "counts": counts,
        "recovered_tournament_names": len(recovered_names),
        "reference_names": len(reference),
        "market_used": False,
        "outcomes_used_for_resolution": False,
        "production_effect": False,
    }
