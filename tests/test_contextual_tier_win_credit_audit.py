from scripts.audit_contextual_tier_win_credit_v1 import (
    JOINT_FEATURE,
    ROUND_FEATURE,
    augment_candidate_features,
    opponent_quality,
    round_progress,
)
from src.contextual_family_calibration import CALIBRATION_FEATURE_PROFILES


def _ledger(round_name, rank, *, won=True):
    return {
        "round": round_name,
        "opponent_rank": rank,
        "won": won,
        "category_points": 1000,
        "recency_weight": 1.0,
    }


def test_round_progress_is_monotonic_and_round_robin_is_explicit():
    assert round_progress("R128") < round_progress("QF") < round_progress("F")
    assert round_progress("Round of 16") == round_progress("R16")
    assert round_progress("RR") == 1.0 / 3.0
    assert round_progress("unknown") is None


def test_opponent_quality_is_continuous_and_rewards_stronger_opponent():
    assert opponent_quality(1) > opponent_quality(10) > opponent_quality(100)
    assert opponent_quality(None) is None


def test_joint_feature_replaces_separate_evidence_without_inventing_missing_rank():
    row = {
        "features": {},
        "candidate_equation_audit": {
            "recent_form_tier_reliable_v5": {
                "tier_win_credit": {
                    "a_ledger": [_ledger("QF", 10), _ledger("SF", 20, won=False)],
                    "b_ledger": [_ledger("R32", 100), _ledger("QF", 80, won=False)],
                },
            },
        },
    }
    coverage = augment_candidate_features([row])
    assert row["features"][ROUND_FEATURE] > 0.0
    assert row["features"][JOINT_FEATURE] > 0.0
    assert coverage["round_available"] == 1
    assert coverage["joint_available"] == 1


def test_missing_metadata_is_omitted_not_converted_to_zero_credit():
    row = {
        "features": {},
        "candidate_equation_audit": {
            "recent_form_tier_reliable_v5": {
                "tier_win_credit": {
                    "a_ledger": [_ledger("QF", None)],
                    "b_ledger": [],
                },
            },
        },
    }
    coverage = augment_candidate_features([row])
    assert row["features"][ROUND_FEATURE] is not None
    assert row["features"][JOINT_FEATURE] is None
    assert coverage["joint_omitted_wins"] == 1


def test_joint_profile_cannot_double_count_category_or_opponent_quality():
    features = CALIBRATION_FEATURE_PROFILES[
        "recent_tier_round_opponent_joint_audit_v1"
    ]["recent_form"]
    assert JOINT_FEATURE in features
    assert "contextual_recent_tier_win_credit_v7" not in features
    assert "contextual_recent_win_quality_v1" not in features
