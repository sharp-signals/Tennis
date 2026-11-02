from datetime import datetime, timedelta, timezone

import pandas as pd

from src.contextual_surface import (
    build_pair_surface_context,
    build_player_surface_context,
)


def _match(day, winner, loser, *, surface="Hard", indoor=None, pace=None):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner,
        "loser_name": loser,
        "surface": surface,
        "indoor": indoor,
        "court_pace_bucket": pace,
    }


def test_plain_hard_is_not_silently_assumed_outdoor():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=10), "A", "X", surface="Hard"),
    ])

    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
        current_venue="outdoor",
    )

    assert context["surface_record"]["matches"] == 1
    assert context["venue_record"]["matches"] == 0
    assert context["venue_observation_coverage"] == 0.0


def test_indoor_hard_overlap_is_measured_once_inside_one_family():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=10), "A", "X", indoor=True),
        _match(cutoff - timedelta(days=20), "Y", "A", indoor=True),
    ])

    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
        current_venue="indoor",
    )

    assert context["surface_record"]["matches"] == 2
    assert context["venue_record"]["matches"] == 2
    assert context["overlap_matches_surface_venue"] == 2
    assert context["component_independence"] is False
    assert context["family_contribution"] is None


def test_pace_is_not_applicable_on_clay():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=10), "A", "X", surface="Clay", pace="fast"),
    ])
    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Clay",
        current_pace_bucket="fast",
    )

    assert context["pace_applicability"] == "NOT_APPLICABLE_NON_HARD"
    assert context["pace_record"] is None


def test_hard_pace_bucket_remains_a_component_not_a_second_vote():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=10), "A", "X", pace="medium_fast"),
        _match(cutoff - timedelta(days=20), "Y", "A", pace="medium_fast"),
    ])
    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
        current_pace_bucket="medium_fast",
    )

    assert context["pace_applicability"] == "APPLICABLE"
    assert context["pace_record"]["matches"] == 2
    assert context["score"] is None
    assert context["weight"] is None


def test_transition_is_factual_and_same_day_is_excluded():
    cutoff = datetime(2026, 11, 2, 18, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=20), "A", "X", surface="Clay"),
        _match(cutoff - timedelta(days=10), "A", "Y", surface="Clay"),
        _match(cutoff, "A", "Z", surface="Hard"),
    ])
    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["historical_matches"] == 2
    assert context["recent_dominant_surface"] == "clay"
    assert context["matches_on_current_surface_last_35d"] == 0
    assert context["transition_observed"] is True


def test_recent_current_surface_exposure_clears_transition_observation():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=30), "A", "X", surface="Clay"),
        _match(cutoff - timedelta(days=20), "A", "Y", surface="Clay"),
        _match(cutoff - timedelta(days=3), "A", "Z", surface="Hard"),
    ])
    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["matches_on_current_surface_last_35d"] == 1
    assert context["days_since_current_surface"] == 3
    assert context["transition_observed"] is False


def test_pair_contract_forbids_adding_components_as_independent_weights():
    a = {"player": "A", "current_surface": "hard", "current_venue": "indoor",
         "surface_record": {"matches": 10}, "venue_record": {"matches": 5},
         "pace_record": {"matches": 4}, "transition_observed": False}
    b = {"player": "B", "current_surface": "hard", "current_venue": "indoor",
         "surface_record": {"matches": 12}, "venue_record": {"matches": 6},
         "pace_record": {"matches": 3}, "transition_observed": True}

    pair = build_pair_surface_context(a, b)

    assert pair["dependency_policy"] == "ONE_FAMILY_CONTRIBUTION_NOT_COMPONENT_SUM"
    assert pair["status"] == "READY"
    assert pair["context_consistent"] is True
    assert pair["score"] is None
    assert pair["leader"] is None
    assert pair["weight"] is None
    assert pair["production_effect"] is False


def test_pair_fails_closed_when_current_contexts_disagree():
    a = {"player": "A", "current_surface": "hard", "current_venue": "indoor",
         "current_pace_bucket": "fast"}
    b = {"player": "B", "current_surface": "hard", "current_venue": "outdoor",
         "current_pace_bucket": "fast"}

    pair = build_pair_surface_context(a, b)

    assert pair["status"] == "CONTEXT_MISMATCH"
    assert pair["context_consistent"] is False
    assert pair["family_contribution"] is None


def test_missing_player_identity_is_not_a_zero_surface_record():
    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    history = pd.DataFrame([
        _match(cutoff - timedelta(days=5), "X", "Y"),
    ])

    context = build_player_surface_context(
        history, "A", cutoff=cutoff, current_surface="Hard",
    )

    assert context["status"] == "IDENTITY_UNRESOLVED"
    assert "surface_record" not in context
    assert context["family_contribution"] is None
