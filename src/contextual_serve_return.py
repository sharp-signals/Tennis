"""Secondary serve/return context for the next-generation factor model."""

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
    return parsed if math.isfinite(parsed) else None


def _positive(value: Any) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _surface(value: Any) -> str | None:
    text = _name(value)
    if "clay" in text or "terra" in text:
        return "clay"
    if "grass" in text or "relva" in text:
        return "grass"
    if "hard" in text or "duro" in text or "carpet" in text:
        return "hard"
    return None


def _dates(frame: pd.DataFrame) -> pd.Series:
    source = frame.get("event_date")
    if source is None:
        source = frame.get("tourney_date", pd.Series(index=frame.index, dtype="object"))
    raw = source.astype("string").str.strip()
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    return compact.fillna(pd.to_datetime(raw, errors="coerce", utc=True))


def _valid_ratio(numerator: float | None, denominator: float | None) -> bool:
    return (
        numerator is not None and denominator is not None
        and denominator > 0 and 0 <= numerator <= denominator
    )


def _extract_match(row: pd.Series, *, player_won: bool) -> dict[str, Any] | None:
    own = "w_" if player_won else "l_"
    opp = "l_" if player_won else "w_"

    def field(prefix: str, name: str) -> float | None:
        return _number(row.get(f"{prefix}{name}"))

    own_svpt = _positive(field(own, "svpt"))
    opp_svpt = _positive(field(opp, "svpt"))
    if own_svpt is None or opp_svpt is None:
        return None
    own_first_in = field(own, "1stIn")
    own_first_won = field(own, "1stWon")
    own_second_won = field(own, "2ndWon")
    opp_first_won = field(opp, "1stWon")
    opp_second_won = field(opp, "2ndWon")
    own_bp_saved = field(own, "bpSaved")
    own_bp_faced = field(own, "bpFaced")
    opp_bp_saved = field(opp, "bpSaved")
    opp_bp_faced = field(opp, "bpFaced")
    own_service_games = _positive(field(own, "SvGms"))
    opp_service_games = _positive(field(opp, "SvGms"))

    return {
        "service_points_won": (
            own_first_won + own_second_won
            if own_first_won is not None and own_second_won is not None
            and _valid_ratio(own_first_won + own_second_won, own_svpt)
            else None
        ),
        "service_points": own_svpt,
        "first_serve_points_won": (
            own_first_won
            if _valid_ratio(own_first_won, own_first_in) else None
        ),
        "first_serve_points": own_first_in,
        "return_points_won": (
            opp_svpt - opp_first_won - opp_second_won
            if opp_first_won is not None and opp_second_won is not None
            and _valid_ratio(opp_first_won + opp_second_won, opp_svpt)
            else None
        ),
        "return_points": opp_svpt,
        "holds": (
            own_service_games - (own_bp_faced - own_bp_saved)
            if own_service_games is not None
            and own_bp_faced is not None and own_bp_saved is not None
            and _valid_ratio(own_bp_faced - own_bp_saved, own_service_games)
            else None
        ),
        "service_games": own_service_games,
        "breaks": (
            opp_bp_faced - opp_bp_saved
            if opp_service_games is not None
            and opp_bp_faced is not None and opp_bp_saved is not None
            and _valid_ratio(opp_bp_faced - opp_bp_saved, opp_service_games)
            else None
        ),
        "return_games": opp_service_games,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def ratio(num_key: str, den_key: str) -> tuple[float | None, float]:
        usable = [
            row for row in rows
            if row.get(num_key) is not None and row.get(den_key) is not None
        ]
        numerator = sum(float(row[num_key]) for row in usable)
        denominator = sum(float(row[den_key]) for row in usable)
        return (
            (100.0 * numerator / denominator if denominator > 0 else None),
            denominator,
        )

    service, service_points = ratio("service_points_won", "service_points")
    first, first_points = ratio("first_serve_points_won", "first_serve_points")
    returns, return_points = ratio("return_points_won", "return_points")
    hold, service_games = ratio("holds", "service_games")
    breaks, return_games = ratio("breaks", "return_games")
    return {
        "matches": len(rows),
        "service_points_won_pct": service,
        "first_serve_points_won_pct": first,
        "return_points_won_pct": returns,
        "hold_pct": hold,
        "break_pct": breaks,
        "service_points_sample": service_points,
        "first_serve_points_sample": first_points,
        "return_points_sample": return_points,
        "service_games_sample": service_games,
        "return_games_sample": return_games,
    }


def build_player_serve_return_context(
    history: pd.DataFrame,
    player: str,
    *,
    cutoff: datetime,
    current_surface: Any = None,
) -> dict[str, Any]:
    """Build ex-ante service/return evidence as a secondary context."""
    surface_now = _surface(current_surface)
    base = {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "player": player,
        "cutoff": cutoff.isoformat(),
        "current_surface": surface_now,
        "family": "serve_return_context",
        "governance_priority": "SECONDARY_BELOW_RECENT_FORM",
        "standalone_signal_allowed": False,
        "may_override_primary_families": False,
        "career_and_recent_are_independent_votes": False,
        "score": None,
        "leader": None,
        "weight": None,
        "family_contribution": None,
        "market_used": False,
        "production_effect": False,
    }
    minimum = {
        "winner_name", "loser_name", "w_svpt", "l_svpt",
        "w_1stWon", "l_1stWon", "w_2ndWon", "l_2ndWon",
    }
    if history is None or history.empty or not minimum.issubset(history.columns):
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

    rows: list[dict[str, Any]] = []
    excluded_non_standard = 0
    for _, row in played.sort_values("_date").iterrows():
        score = str(row.get("score") or "")
        if score and _NON_STANDARD.search(score):
            excluded_non_standard += 1
            continue
        player_won = _name(row.get("winner_name")) == wanted
        extracted = _extract_match(row, player_won=player_won)
        if extracted is None:
            continue
        opponent_rank = _positive(
            row.get("loser_rank") if player_won else row.get("winner_rank")
        )
        rows.append({
            **extracted,
            "event_date": row["_date"].date().isoformat(),
            "days_before_cutoff": (cutoff_utc.date() - row["_date"].date()).days,
            "surface": _surface(row.get("surface")),
            "opponent_rank": opponent_rank,
        })

    if not rows:
        return {
            **base,
            "status": "NO_USABLE_POINT_LEVEL_AGGREGATES",
            "excluded_non_standard_matches": excluded_non_standard,
        }
    current_surface_rows = [
        row for row in rows if surface_now is not None and row["surface"] == surface_now
    ]
    recent_90_rows = [row for row in rows if row["days_before_cutoff"] <= 90]
    recent_90_surface_rows = [
        row for row in recent_90_rows
        if surface_now is not None and row["surface"] == surface_now
    ]
    ranked = [row for row in rows if row["opponent_rank"] is not None]
    return {
        **base,
        "status": "AVAILABLE",
        "usable_matches": len(rows),
        "excluded_non_standard_matches": excluded_non_standard,
        "career_all": _aggregate(rows),
        "career_current_surface": _aggregate(current_surface_rows),
        "recent_90d_all": _aggregate(recent_90_rows),
        "recent_90d_current_surface": _aggregate(recent_90_surface_rows),
        "opponent_rank_coverage": len(ranked) / len(rows),
        "opponent_rank_median": (
            float(pd.Series([row["opponent_rank"] for row in ranked]).median())
            if ranked else None
        ),
        "opponent_adjustment_status": (
            "FACTS_AVAILABLE_NOT_YET_CALIBRATED" if ranked
            else "RANKING_UNAVAILABLE"
        ),
    }


def build_pair_serve_return_context(
    player_a: dict[str, Any],
    player_b: dict[str, Any],
) -> dict[str, Any]:
    """Pair contexts without promoting raw percentages to a primary signal."""
    context_consistent = (
        player_a.get("current_surface") == player_b.get("current_surface")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "OBSERVATIONAL_ONLY",
        "family": "serve_return_context",
        "status": "READY" if context_consistent else "CONTEXT_MISMATCH",
        "context_consistent": context_consistent,
        "player_a": player_a.get("player"),
        "player_b": player_b.get("player"),
        "current_surface": player_a.get("current_surface"),
        "career_baseline": {
            "a": player_a.get("career_current_surface") or player_a.get("career_all"),
            "b": player_b.get("career_current_surface") or player_b.get("career_all"),
        },
        "recent_context": {
            "a": player_a.get("recent_90d_current_surface") or player_a.get("recent_90d_all"),
            "b": player_b.get("recent_90d_current_surface") or player_b.get("recent_90d_all"),
        },
        "dependency_policy": (
            "CAREER_IS_BASELINE_RECENT_IS_DEVIATION_SINGLE_SECONDARY_FAMILY"
        ),
        "governance_priority": "SECONDARY_BELOW_RECENT_FORM",
        "standalone_signal_allowed": False,
        "may_override_primary_families": False,
        "score": None,
        "leader": None,
        "weight": None,
        "family_contribution": None,
        "market_used": False,
        "production_effect": False,
    }
