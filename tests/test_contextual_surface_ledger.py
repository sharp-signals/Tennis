from datetime import date

from src.contextual_surface_ledger import (
    build_chronological_surface_ledger,
    build_provider_surface_ledger,
    exact_surface_context,
)


def test_exact_surface_context_keeps_indoor_separate_from_outdoor():
    assert exact_surface_context("Hard", indoor=True) == "hard_indoor"
    assert exact_surface_context("Hard", indoor=False) == "hard_outdoor"
    assert exact_surface_context("I.hard") == "hard_indoor"
    assert exact_surface_context("Hard") is None


def test_clay_and_grass_do_not_require_venue():
    assert exact_surface_context("Clay") == "clay"
    assert exact_surface_context("Grass") == "grass"


def test_provider_ledger_exposes_career_and_two_seasons_without_summing():
    performance = {
        "by_surface": {
            "hard": {"wins": 40, "losses": 30, "matches": 70},
            "hard_indoor": {"wins": 30, "losses": 20, "matches": 50},
        },
        "by_year": {
            "2025": {"court": {"3": {"aw": 6, "al": 4}}},
            "2026": {"court": {"3": {"aw": 8, "al": 2}}},
        },
    }
    ledger = build_provider_surface_ledger(
        performance, as_of=date(2026, 11, 3),
    )
    indoor = ledger["contexts"]["hard_indoor"]
    outdoor = ledger["contexts"]["hard_outdoor"]
    assert outdoor["career"]["matches"] == 70
    assert indoor["career"]["matches"] == 50
    assert indoor["previous_season"]["win_pct"] == 60.0
    assert indoor["current_season"]["win_pct"] == 80.0
    assert indoor["current_vs_previous_win_pct_pp"] == 20.0
    assert indoor["source_overlap_policy"] == "SELECT_ONE_SOURCE_NEVER_SUM"


def test_missing_year_is_missing_not_zero_or_neutral():
    ledger = build_provider_surface_ledger(
        {"by_surface": {"grass": {"wins": 4, "losses": 2}}},
        as_of=date(2026, 11, 3),
    )
    grass = ledger["contexts"]["grass"]
    assert grass["career"]["win_pct"] == 66.7
    assert grass["current_season"] is None
    assert grass["previous_season"] is None
    assert grass["current_vs_previous_win_pct_pp"] is None


def test_chronological_ledger_excludes_future_and_other_surfaces():
    observations = [
        {"event_date": "2025-04-01", "surface_context": "clay", "won": True},
        {"event_date": "2025-05-01", "surface_context": "clay", "won": False},
        {"event_date": "2026-02-01", "surface_context": "clay", "won": True},
        {"event_date": "2026-03-01", "surface_context": "hard_outdoor", "won": False},
        {"event_date": "2026-12-01", "surface_context": "clay", "won": True},
    ]
    ledger = build_chronological_surface_ledger(
        observations, context="clay", cutoff=date(2026, 11, 3),
    )
    assert ledger["career"]["matches"] == 3
    assert ledger["previous_season"]["win_pct"] == 50.0
    assert ledger["current_season"]["win_pct"] == 100.0
    assert ledger["future_matches_excluded"] is True
