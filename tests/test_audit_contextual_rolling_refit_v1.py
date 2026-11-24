from scripts.audit_contextual_rolling_refit_v1 import (
    _decision,
    _temporary_removals,
    rolling_splits,
)
from src.contextual_family_calibration import CALIBRATION_FEATURE_PROFILES


def test_rolling_splits_have_ordered_non_overlapping_tests():
    rows = [
        {"event_date": f"2026-01-{index + 1:02d}", "match_key": str(index)}
        for index in range(20)
    ]
    folds = rolling_splits(rows)
    assert len(folds) == 3
    assert folds[0]["test"][-1]["event_date"] < folds[1]["test"][0]["event_date"]
    assert folds[1]["test"][-1]["event_date"] < folds[2]["test"][0]["event_date"]


def test_temporary_removals_restore_original_profile():
    profile = "serve_return_points_recent_deviation_v1"
    original = CALIBRATION_FEATURE_PROFILES[profile]["serve_return"]
    removed = "return_points_won_recent_deviation_v1"
    with _temporary_removals({profile: (removed,)}):
        assert removed not in CALIBRATION_FEATURE_PROFILES[profile]["serve_return"]
    assert CALIBRATION_FEATURE_PROFILES[profile]["serve_return"] == original


def test_promotion_requires_probability_and_calibration_improvement():
    paired = {"status": "SUPPORTED"}
    base = {"brier": 0.22, "ece_10": 0.02}
    improved = {"brier": 0.21, "ece_10": 0.019}
    worse_calibration = {"brier": 0.21, "ece_10": 0.021}
    assert _decision(paired, [0.01, 0.02, -0.01], base, improved) == (
        "CANDIDATE_SUPPORTED"
    )
    assert _decision(
        paired, [0.01, 0.02, -0.01], base, worse_calibration,
    ) == "INCONCLUSIVE_KEEP_CURRENT_RELEASE"
