from scripts.audit_contextual_existing_feature_ablation import (
    zero_frozen_feature,
)
from src.contextual_family_calibration import CALIBRATION_FEATURE_PROFILES


def test_zero_frozen_feature_changes_only_requested_weight():
    combination = {
        "runtime_family_models": {
            "recent_form": {
                "columns": ["quality", "quality__missing", "tier"],
                "weights": [0.3, 0.0, 0.2],
            },
        },
    }
    candidate, original = zero_frozen_feature(
        combination, family="recent_form", feature="quality",
    )
    assert original == 0.3
    assert candidate["runtime_family_models"]["recent_form"]["weights"] == [
        0.0, 0.0, 0.2,
    ]
    assert combination["runtime_family_models"]["recent_form"]["weights"] == [
        0.3, 0.0, 0.2,
    ]


def test_missing_feature_is_reported_without_mutating_contract():
    combination = {
        "runtime_family_models": {
            "structural_strength": {
                "columns": ["rank"],
                "weights": [0.4],
            },
        },
    }
    candidate, original = zero_frozen_feature(
        combination, family="structural_strength", feature="trajectory",
    )
    assert original is None
    assert candidate == combination


def test_atp_v8_profile_removes_only_raw_trajectory_from_structural_family():
    baseline = CALIBRATION_FEATURE_PROFILES["contextual_v7"][
        "structural_strength"
    ]
    candidate = CALIBRATION_FEATURE_PROFILES[
        "contextual_v8_atp_no_raw_trajectory"
    ]["structural_strength"]
    assert "contextual_structural_trajectory_margin_v3" in baseline
    assert "contextual_structural_trajectory_margin_v3" not in candidate
    assert set(candidate) == set(baseline) - {
        "contextual_structural_trajectory_margin_v3",
    }
