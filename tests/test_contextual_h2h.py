from datetime import datetime, timedelta, timezone

import pandas as pd

from src.contextual_h2h import build_contextual_h2h


def _match(day, winner, loser, *, surface="Hard", score="6-4 6-4",
           context="atp_main", best_of=3, rank_winner=20, rank_loser=40):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner,
        "loser_name": loser,
        "surface": surface,
        "score": score,
        "_history_competition_scope": context,
        "best_of": best_of,
        "winner_rank": rank_winner,
        "loser_rank": rank_loser,
    }


def test_verified_no_h2h_is_coverage_without_impact():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=5), "A", "X"),
        _match(cutoff - timedelta(days=4), "B", "Y"),
    ])

    result = build_contextual_h2h(history, "A", "B", cutoff=cutoff)

    assert result["status"] == "OBSERVED_NONE"
    assert result["coverage_complete"] is True
    assert result["observed_matches"] == 0
    assert result["family_contribution"] is None


def test_unresolved_identity_is_not_reported_as_verified_zero():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=5), "A", "X"),
    ])

    result = build_contextual_h2h(history, "A", "B", cutoff=cutoff)

    assert result["status"] == "IDENTITY_UNRESOLVED"
    assert result["identity_a_observed"] is True
    assert result["identity_b_observed"] is False
    assert "coverage_complete" not in result


def test_unsearchable_source_is_distinct_from_no_h2h():
    result = build_contextual_h2h(
        pd.DataFrame([{"name": "not a match schema"}]), "A", "B",
        cutoff=datetime(2026, 11, 2, tzinfo=timezone.utc),
    )

    assert result["status"] == "SOURCE_UNAVAILABLE"
    assert result["matches"] == []
    assert result["production_effect"] is False


def test_old_cross_surface_and_recent_same_surface_remain_distinct():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=1500), "A", "B", surface="Clay"),
        _match(cutoff - timedelta(days=30), "A", "B", surface="Hard"),
    ])

    result = build_contextual_h2h(
        history, "A", "B", cutoff=cutoff, current_surface="Hard",
        current_context="atp_main", current_best_of=3,
    )

    assert result["status"] == "AVAILABLE"
    assert result["a_wins"] == 2
    assert result["same_surface_matches"] == 1
    assert result["most_recent_days_before_cutoff"] == 30
    assert result["score"] is None
    assert result["weight"] is None


def test_same_day_and_future_matches_are_excluded():
    cutoff = datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=1), "A", "B"),
        _match(cutoff, "B", "A"),
        _match(cutoff + timedelta(days=1), "B", "A"),
    ])

    result = build_contextual_h2h(history, "A", "B", cutoff=cutoff)

    assert result["observed_matches"] == 1
    assert result["a_wins"] == 1
    assert result["b_wins"] == 0


def test_retirement_is_visible_but_not_competitively_eligible():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=10), "A", "B", score="6-4 2-1 RET"),
    ])

    result = build_contextual_h2h(history, "A", "B", cutoff=cutoff)

    assert result["observed_matches"] == 1
    assert result["eligible_matches"] == 0
    assert result["non_standard_matches"] == 1
    assert result["a_win_share"] is None


def test_repeated_direction_is_factual_but_still_has_no_contribution():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    rows = [
        _match(cutoff - timedelta(days=30 * index), "A" if index < 5 else "B", "B" if index < 5 else "A")
        for index in range(1, 7)
    ]
    result = build_contextual_h2h(pd.DataFrame(rows), "A", "B", cutoff=cutoff)

    assert result["eligible_matches"] == 6
    assert result["a_wins"] == 4
    assert result["b_wins"] == 2
    assert result["direction_consistency"] == 4 / 6
    assert result["leader"] is None
    assert result["family_contribution"] is None


def test_challenger_encounter_is_preserved_as_different_context():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(
            cutoff - timedelta(days=120), "A", "B",
            context="challenger", surface="Hard",
        ),
    ])

    result = build_contextual_h2h(
        history, "A", "B", cutoff=cutoff, current_surface="Hard",
        current_context="atp_main",
    )

    assert result["matches"][0]["competition_context"] == "challenger"
    assert result["matches"][0]["same_competition_context"] is False
    assert result["same_surface_matches"] == 1
    assert result["same_context_matches"] == 0


def test_evolution_since_encounter_is_preserved_for_both_players():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(
            cutoff - timedelta(days=200), "A", "B",
            rank_winner=80, rank_loser=30,
        ),
    ])
    result = build_contextual_h2h(
        history, "A", "B", cutoff=cutoff,
        current_rank_a=40, current_rank_b=60,
    )
    match = result["matches"][0]

    assert match["ranking_strength_change_a_since_match"] > 0
    assert match["ranking_strength_change_b_since_match"] < 0
