"""Construção factual da ficha estruturada de jogador v2.

Os valores deste módulo servem a base pesquisável. Não são uma segunda
equação de pricing e, por omissão, ficam marcados como descritivos.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import statistics
from typing import Optional

import pandas as pd

from . import fetch_data
from .contextual_ranking import build_player_ranking_context
from .player_profile_contract import (
    DESCRIPTIVE_ONLY,
    MODEL_ACTIVE,
    build_profile_contract,
    make_metric,
)


def _played_rows(history: pd.DataFrame, player: str) -> pd.DataFrame:
    if history.empty:
        return history.iloc[0:0].copy()
    winner = history.get("winner_name", pd.Series(index=history.index, dtype=object))
    loser = history.get("loser_name", pd.Series(index=history.index, dtype=object))
    normalized = player.strip().casefold()
    mask = (
        winner.fillna("").astype(str).str.strip().str.casefold().eq(normalized)
        | loser.fillna("").astype(str).str.strip().str.casefold().eq(normalized)
    )
    return history.loc[mask].copy()


def _win_rate(wins: int, matches: int) -> float | None:
    return round(wins / matches, 6) if matches else None


def _history_dates(frame: pd.DataFrame) -> pd.Series:
    source = frame.get("tourney_date", pd.Series(index=frame.index, dtype=object))
    raw = source.astype("string").str.strip()
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    return compact.fillna(pd.to_datetime(raw, errors="coerce", utc=True))


def _rank_for_player(row: pd.Series, player: str) -> float | None:
    key = "winner_rank" if row.get("winner_name") == player else "loser_rank"
    value = pd.to_numeric(pd.Series([row.get(key)]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and float(value) > 0 else None


def _opponent_rank(row: pd.Series, player: str) -> float | None:
    key = "loser_rank" if row.get("winner_name") == player else "winner_rank"
    value = pd.to_numeric(pd.Series([row.get(key)]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and float(value) > 0 else None


def _record_metric(
    rows: pd.DataFrame, player: str, *, metric_id: str, label: str,
    family: str, source: str, context: dict | None = None,
) -> dict:
    matches = len(rows)
    wins = int((rows.get("winner_name", pd.Series(dtype=object)) == player).sum())
    return make_metric(
        metric_id=metric_id,
        label=label,
        family=family,
        value=_win_rate(wins, matches),
        unit="win_rate",
        sample_size=matches,
        source=source,
        model_role=DESCRIPTIVE_ONLY,
        applicable=matches > 0,
        context={"wins": wins, "losses": max(0, matches - wins), **(context or {})},
    )


def _yearly_ranking_summary(played: pd.DataFrame, player: str) -> list[dict]:
    if played.empty:
        return []
    rows = played.copy()
    rows["_date"] = _history_dates(rows)
    rows["_rank"] = rows.apply(lambda row: _rank_for_player(row, player), axis=1)
    rows = rows.dropna(subset=["_date", "_rank"]).sort_values("_date")
    result = []
    for year, group in rows.groupby(rows["_date"].dt.year):
        ranks = [float(value) for value in group["_rank"] if float(value) > 0]
        if not ranks:
            continue
        result.append({
            "year": int(year),
            "start_rank": round(ranks[0], 1),
            "end_rank": round(ranks[-1], 1),
            "best_rank": round(min(ranks), 1),
            "typical_rank": round(math.exp(statistics.median([math.log(rank) for rank in ranks])), 1),
            "observations": len(ranks),
        })
    return result


def _tier_key(row: pd.Series) -> str | None:
    raw = str(row.get("tier") or row.get("tourney_level") or "").strip().casefold()
    if not raw:
        return None
    if raw == "g" or "grand slam" in raw or "major" in raw:
        return "grand_slam"
    if raw == "m" or "masters 1000" in raw or "wta 1000" in raw:
        return "masters_1000"
    if raw == "f" or "finals" in raw:
        return "tour_finals"
    if "500" in raw:
        return "tour_500"
    if "250" in raw and "challenger" not in raw:
        return "tour_250"
    if "challenger" in raw or raw == "c":
        return "challenger"
    if "wta 125" in raw:
        return "wta_125"
    if raw == "a":
        return "main_tour_unspecified"
    return None


def _append_context_metrics(metrics: list[dict], played: pd.DataFrame, player: str) -> None:
    yearly = _yearly_ranking_summary(played, player)
    metrics.append(make_metric(
        metric_id="ranking_by_year",
        label="Evolução anual do ranking",
        family="structural_strength",
        value=yearly,
        unit="ranking_series",
        sample_size=sum(int(row["observations"]) for row in yearly),
        source="canonical_history_match_ranks",
        model_role=DESCRIPTIVE_ONLY,
        applicable=bool(yearly),
    ))

    rank_bands = (
        ("top3", "Contra Top 3", lambda rank: rank <= 3),
        ("top10", "Contra Top 10", lambda rank: rank <= 10),
        ("top20", "Contra Top 20", lambda rank: rank <= 20),
        ("top50", "Contra Top 50", lambda rank: rank <= 50),
        ("top100", "Contra Top 100", lambda rank: rank <= 100),
        ("outside_top100", "Contra ranking 100+", lambda rank: rank > 100),
    )
    ranked = played.copy()
    ranked["_opponent_rank"] = ranked.apply(lambda row: _opponent_rank(row, player), axis=1)
    ranked = ranked.dropna(subset=["_opponent_rank"])
    for key, label, predicate in rank_bands:
        subset = ranked[ranked["_opponent_rank"].map(predicate)]
        metrics.append(_record_metric(
            subset, player,
            metric_id=f"opponent_level_{key}",
            label=label,
            family="recent_form",
            source="canonical_history_opponent_rank_at_match",
            context={"bucket_type": "cumulative" if key != "outside_top100" else "exclusive"},
        ))

    tiered = played.copy()
    tiered["_tier_key"] = tiered.apply(_tier_key, axis=1)
    for key, label in (
        ("grand_slam", "Grand Slam"),
        ("masters_1000", "Masters/WTA 1000"),
        ("tour_finals", "Finals"),
        ("tour_500", "ATP/WTA 500"),
        ("tour_250", "ATP/WTA 250"),
        ("main_tour_unspecified", "Circuito principal sem categoria detalhada"),
        ("wta_125", "WTA 125"),
        ("challenger", "Challenger"),
    ):
        subset = tiered[tiered["_tier_key"] == key]
        metrics.append(_record_metric(
            subset, player,
            metric_id=f"tournament_level_{key}",
            label=label,
            family="recent_form",
            source="canonical_history_tournament_level",
        ))

    if "best_of" in played.columns:
        best_of = pd.to_numeric(played["best_of"], errors="coerce")
        for value, key, label in ((3, "bo3", "Melhor de 3"), (5, "bo5", "Melhor de 5")):
            metrics.append(_record_metric(
                played[best_of == value], player,
                metric_id=f"format_{key}",
                label=label,
                family="recent_form",
                source="canonical_history_best_of",
            ))

    venue = fetch_data.compute_indoor_outdoor_stats(played, player) or {}
    for key, label in (("indoor", "Indoor"), ("outdoor", "Outdoor")):
        record = venue.get(key) or {}
        matches = int(record.get("matches") or 0)
        wins = int(record.get("wins") or 0)
        metrics.append(make_metric(
            metric_id=f"venue_{key}_career",
            label=label,
            family="surface_conditions",
            value=_win_rate(wins, matches),
            unit="win_rate",
            sample_size=matches,
            source="canonical_history_venue_context",
            model_role=DESCRIPTIVE_ONLY,
            applicable=matches > 0,
            context={"wins": wins, "losses": max(0, matches - wins)},
        ))


def build_player_profile_v2_record(
    history: pd.DataFrame,
    player: str,
    tour: str,
    *,
    player_id: int | None = None,
    country: str | None = None,
    generated_at_utc: str | None = None,
) -> Optional[dict]:
    resolved = fetch_data.resolve_player_name(history, player)
    if resolved is None:
        return None

    played = _played_rows(history, resolved)
    metrics: list[dict] = []

    ranking = fetch_data.get_player_ranking(history, resolved)
    if ranking and ranking.get("rank") is not None:
        metrics.append(make_metric(
            metric_id="current_rank",
            label="Ranking atual observado",
            family="structural_strength",
            value=int(ranking["rank"]),
            unit="rank",
            sample_size=len(played),
            source="canonical_history_latest_rank",
            model_role=MODEL_ACTIVE,
            context={"as_of": ranking.get("as_of"), "points": ranking.get("points")},
        ))

    cutoff = pd.to_datetime(generated_at_utc, errors="coerce", utc=True)
    cutoff_dt = (
        cutoff.to_pydatetime()
        if not pd.isna(cutoff) else datetime.now(timezone.utc)
    )
    if "tourney_date" in history.columns and _history_dates(history).notna().any():
        ranking_context = build_player_ranking_context(
            history,
            resolved,
            cutoff=cutoff_dt,
            current_rank=(ranking or {}).get("rank"),
            current_points=(ranking or {}).get("points"),
        )
    else:
        ranking_context = {
            "current_rank": (ranking or {}).get("rank"),
            "current_points": (ranking or {}).get("points"),
            "historical_observation_count": 0,
            "evidence_status": "CURRENT_ONLY" if ranking else "MISSING",
            "long_layoff_detected": False,
            "return_phase": "NONE",
        }
    rank_sample = int(ranking_context.get("historical_observation_count") or 0)
    for metric_id, label, key, unit, model_role in (
        ("current_points", "Pontos atuais", "current_points", "points", MODEL_ACTIVE),
        ("representative_rank_365d", "Ranking típico nos últimos 365 dias", "typical_rank_365d", "rank", MODEL_ACTIVE),
        ("representative_rank_730d", "Ranking típico nos últimos 730 dias", "typical_rank_730d", "rank", DESCRIPTIVE_ONLY),
        ("observed_peak_rank", "Melhor ranking observado", "observed_peak_rank", "rank", DESCRIPTIVE_ONLY),
        ("rank_band_persistence_365d", "Persistência no patamar atual", "current_band_persistence_365d", "rate", DESCRIPTIVE_ONLY),
        ("matches_since_return", "Jogos desde o regresso", "matches_since_return", "matches", MODEL_ACTIVE),
    ):
        value = ranking_context.get(key)
        applicable = value is not None
        if key == "matches_since_return" and not ranking_context.get("long_layoff_detected"):
            value = None
            applicable = False
        metrics.append(make_metric(
            metric_id=metric_id,
            label=label,
            family="structural_strength",
            value=round(float(value), 6) if value is not None else None,
            unit=unit,
            sample_size=(
                int(ranking_context.get("matches_since_return") or 0)
                if key == "matches_since_return" else rank_sample
            ),
            source="contextual_ranking_v1",
            model_role=model_role,
            applicable=applicable,
            context={
                "return_phase": ranking_context.get("return_phase"),
                "evidence_status": ranking_context.get("evidence_status"),
            },
        ))

    for window in (5, 10, 20):
        form = fetch_data.compute_recent_form(history, resolved, window)
        matches = int((form or {}).get("matches") or 0)
        wins = int((form or {}).get("wins") or 0)
        metrics.append(make_metric(
            metric_id=f"recent_form_last_{window}",
            label=f"Resultados nos últimos {window} jogos",
            family="recent_form",
            value=_win_rate(wins, matches),
            unit="win_rate",
            sample_size=matches,
            source="canonical_history",
            model_role=DESCRIPTIVE_ONLY,
            applicable=matches > 0,
            context={"wins": wins, "losses": max(0, matches - wins), "window": window},
        ))

    surface_stats = fetch_data.compute_surface_stats(history, resolved) or {}
    for surface in ("Hard", "Clay", "Grass"):
        stats = surface_stats.get(surface) or {}
        matches = int(stats.get("matches") or 0)
        wins = int(stats.get("wins") or 0)
        metrics.append(make_metric(
            metric_id=f"surface_{surface.lower()}_career",
            label=f"Carreira em {surface}",
            family="surface_conditions",
            value=_win_rate(wins, matches),
            unit="win_rate",
            sample_size=matches,
            source="canonical_history",
            model_role=DESCRIPTIVE_ONLY,
            applicable=matches > 0,
            context={"wins": wins, "losses": max(0, matches - wins), "surface": surface.lower()},
        ))

    _append_context_metrics(metrics, played, resolved)

    serve = fetch_data.compute_serve_return_stats(history, resolved, 20) or {}
    serve_matches = int(serve.get("matches_used") or 0)
    for metric_id, label, key in (
        ("serve_first_won_recent", "Pontos ganhos no primeiro serviço", "avg_first_serve_won_pct"),
        ("serve_break_points_saved_recent", "Break points salvos", "avg_break_points_saved_pct"),
    ):
        raw_value = serve.get(key)
        metrics.append(make_metric(
            metric_id=metric_id,
            label=label,
            family="serve_return",
            value=round(float(raw_value), 6) if raw_value is not None else None,
            unit="rate",
            sample_size=serve_matches,
            source="canonical_history_point_stats",
            model_role=DESCRIPTIVE_ONLY,
            applicable=raw_value is not None and serve_matches > 0,
            context={"window": 20},
        ))

    identity = {"player_id": player_id, "country": country}
    if ranking:
        identity.update({
            "current_rank": ranking.get("rank"),
            "current_points": ranking.get("points"),
            "ranking_as_of": ranking.get("as_of"),
        })
    return build_profile_contract(
        player_name=resolved,
        tour=tour,
        overall_matches=len(played),
        metrics=metrics,
        generated_at_utc=generated_at_utc or datetime.now(timezone.utc).isoformat(),
        identity=identity,
    )
