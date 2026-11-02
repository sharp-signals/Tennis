import math

from src.contextual_family_calibration import (
    _fit_logistic_elastic_net,
    calibrate_contextual_families,
    calibrate_family,
)
from src.contextual_family_replay import FEATURE_FAMILIES

import numpy as np


def _row(index, *, signal=None, won=None, missing=False):
    features = {key: None for key in FEATURE_FAMILIES}
    if not missing:
        features["current_rank_log_ratio"] = float(signal)
        features["rank_change_from_last_observation"] = float((index % 5) - 2)
    return {
        "event_date": f"2026-01-{(index % 28) + 1:02d}",
        "target_a_win": bool(signal > 0) if won is None else bool(won),
        "features": features,
    }


def _split_rows():
    return {
        "train": [_row(i, signal=(-2.0 if i % 2 else 2.0)) for i in range(120)],
        "validation": [_row(i, signal=(-1.5 if i % 2 else 1.5)) for i in range(60)],
        "holdout": [_row(i, signal=(-1.0 if i % 2 else 1.0)) for i in range(60)],
    }


def test_elastic_net_learns_positive_direction():
    x = np.array([[-2.0], [-1.0], [1.0], [2.0]] * 20)
    y = np.array([0.0, 0.0, 1.0, 1.0] * 20)
    _, weights, _ = _fit_logistic_elastic_net(x, y, l1=0.001)
    assert weights[0] > 0


def test_family_equation_is_selected_on_validation_and_supported_on_holdout():
    result = calibrate_family(_split_rows(), family="structural_strength")
    assert result["status"] == "HOLDOUT_SUPPORTED"
    assert result["coefficients"]["current_rank_log_ratio"] > 0
    assert "rank_change_from_last_observation" not in result["coefficients"]
    assert result["holdout"]["model"]["log_loss"] < result["holdout"]["intercept_only_baseline"]["log_loss"]


def test_missing_values_have_explicit_indicators():
    split = _split_rows()
    split["train"][0] = _row(0, signal=1.0, missing=True)
    result = calibrate_family(split, family="structural_strength")
    assert result["preprocessor"]["missing_policy"] == "median_imputation_plus_explicit_missing_indicator"
    assert "current_rank_log_ratio__missing" in result["coefficients"]


def test_holdout_extreme_does_not_enter_preprocessor():
    split = _split_rows()
    split["holdout"][0]["features"]["current_rank_log_ratio"] = 1_000_000.0
    result = calibrate_family(split, family="structural_strength")
    assert result["preprocessor"]["features"]["current_rank_log_ratio"]["upper"] < 100.0


def test_insufficient_family_is_not_fitted():
    empty = {"train": [], "validation": [], "holdout": []}
    result = calibrate_family(empty, family="matchup_h2h")
    assert result["status"] == "INSUFFICIENT_COVERAGE"


def test_all_families_remain_separate_and_overall_probability_is_absent():
    rows = _split_rows()["train"] + _split_rows()["validation"] + _split_rows()["holdout"]
    # Give each group distinct dates so the chronological splitter has material.
    for i, row in enumerate(rows):
        row["event_date"] = f"{2020 + i // 100:04d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
    result = calibrate_contextual_families(rows, universe="atp")
    assert set(result["families"]) == set(FEATURE_FAMILIES.values())
    assert result["families_combined"] is False
    assert result["overall_probability_fitted"] is False
    assert result["fair_odd_fitted"] is False


def test_calibration_never_uses_market_or_changes_production():
    rows = _split_rows()["train"] + _split_rows()["validation"] + _split_rows()["holdout"]
    for i, row in enumerate(rows):
        row["event_date"] = f"{2020 + i // 100:04d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
    result = calibrate_contextual_families(rows, universe="wta")
    assert result["market_used"] is False
    assert result["production_effect"] is False
    assert result["universe"] == "wta"


def test_coefficients_and_metrics_are_finite():
    result = calibrate_family(_split_rows(), family="structural_strength")
    assert math.isfinite(result["intercept"])
    assert all(math.isfinite(value) for value in result["coefficients"].values())
    assert math.isfinite(result["holdout"]["model"]["brier"])
