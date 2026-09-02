"""Bounded historical-coverage enrichment for CHANGE-2026-09-02-023.

This module is intentionally separate from production analysis. It expands the
history behind a fixed manifest, then attaches independently sourced facts
without overwriting the original RapidAPI records.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from . import fetch_data
from .historical_acquisition import HistoricalAcquirer
from .historical_warehouse import HistoricalWarehouse, payload_hash, utc_now


TENNIS_DATA_SOURCE = "tennis-data.co.uk"
ODDS_PAIRS = (
    ("PSW", "PSL", "Pinnacle"),
    ("AvgW", "AvgL", "market-average"),
    ("B365W", "B365L", "Bet365"),
    ("MaxW", "MaxL", "market-maximum"),
)


def _date(value: Any) -> datetime | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().astimezone(timezone.utc)


def _surface(value: Any) -> str | None:
    family = fetch_data._normalize_surface_family(value)
    return {"hard": "Hard", "clay": "Clay", "grass": "Grass", "carpet": "Carpet"}.get(family)


def _scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def _alias_index(names: Iterable[str]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = defaultdict(set)
    for name in names:
        canonical = str(name).strip()
        normalized = fetch_data._normalize_name(canonical)
        if not normalized:
            continue
        aliases[normalized].add(canonical)
        for alias in fetch_data._structural_name_candidates(normalized):
            aliases[alias].add(canonical)
    return aliases


def _resolve_name(name: Any, aliases: Mapping[str, set[str]]) -> str | None:
    candidates = aliases.get(fetch_data._normalize_name(str(name or "")), set())
    return next(iter(candidates)) if len(candidates) == 1 else None


def _source_record_key(tour: str, year: int, row_number: int, row: Mapping[str, Any]) -> str:
    material = {
        "tour": tour, "year": year, "row": row_number,
        "date": str(row.get("Date")), "winner": row.get("winner_name"),
        "loser": row.get("loser_name"), "tournament": row.get("Tournament"),
    }
    return f"{tour}:{year}:{payload_hash(material)}"


def load_tennis_data_year(
    tour: str,
    year: int,
    *,
    cache_dir: Path,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Use the existing loader, with a local-first persistent CSV cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{tour}_tdcouk_{year}.csv"
    if path.exists():
        frame = pd.read_csv(path)
        return frame, {"tour": tour, "year": year, "cache_hit": True, "downloaded": False}
    frame = fetch_data._load_tennisdata_couk(tour, year)
    if frame is None or frame.empty:
        return None, {"tour": tour, "year": year, "cache_hit": False, "downloaded": False}
    frame.to_csv(path, index=False)
    return frame, {"tour": tour, "year": year, "cache_hit": False, "downloaded": True}


def enrich_opponent_history(
    warehouse: HistoricalWarehouse,
    targets: list[Mapping[str, Any]],
    *,
    max_calls: int,
    required_prior_matches: int = 10,
    resume: bool = True,
) -> dict[str, Any]:
    """Acquire pages until each target player has ten strictly prior matches."""
    cutoffs: dict[tuple[str, str], str] = {}
    names: dict[tuple[str, str], str] = {}
    target_membership: dict[tuple[str, str], list[str]] = defaultdict(list)
    for target in targets:
        tour = str(target["tour"]).lower()
        cutoff = str(target["event_start_utc"])
        for side in ("a", "b"):
            player_id = target.get(f"player_{side}_id")
            if player_id is None:
                continue
            key = (tour, str(player_id))
            cutoffs[key] = min(cutoffs.get(key, cutoff), cutoff)
            names[key] = str(target.get(f"player_{side}_name") or player_id)
            target_membership[key].append(str(target["canonical_match_id"]))

    acquirer = HistoricalAcquirer(warehouse)
    players: list[dict[str, Any]] = []
    page_reports: list[dict[str, Any]] = []
    for (tour, player_id), cutoff in sorted(cutoffs.items()):
        initial_count = len(warehouse.player_matches_before(player_id, cutoff))
        before = initial_count
        already_sufficient = before >= required_prior_matches
        stop_reason = "already_sufficient" if already_sufficient else "not_started"
        iterations = 0
        calls_at_start = acquirer.metrics.calls_made
        cache_hits_at_start = acquirer.metrics.cache_hits
        pages_for_player = 0
        source_exhausted = False
        while before < required_prior_matches and acquirer.metrics.calls_made < max_calls:
            iterations += 1
            if iterations > 50:
                stop_reason = "iteration_guard"
                break
            result = acquirer.acquire_player_past_match_pages(
                tour, int(player_id), resume=resume, max_pages=1, max_calls=max_calls,
            )
            page_reports.extend(result.get("pages") or [])
            pages_for_player += len(result.get("pages") or [])
            source_exhausted = bool(result.get("source_exhausted"))
            after = len(warehouse.player_matches_before(player_id, cutoff))
            stop_reason = str(result.get("stop_reason") or "unknown")
            if after >= required_prior_matches:
                before = after
                stop_reason = "sufficient"
                break
            if result.get("source_exhausted") or stop_reason in {
                "failed", "budget_reached", "max_calls", "repeated_page",
                "non_advancing_page", "iteration_guard",
            }:
                before = after
                break
            if after == before and not result.get("pages"):
                stop_reason = "no_progress"
                break
            before = after
        final_count = len(warehouse.player_matches_before(player_id, cutoff))
        if acquirer.metrics.calls_made >= max_calls and final_count < required_prior_matches:
            stop_reason = "max_calls"
        players.append({
            "tour": tour.upper(), "player_id": player_id, "player_name": names[(tour, player_id)],
            "target_match_ids": list(dict.fromkeys(target_membership[(tour, player_id)])),
            "targets_count": len(set(target_membership[(tour, player_id)])),
            "earliest_target_cutoff": cutoff, "prior_matches": final_count,
            "prior_matches_before_acquisition": initial_count,
            "required_prior_matches": required_prior_matches,
            "already_sufficient": already_sufficient,
            "enriched_to_sufficient": not already_sufficient and final_count >= required_prior_matches,
            "prehistory_10_sufficient": final_count >= required_prior_matches,
            "sufficient": final_count >= required_prior_matches,
            "pages_required": pages_for_player,
            "calls_made": acquirer.metrics.calls_made - calls_at_start,
            "cache_hits": acquirer.metrics.cache_hits - cache_hits_at_start,
            "source_exhausted": source_exhausted,
            "stop_reason": stop_reason,
        })

    sufficient = sum(int(player["sufficient"]) for player in players)
    already_sufficient = sum(int(player["already_sufficient"]) for player in players)
    enriched = sum(int(player["enriched_to_sufficient"]) for player in players)
    return {
        "acquisition": acquirer.metrics.as_dict(),
        "players_total": len(players), "players_sufficient": sufficient,
        "players_already_sufficient": already_sufficient,
        "players_enriched_to_sufficient": enriched,
        "players_insufficient": len(players) - sufficient,
        "calls_per_player_enriched": round(acquirer.metrics.calls_made / enriched, 4) if enriched else None,
        "players": players, "page_reports": page_reports,
    }


def enrich_from_tennis_data(
    warehouse: HistoricalWarehouse,
    *,
    cache_dir: Path,
) -> dict[str, Any]:
    """Conservatively join annual source rows to warehouse matches."""
    matches = warehouse.list_matches()
    names = {
        str(value) for match in matches
        for value in (match.get("player_a_name"), match.get("player_b_name")) if value
    }
    aliases = _alias_index(names)
    years_by_tour: dict[str, set[int]] = defaultdict(set)
    for match in matches:
        parsed = _date(match.get("event_start_utc"))
        if parsed and match.get("tour"):
            years_by_tour[str(match["tour"]).lower()].add(parsed.year)

    source_rows: dict[tuple[str, frozenset[str]], list[dict[str, Any]]] = defaultdict(list)
    loads: list[dict[str, Any]] = []
    unresolved_source_names = 0
    odds_columns: set[str] = set()
    for tour, years in sorted(years_by_tour.items()):
        for year in sorted(years):
            frame, load = load_tennis_data_year(tour, year, cache_dir=cache_dir)
            loads.append(load)
            if frame is None:
                continue
            for row_number, (_, series) in enumerate(frame.iterrows()):
                row = series.to_dict()
                winner = _resolve_name(row.get("winner_name"), aliases)
                loser = _resolve_name(row.get("loser_name"), aliases)
                played = _date(row.get("Date") or row.get("tourney_date"))
                if not winner or not loser or not played:
                    unresolved_source_names += 1
                    continue
                record = {
                    "row": row, "winner": winner, "loser": loser, "date": played,
                    "source_record_key": _source_record_key(tour, year, row_number, row),
                }
                source_rows[(tour, frozenset((winner, loser)))].append(record)
                for winner_col, loser_col, _ in ODDS_PAIRS:
                    if winner_col in frame.columns and loser_col in frame.columns:
                        odds_columns.update((winner_col, loser_col))

    matched = ambiguous = unmatched = enrichments_added = conflicts = odds_stored = 0
    match_methods: dict[str, int] = defaultdict(int)
    for match in matches:
        tour = str(match.get("tour") or "").lower()
        pair = frozenset((str(match["player_a_name"]), str(match["player_b_name"])))
        target_date = _date(match.get("event_start_utc"))
        if not target_date:
            unmatched += 1
            continue
        pool = source_rows.get((tour, pair), [])
        exact = [record for record in pool if record["date"].date() == target_date.date()]
        method = "exact_pair_exact_date"
        candidates = exact
        if not exact:
            candidates = [
                record for record in pool
                if abs((record["date"].date() - target_date.date()).days) <= 1
            ]
            method = "exact_pair_date_window_1d"
        if len(candidates) != 1:
            ambiguous += int(len(candidates) > 1)
            unmatched += int(len(candidates) == 0)
            continue
        record = candidates[0]
        row = record["row"]
        matched += 1
        match_methods[method] += 1
        source_date = record["date"].date().isoformat()
        mapping: dict[str, Any] = {
            "surface": _surface(row.get("surface")),
            "tournament": _scalar(row.get("Tournament")),
            "tournament_level": _scalar(row.get("Series")),
        }
        winner_is_a = record["winner"] == match["player_a_name"]
        mapping["player_a_rank"] = _scalar(row.get("winner_rank") if winner_is_a else row.get("loser_rank"))
        mapping["player_b_rank"] = _scalar(row.get("loser_rank") if winner_is_a else row.get("winner_rank"))
        for field_name, value in mapping.items():
            if value is None or (not isinstance(value, str) and pd.isna(value)) or str(value).strip() == "":
                continue
            original = match.get(field_name)
            inserted = warehouse.add_match_enrichment({
                "match_id": match["canonical_match_id"], "field_name": field_name,
                "value": value, "source": TENNIS_DATA_SOURCE,
                "source_record_key": record["source_record_key"], "source_date": source_date,
                "temporal_class": "RECONSTRUCTED_EX_ANTE", "match_method": method,
                "match_confidence": "deterministic_unique",
                "payload_hash": payload_hash(record["source_record_key"]),
                "fetched_at_utc": utc_now(),
            })
            enrichments_added += int(inserted)
            conflicts += int(inserted and original is not None and str(original) != str(value))

        for winner_col, loser_col, bookmaker in ODDS_PAIRS:
            try:
                winner_odd, loser_odd = float(row.get(winner_col)), float(row.get(loser_col))
            except (TypeError, ValueError):
                continue
            if winner_odd <= 1 or loser_odd <= 1:
                continue
            selections = (
                (record["winner"], winner_odd), (record["loser"], loser_odd),
            )
            for selection, odd in selections:
                warehouse.add_market_quote({
                    "match_id": match["canonical_match_id"], "bookmaker": bookmaker,
                    "market": "moneyline", "selection": selection, "odd": odd,
                    "provider_timestamp": None, "temporal_role": "UNKNOWN",
                    "temporal_class": "UNAVAILABLE", "source": TENNIS_DATA_SOURCE,
                    "endpoint": f"annual-xlsx:{tour}:{target_date.year}",
                    "fetched_at_utc": utc_now(),
                    "payload_hash": payload_hash(record["source_record_key"]),
                })
                odds_stored += 1

    return {
        "source": TENNIS_DATA_SOURCE, "loads": loads,
        "years_tours_loaded": [
            {"tour": item.get("tour"), "year": item.get("year")}
            for item in loads if item.get("downloaded") or item.get("cache_hit")
        ],
        "downloads": sum(int(bool(item.get("downloaded"))) for item in loads),
        "cache_hits": sum(int(bool(item.get("cache_hit"))) for item in loads),
        "matches_considered": len(matches), "matches_matched": matched,
        "matches_unmatched": unmatched, "matches_ambiguous": ambiguous,
        "match_methods": dict(match_methods), "unresolved_source_rows": unresolved_source_names,
        "exact_matches": match_methods.get("exact_pair_exact_date", 0),
        "date_window_1d_matches": match_methods.get("exact_pair_date_window_1d", 0),
        "enrichments_added": enrichments_added, "conflicts_observed": conflicts,
        "odds_inventory_columns": sorted(odds_columns), "odds_quotes_attempted": odds_stored,
        "odds_temporal_class": "UNAVAILABLE",
    }
