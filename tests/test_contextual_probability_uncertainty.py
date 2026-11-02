from datetime import date, timedelta
import math

from src.contextual_family_replay import FEATURE_FAMILIES
from src.contextual_probability_uncertainty import (
    _chronological_halves,
    _fair_odd_interval,
    _primary_ready,
    _wilson,
    calibrate_probability_uncertainty,
)


def _rows(count=600):
    start = date(2020, 1, 1)
    rows = []
    for i in range(count):
        latent = {family: math.sin(i * rate + shift) for family, rate, shift in (
            ("recent_form", .17, 0), ("structural_strength", .31, 1),
            ("surface_conditions", .11, 2), ("matchup_h2h", .23, .4),
            ("serve_return", .07, 1.7),
        )}
        features = {
            feature: latent[family] + .02 * math.sin(i * .41 + len(feature))
            for feature, family in FEATURE_FAMILIES.items()
        }
        h2h_none = i % 4 == 0
        if h2h_none:
            features["h2h_win_share_margin"] = None
            features["same_surface_h2h_win_share_margin"] = None
        rows.append({
            "event_date": (start + timedelta(days=i)).isoformat(),
            "target_a_win": sum(latent.values()) > 0,
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


def test_wilson_interval_contains_observed_rate():
    lower, upper = _wilson(60, 100)
    assert lower < 0.6 < upper
    assert 0.0 <= lower < upper <= 1.0


def test_independent_wilson_intervals_can_overlap_when_points_differ_slightly():
    calibration = _wilson(79, 100)
    test = _wilson(80, 100)
    assert not (test[1] < calibration[0] or test[0] > calibration[1])


def test_fair_odd_interval_has_correct_inverse_order():
    odd = _fair_odd_interval(0.6, 0.5, 0.7)
    assert odd["lower_odd"] < odd["central"] < odd["upper_odd"]


def test_chronological_halves_do_not_split_dates():
    rows = _rows(20)
    probabilities = [0.5] * len(rows)
    first, second = _chronological_halves(rows, probabilities)
    assert {item["row"]["event_date"] for item in first}.isdisjoint(
        {item["row"]["event_date"] for item in second}
    )


def test_primary_readiness_requires_form_and_structure():
    row = _rows(1)[0]
    assert _primary_ready(row) is True
    row["family_states"]["recent_form"]["data_state"] = "INSUFFICIENT_SAMPLE"
    assert _primary_ready(row) is False


def test_uncertainty_calibration_is_shadow_only_and_market_free():
    result = calibrate_probability_uncertainty(_rows(), universe="atp")
    assert result["status"] == "UNCERTAINTY_CALIBRATED_FOR_SHADOW"
    assert result["fair_odd_status"] == "SHADOW_ONLY_NOT_OPERATIONAL"
    assert result["market_used"] is False
    assert result["production_effect"] is False
    assert result["test_summary"]["records"] > 0
    assert result["supported_probability_range"]["lower"] < result["supported_probability_range"]["upper"]
    for item in result["example_intervals"]:
        low, high = item["probability_interval_90"]
        assert low <= item["probability"] <= high
