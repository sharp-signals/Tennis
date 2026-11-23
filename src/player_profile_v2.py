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
    assess_sample,
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


def _rows_before(played: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    if played.empty:
        return played.copy()
    rows = played.copy()
    rows["_date"] = _history_dates(rows)
    return rows[rows["_date"].notna() & (rows["_date"] < pd.Timestamp(cutoff))].copy()


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


def _append_recent_quality_metrics(
    metrics: list[dict], played: pd.DataFrame, player: str, cutoff: datetime,
) -> None:
    dated = _rows_before(played, cutoff)
    start = pd.Timestamp(cutoff) - pd.Timedelta(days=90)
    recent = dated[dated["_date"] >= start].copy()
    recent["_player_rank"] = recent.apply(lambda row: _rank_for_player(row, player), axis=1)
    recent["_opponent_rank"] = recent.apply(lambda row: _opponent_rank(row, player), axis=1)
    ranked = recent.dropna(subset=["_player_rank", "_opponent_rank"])
    wins = ranked[ranked["winner_name"] == player]
    losses = ranked[ranked["loser_name"] == player]
    quality_wins = wins[wins["_opponent_rank"] < wins["_player_rank"]]
    costly_losses = losses[losses["_opponent_rank"] > losses["_player_rank"]]

    for metric_id, label, subset, denominator, event in (
        (
            "recent_90d_quality_wins",
            "Vitórias sobre adversários melhor classificados · 90 dias",
            quality_wins,
            wins,
            "quality_win",
        ),
        (
            "recent_90d_costly_losses",
            "Derrotas com adversários pior classificados · 90 dias",
            costly_losses,
            losses,
            "costly_loss",
        ),
    ):
        count = len(subset)
        sample = len(denominator)
        examples = []
        for _, row in subset.sort_values("_date", ascending=False).head(5).iterrows():
            opponent = row.get("loser_name") if row.get("winner_name") == player else row.get("winner_name")
            examples.append({
                "date": row["_date"].date().isoformat(),
                "opponent": opponent,
                "player_rank": round(float(row["_player_rank"]), 1),
                "opponent_rank": round(float(row["_opponent_rank"]), 1),
                "tournament": row.get("tourney_name"),
            })
        metrics.append(make_metric(
            metric_id=metric_id,
            label=label,
            family="recent_form",
            value=_win_rate(count, sample),
            unit="rate_within_ranked_results",
            sample_size=sample,
            source="canonical_history_match_ranks",
            model_role=DESCRIPTIVE_ONLY,
            applicable=sample > 0,
            context={
                "event": event,
                "count": count,
                "ranked_result_sample": sample,
                "window_days": 90,
                "examples": examples,
            },
        ))


def _append_season_surface_metrics(
    metrics: list[dict], played: pd.DataFrame, player: str, cutoff: datetime,
) -> None:
    dated = _rows_before(played, cutoff)
    if dated.empty:
        series = []
    else:
        dated["_year"] = dated["_date"].dt.year
        dated["_surface"] = dated.get(
            "surface", pd.Series(index=dated.index, dtype=object)
        ).fillna("").astype(str).str.strip().str.casefold()
        series = []
        for year in sorted(dated["_year"].dropna().unique()):
            year_rows = dated[dated["_year"] == year]
            point = {"year": int(year), "overall": _series_record(year_rows, player)}
            for surface in ("hard", "clay", "grass"):
                point[surface] = _series_record(
                    year_rows[year_rows["_surface"] == surface], player,
                )
            series.append(point)
    metrics.append(make_metric(
        metric_id="season_surface_evolution",
        label="Evolução por época e superfície",
        family="surface_conditions",
        value=series,
        unit="season_surface_series",
        sample_size=sum(point["overall"]["matches"] for point in series),
        source="canonical_history",
        model_role=DESCRIPTIVE_ONLY,
        applicable=bool(series),
        context={"surfaces": ["hard", "clay", "grass"]},
    ))


def _series_record(rows: pd.DataFrame, player: str) -> dict:
    matches = len(rows)
    wins = int((rows.get("winner_name", pd.Series(dtype=object)) == player).sum())
    return {
        "matches": matches,
        "wins": wins,
        "losses": max(0, matches - wins),
        "win_rate": _win_rate(wins, matches),
        "sample_assessment": assess_sample(matches, applicable=matches > 0),
    }


def _append_odds_metrics(
    metrics: list[dict], odds_history: pd.DataFrame, player: str, cutoff: datetime,
) -> None:
    if odds_history is None or odds_history.empty:
        return
    evidence = fetch_data.compute_historical_moneyline_margins(
        odds_history, player, before=cutoff,
    )
    if not evidence:
        return
    source = str(evidence.get("source") or "historical_odds_cache")
    basis = evidence.get("odds_basis")
    favorite_n = 0
    favorite_wins = 0
    for band, cell in (evidence.get("buckets") or {}).items():
        n = int(cell.get("n") or 0)
        wins = int(cell.get("wins") or 0)
        if not n:
            continue
        slug = band.replace(".", "_").replace("-", "_")
        metrics.append(make_metric(
            metric_id=f"moneyline_odds_band_{slug}",
            label=f"Moneyline observada {band}",
            family="historical_market_context",
            value=round(wins / n, 6),
            unit="win_rate",
            sample_size=n,
            source=source,
            model_role=DESCRIPTIVE_ONLY,
            context={
                "wins": wins,
                "losses": max(0, n - wins),
                "odds_band": band,
                "mean_game_diff": cell.get("mean_game_diff"),
                "by_format": cell.get("by_format") or {},
                "odds_basis": basis,
            },
        ))
        try:
            upper = float(band.split("-", 1)[1])
        except (IndexError, TypeError, ValueError):
            upper = 99.0
        if upper <= 2.0:
            favorite_n += n
            favorite_wins += wins

    if favorite_n:
        metrics.append(make_metric(
            metric_id="moneyline_observed_1_20_to_2_00",
            label="Quando a odd observada ficou entre 1.20 e 2.00",
            family="historical_market_context",
            value=round(favorite_wins / favorite_n, 6),
            unit="win_rate",
            sample_size=favorite_n,
            source=source,
            model_role=DESCRIPTIVE_ONLY,
            context={
                "wins": favorite_wins,
                "losses": favorite_n - favorite_wins,
                "definition": "bandas disponíveis de odd observada entre 1.20 e 2.00",
                "odds_basis": basis,
            },
        ))
    underdog = evidence.get("underdog") or {}
    underdog_n = int(underdog.get("n") or 0)
    underdog_wins = int(underdog.get("wins") or 0)
    if underdog_n:
        metrics.append(make_metric(
            metric_id="moneyline_observed_above_2_00",
            label="Quando a odd observada foi superior a 2.00",
            family="historical_market_context",
            value=round(underdog_wins / underdog_n, 6),
            unit="win_rate",
            sample_size=underdog_n,
            source=source,
            model_role=DESCRIPTIVE_ONLY,
            context={
                "wins": underdog_wins,
                "losses": underdog_n - underdog_wins,
                "definition": "odd observada do jogador > 2.00",
                "mean_game_diff": underdog.get("mean_game_diff"),
                "by_format": underdog.get("by_format") or {},
                "odds_basis": basis,
            },
        ))

def build_player_profile_v2_record(
    history: pd.DataFrame,
    player: str,
    tour: str,
    *,
    odds_history: pd.DataFrame | None = None,
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
    _append_recent_quality_metrics(metrics, played, resolved, cutoff_dt)
    _append_season_surface_metrics(metrics, played, resolved, cutoff_dt)
    _append_odds_metrics(metrics, odds_history, resolved, cutoff_dt)

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
