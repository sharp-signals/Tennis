from datetime import date, timedelta
import math

import numpy as np

from src.contextual_family_calibration import _fit_logistic_elastic_net
from src.contextual_family_combination import (
    _meta_matrix,
    _primary_readiness,
    combine_contextual_families,
)
from src.contextual_family_replay import FEATURE_FAMILIES


def _rows(count=720):
    start = date(2020, 1, 1)
    rows = []
    for i in range(count):
        latent = {
            "recent_form": math.sin(i * 0.17),
            "structural_strength": math.sin(i * 0.31 + 1.0),
            "surface_conditions": math.sin(i * 0.11 + 2.0),
            "matchup_h2h": math.sin(i * 0.23 + 0.4),
            "serve_return": math.sin(i * 0.07 + 1.7),
        }
        target = sum(latent.values()) > 0
        features = {}
        for feature, family in FEATURE_FAMILIES.items():
            value = latent[family] + 0.03 * math.sin(i * 0.43 + len(feature))
            features[feature] = value
        h2h_none = i % 4 == 0
        if h2h_none:
            features["h2h_win_share_margin"] = None
            features["same_surface_h2h_win_share_margin"] = None
        rows.append({
            "event_date": (start + timedelta(days=i)).isoformat(),
            "target_a_win": target,
            "features": features,
            "family_states": {
                "recent_form": {"data_state": "OBSERVED"},
                "structural_strength": {"data_state": "OBSERVED"},
                "surface_conditions": {"data_state": "OBSERVED"},
                "matchup_h2h": {"data_state": "OBSERVED_NONE" if h2h_none else "OBSERVED"},
                "serve_return": {"data_state": "OBSERVED"},
            },
        })
    return rows


def test_nonnegative_mask_prevents_family_direction_reversal():
    x = np.array([[-2.0], [-1.0], [1.0], [2.0]] * 30)
    y = np.array([1.0, 1.0, 0.0, 0.0] * 30)
    _, weights, _ = _fit_logistic_elastic_net(
        x, y, l1=0.0, nonnegative_mask=np.array([True]),
    )
    assert weights[0] == 0.0


def test_meta_matrix_distinguishes_observed_none_from_unavailable():
    rows = _rows(2)
    for row in rows:
        row["family_probabilities"] = {family: 0.6 for family in set(FEATURE_FAMILIES.values())}
    rows[0]["family_probabilities"]["matchup_h2h"] = None
    rows[1]["family_probabilities"]["matchup_h2h"] = None
    rows[1]["family_states"]["matchup_h2h"]["data_state"] = "INSUFFICIENT_SAMPLE"
    x, _, columns, _ = _meta_matrix(rows)
    none_col = columns.index("matchup_h2h__observed_none")
    unavailable_col = columns.index("matchup_h2h__unavailable")
    assert x[0, none_col] == 1.0 and x[0, unavailable_col] == 0.0
    assert x[1, none_col] == 0.0 and x[1, unavailable_col] == 1.0


def test_combination_is_supported_and_beats_each_complementary_family():
    result = combine_contextual_families(_rows(), universe="atp")
    assert result["status"] == "HOLDOUT_SUPPORTED"
    assert result["holdout"]["gain_vs_best_family"] > 0
    assert result["overall_probability_fitted"] is True
    assert result["fair_odd_fitted"] is False


def test_family_directional_coefficients_are_nonnegative():
    result = combine_contextual_families(_rows(), universe="wta")
    assert all(value >= 0 for value in result["family_coefficients"].values())
    assert result["directional_family_coefficients_nonnegative"] is True


def test_primary_readiness_does_not_allow_secondary_family_to_replace_form():
    rows = _rows(3)
    rows[0]["family_states"]["recent_form"]["data_state"] = "MISSING_DATA"
    readiness = _primary_readiness(rows)
    assert readiness["ready"] == 2
    assert readiness["total"] == 3


def test_combination_is_market_free_and_read_only():
    result = combine_contextual_families(_rows(), universe="challenger")
    assert result["market_used"] is False
    assert result["production_effect"] is False
    assert result["uncertainty_policy"]["missing_family_is_not_neutral"] is True
    assert result["meta_l1_selected_inside_validation"] >= 0
