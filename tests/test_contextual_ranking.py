from datetime import datetime, timedelta, timezone

import pandas as pd

from src.contextual_ranking import (
    build_pair_ranking_context,
    build_player_ranking_context,
)


def _match(day, winner, loser, winner_rank, loser_rank, winner_points=None, loser_points=None):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner,
        "loser_name": loser,
        "winner_rank": winner_rank,
        "loser_rank": loser_rank,
        "winner_rank_points": winner_points,
        "loser_rank_points": loser_points,
    }


def test_pair_preserves_continuous_gap_without_assigning_score_or_weight():
    a = {"player": "A", "current_rank": 40, "current_points": 1100,
         "historical_observation_count": 5}
    b = {"player": "B", "current_rank": 60, "current_points": 850,
         "historical_observation_count": 5}

    pair = build_pair_ranking_context(a, b)

    assert pair["absolute_rank_gap"] == 20
    assert pair["current_rank_log_ratio_a_minus_b"] > 0
    assert pair["score"] is None
    assert pair["leader"] is None
    assert pair["weight"] is None
    assert pair["production_effect"] is False


def test_large_structural_gap_is_larger_than_nearby_rank_gap():
    close = build_pair_ranking_context(
        {"player": "A", "current_rank": 40},
        {"player": "B", "current_rank": 60},
    )
    wide = build_pair_ranking_context(
        {"player": "A", "current_rank": 10},
        {"player": "B", "current_rank": 200},
    )

    assert wide["current_rank_log_ratio_a_minus_b"] > close["current_rank_log_ratio_a_minus_b"]


def test_history_is_strictly_ex_ante_and_preserves_observed_peak():
    cutoff = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(cutoff - timedelta(days=365), "A", "X", 30, 50, 1500, 900),
        _match(cutoff - timedelta(days=20), "Y", "A", 20, 80, 1800, 600),
        _match(cutoff, "A", "Z", 75, 100, 650, 400),
        _match(cutoff + timedelta(days=1), "A", "Q", 70, 120, 700, 300),
    ])

    context = build_player_ranking_context(
        frame, "A", cutoff=cutoff, current_rank=75, current_points=650,
        days_since_last_match=20,
    )

    assert context["historical_observation_count"] == 2
    assert context["observed_peak_rank"] == 30
    assert context["last_observed_rank"] == 80
    assert context["current_vs_observed_peak_log_ratio"] > 0
    assert context["days_since_last_match"] == 20


def test_missing_history_is_not_converted_to_neutral_or_zero():
    context = build_player_ranking_context(
        pd.DataFrame(), "A",
        cutoff=datetime(2026, 11, 2, tzinfo=timezone.utc),
        current_rank=42,
    )

    assert context["evidence_status"] == "CURRENT_ONLY"
    assert context["observed_peak_rank"] is None
    assert context["ranking_strength_change_6m"] is None


def test_returning_former_top_player_is_exposed_but_not_auto_promoted():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(cutoff - timedelta(days=300), "A", "X", 30, 70, 1400, 700),
    ])
    context = build_player_ranking_context(
        frame, "A", cutoff=cutoff, current_rank=110, current_points=450,
        days_since_last_match=190,
    )

    assert context["observed_peak_rank"] == 30
    assert context["current_rank"] == 110
    assert context["days_since_last_match"] == 190
    assert context["current_vs_observed_peak_log_ratio"] > 0
    assert context["production_effect"] is False


def test_weekly_history_does_not_overweight_multiple_matches_in_same_week():
    cutoff = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(cutoff - timedelta(days=20), "A", "X", 40, 90),
        _match(cutoff - timedelta(days=19), "A", "Y", 39, 80),
        _match(cutoff - timedelta(days=12), "Z", "A", 20, 42),
        _match(cutoff, "A", "Q", 15, 30),
    ])
    context = build_player_ranking_context(
        frame, "A", cutoff=cutoff, current_rank=41,
    )
    assert context["weekly_rank_observations_365d"] == 2
    assert 39 <= context["typical_rank_365d"] <= 42
    assert context["current_band_persistence_365d"] == 1.0


def test_rank_outside_current_band_reduces_persistence_without_becoming_vote():
    cutoff = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(cutoff - timedelta(days=120), "A", "X", 85, 100),
        _match(cutoff - timedelta(days=60), "A", "Y", 70, 100),
        _match(cutoff - timedelta(days=10), "A", "Z", 38, 100),
    ])
    context = build_player_ranking_context(
        frame, "A", cutoff=cutoff, current_rank=35,
    )
    assert context["weekly_rank_observations_365d"] == 3
    assert context["current_band_persistence_365d"] == 1 / 3
    assert context["current_vs_typical_365d_log_ratio"] < 0
