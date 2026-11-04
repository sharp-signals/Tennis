import pandas as pd

from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
    season_registry_context,
)


def test_user_confirmed_2026_indoor_registry_is_season_aware():
    assert season_registry_context(
        "Grand Prix Auvergne-Rhone-Alpes - Lyon",
        event_date="2026-10-20",
    ) == "hard_indoor"
    assert season_registry_context(
        "Open Parc - Lyon", event_date="2024-05-20",
    ) is None


def test_exact_name_reference_recovers_only_unambiguous_context():
    frame = pd.DataFrame([
        {
            "date": "2026-02-01", "tourney_name": "Open Occitanie - Montpellier",
            "surface": "Hard", "indoor": True,
        },
        {
            "date": "2025-02-01", "tourney_name": "Open Occitanie - Montpellier",
            "surface": None, "indoor": None,
        },
    ])
    enriched, audit = enrich_tournament_surface_contexts(frame)
    assert enriched.loc[1, "surface_context"] == "hard_indoor"
    assert enriched.loc[1, "surface_context_source"] == "exact_tournament_reference"
    assert audit["counts"]["exact_tournament_reference"] == 1
    assert audit["outcomes_used_for_resolution"] is False


def test_conflicting_observed_contexts_are_not_propagated():
    frame = pd.DataFrame([
        {"date": "2026-01-01", "tourney_name": "Example", "surface": "Clay"},
        {
            "date": "2026-02-01", "tourney_name": "Example",
            "surface": "Hard", "indoor": True,
        },
        {"date": "2025-01-01", "tourney_name": "Example", "surface": None},
    ])
    enriched, audit = enrich_tournament_surface_contexts(frame)
    assert pd.isna(enriched.loc[2, "surface_context"])
    assert audit["counts"]["unresolved"] == 1


def test_provider_indoor_codes_are_observed_fields():
    frame = pd.DataFrame([
        {
            "date": "2025-10-01", "tourney_name": "Metz",
            "surface": "Hard", "indoor": "I",
        },
        {
            "date": "2025-08-01", "tourney_name": "Cincinnati",
            "surface": "Hard", "indoor": "O",
        },
    ])
    enriched, audit = enrich_tournament_surface_contexts(frame)
    assert enriched["surface_context"].tolist() == [
        "hard_indoor", "hard_outdoor",
    ]
    assert audit["counts"]["observed_fields"] == 2
