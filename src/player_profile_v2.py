"""Construção factual da ficha estruturada de jogador v2.

Os valores deste módulo servem a base pesquisável. Não são uma segunda
equação de pricing e, por omissão, ficam marcados como descritivos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import fetch_data
from .player_profile_contract import DESCRIPTIVE_ONLY, build_profile_contract, make_metric


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
            model_role=DESCRIPTIVE_ONLY,
            context={"as_of": ranking.get("as_of"), "points": ranking.get("points")},
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
