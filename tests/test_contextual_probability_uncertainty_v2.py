from src.contextual_probability_uncertainty_v2 import (
    _apply_calibrator,
    _fair_odd,
    _quality_group,
)


def test_identity_calibrator_preserves_probability():
    model = {"method": "IDENTITY", "intercept": 0.0, "slope": 1.0}
    assert _apply_calibrator(0.63, model) == 0.63


def test_fair_odd_interval_reverses_probability_bounds():
    result = _fair_odd(0.60, 0.54, 0.66)
    assert result == {
        "central": 1.6667,
        "lower_odd": 1.5152,
        "upper_odd": 1.8519,
    }


def test_observed_none_h2h_is_coverage_not_missingness():
    row = {
        "family_probabilities": {
            "recent_form": 0.6,
            "structural_strength": 0.6,
            "surface_conditions": 0.6,
            "matchup_h2h": None,
            "serve_return": 0.6,
        },
        "family_states": {
            "matchup_h2h": {"data_state": "OBSERVED_NONE"},
        },
        "family_numeric_states": {"surface_conditions": "OBSERVED"},
    }
    assert _quality_group(row) == "PRIMARY_READY_COMPLETE"


def test_missing_primary_blocks_ready_group():
    row = {
        "family_probabilities": {
            "recent_form": None,
            "structural_strength": 0.6,
            "surface_conditions": 0.6,
            "matchup_h2h": None,
            "serve_return": 0.6,
        },
        "family_states": {
            "matchup_h2h": {"data_state": "OBSERVED_NONE"},
        },
        "family_numeric_states": {"surface_conditions": "OBSERVED"},
    }
    assert _quality_group(row) == "PRIMARY_DEGRADED"
