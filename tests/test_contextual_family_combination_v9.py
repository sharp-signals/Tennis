import numpy as np

from src.contextual_family_combination_v2 import FAMILY_ORDER
from src.contextual_family_combination_v9 import (
    META_FAMILIES,
    h2h_sample_reliability,
    hierarchy_v9_projector,
    prepare_contextual_meta_rows,
)


def _row(*, recent=0.7, structural=0.65, h2h=0.25, h2h_sample=1):
    return {
        "target_a_win": True,
        "family_probabilities": {
            "recent_form": recent,
            "structural_strength": structural,
            "surface_conditions": 0.6,
            "matchup_h2h": h2h,
            "serve_return": 0.55,
        },
        "family_states": {
            family: {"data_state": "OBSERVED"} for family in FAMILY_ORDER
        },
        "samples": {"h2h": h2h_sample},
    }


def _columns():
    columns = []
    for family in META_FAMILIES:
        columns.extend([
            f"{family}__logit",
            f"{family}__unavailable",
            f"{family}__observed_none",
        ])
    return columns


def test_single_h2h_is_factual_but_has_no_directional_vote():
    prepared = prepare_contextual_meta_rows([_row()])[0]
    assert prepared["family_probabilities"]["matchup_h2h"] == 0.5
    assert prepared["combination_context_v9"]["h2h_sample"] == 1
    assert prepared["combination_context_v9"]["h2h_reliability"] == 0.0


def test_h2h_reliability_grows_after_first_match_and_is_capped():
    assert h2h_sample_reliability(0) == 0.0
    assert h2h_sample_reliability(1) == 0.0
    assert h2h_sample_reliability(2) == 1.0 / 3.0
    assert h2h_sample_reliability(3) == 2.0 / 3.0
    assert h2h_sample_reliability(4) == 1.0
    assert h2h_sample_reliability(20) == 1.0


def test_single_neutral_ablation_only_suppresses_one_h2h():
    single, repeated = prepare_contextual_meta_rows(
        [_row(h2h_sample=1), _row(h2h_sample=2)],
        h2h_policy="single_neutral",
    )
    assert single["family_probabilities"]["matchup_h2h"] == 0.5
    assert repeated["family_probabilities"]["matchup_h2h"] == 0.25


def test_raw_h2h_ablation_preserves_single_h2h_signal():
    prepared = prepare_contextual_meta_rows(
        [_row(h2h_sample=1)], h2h_policy="raw",
    )[0]
    assert prepared["family_probabilities"]["matchup_h2h"] == 0.25


def test_primary_agreement_only_activates_when_both_primary_families_align():
    aligned = prepare_contextual_meta_rows([_row()])[0]
    opposed = prepare_contextual_meta_rows([
        _row(recent=0.7, structural=0.4),
    ])[0]
    assert aligned["family_probabilities"]["primary_agreement"] > 0.5
    assert opposed["family_probabilities"]["primary_agreement"] == 0.5


def test_primary_agreement_threshold_ignores_weak_alignment():
    weak = prepare_contextual_meta_rows(
        [_row(recent=0.55, structural=0.56)],
        primary_agreement_threshold=0.3,
    )[0]
    strong = prepare_contextual_meta_rows(
        [_row(recent=0.7, structural=0.65)],
        primary_agreement_threshold=0.3,
    )[0]
    assert weak["family_probabilities"]["primary_agreement"] == 0.5
    assert strong["family_probabilities"]["primary_agreement"] > 0.5


def test_primary_agreement_coefficient_cannot_exceed_either_primary():
    columns = _columns()
    weights = np.zeros(len(columns))
    values = {
        "recent_form": 0.4,
        "structural_strength": 0.5,
        "surface_conditions": 0.3,
        "matchup_h2h": 0.2,
        "serve_return": 0.1,
        "primary_agreement": 2.0,
    }
    for family, value in values.items():
        weights[columns.index(f"{family}__logit")] = value
    projected = hierarchy_v9_projector(columns)(weights)
    agreement = projected[columns.index("primary_agreement__logit")]
    assert agreement == 0.4
