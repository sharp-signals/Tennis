from datetime import datetime, timedelta, timezone

import pandas as pd

from src.contextual_serve_return import (
    build_pair_serve_return_context,
    build_player_serve_return_context,
)


def _match(day, winner="A", loser="B", *, surface="Hard", score="6-4 6-4",
           winner_rank=20, loser_rank=40):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner, "loser_name": loser,
        "surface": surface, "score": score,
        "winner_rank": winner_rank, "loser_rank": loser_rank,
        "w_svpt": 100, "w_1stIn": 60, "w_1stWon": 42, "w_2ndWon": 20,
        "w_bpSaved": 5, "w_bpFaced": 8, "w_SvGms": 12,
        "l_svpt": 100, "l_1stIn": 60, "l_1stWon": 36, "l_2ndWon": 16,
        "l_bpSaved": 4, "l_bpFaced": 9, "l_SvGms": 11,
    }


def test_service_and_return_are_aggregated_from_points_not_match_averages():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    context = build_player_serve_return_context(
        pd.DataFrame([_match(cutoff - timedelta(days=10))]),
        "A", cutoff=cutoff, current_surface="Hard",
    )
    metrics = context["recent_90d_current_surface"]

    assert metrics["service_points_won_pct"] == 62.0
    assert metrics["return_points_won_pct"] == 48.0
    assert metrics["hold_pct"] == 75.0
    assert round(metrics["break_pct"], 6) == round(100 * 5 / 11, 6)


def test_same_day_and_future_are_excluded():
    cutoff = datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=1)),
        _match(cutoff),
        _match(cutoff + timedelta(days=1)),
    ])
    context = build_player_serve_return_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["usable_matches"] == 1


def test_retirement_is_excluded_from_comparable_service_context():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=5), score="6-4 2-1 RET"),
        _match(cutoff - timedelta(days=10)),
    ])
    context = build_player_serve_return_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["usable_matches"] == 1
    assert context["excluded_non_standard_matches"] == 1


def test_surface_specific_and_recent_views_are_not_independent_votes():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=10), surface="Hard"),
        _match(cutoff - timedelta(days=200), surface="Hard"),
        _match(cutoff - timedelta(days=20), surface="Clay"),
    ])
    context = build_player_serve_return_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["career_all"]["matches"] == 3
    assert context["career_current_surface"]["matches"] == 2
    assert context["recent_90d_all"]["matches"] == 2
    assert context["recent_90d_current_surface"]["matches"] == 1
    assert context["career_and_recent_are_independent_votes"] is False


def test_opponent_quality_is_preserved_but_not_pretended_adjusted():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    context = build_player_serve_return_context(
        pd.DataFrame([
            _match(cutoff - timedelta(days=10), loser_rank=10),
            _match(cutoff - timedelta(days=20), loser_rank=100),
        ]),
        "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["opponent_rank_coverage"] == 1.0
    assert context["opponent_rank_median"] == 55.0
    assert context["opponent_adjustment_status"] == "FACTS_AVAILABLE_NOT_YET_CALIBRATED"


def test_pair_is_secondary_and_cannot_create_standalone_signal():
    a = {"player": "A", "current_surface": "hard", "career_all": {"matches": 50},
         "recent_90d_all": {"matches": 8}}
    b = {"player": "B", "current_surface": "hard", "career_all": {"matches": 60},
         "recent_90d_all": {"matches": 9}}
    pair = build_pair_serve_return_context(a, b)

    assert pair["status"] == "READY"
    assert pair["governance_priority"] == "SECONDARY_BELOW_RECENT_FORM"
    assert pair["standalone_signal_allowed"] is False
    assert pair["may_override_primary_families"] is False
    assert pair["score"] is None
    assert pair["weight"] is None


def test_missing_columns_are_source_unavailable_not_zero_performance():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    context = build_player_serve_return_context(
        pd.DataFrame([{"winner_name": "A", "loser_name": "B"}]),
        "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["status"] == "SOURCE_UNAVAILABLE"
    assert context["family_contribution"] is None
