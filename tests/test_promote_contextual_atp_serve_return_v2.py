from scripts.promote_contextual_atp_serve_return_v2 import (
    ATP_SERVE_RETURN_PROFILE,
    _promotion_supported,
    candidate_profiles,
)


def test_candidate_changes_only_atp_serve_return_profile():
    baseline = {
        "family_profiles": {
            "recent_form": "recent",
            "structural_strength": "structural",
            "surface_conditions": "surface",
            "matchup_h2h": "h2h",
            "serve_return": "old_serve",
        },
    }
    candidate = candidate_profiles(baseline)
    assert candidate["serve_return"] == ATP_SERVE_RETURN_PROFILE
    assert {
        key: value for key, value in candidate.items() if key != "serve_return"
    } == {
        key: value for key, value in baseline["family_profiles"].items()
        if key != "serve_return"
    }


def test_promotion_gate_requires_all_three_quality_checks():
    baseline = {"brier": 0.21, "ece_10": 0.02}
    candidate = {"brier": 0.209, "ece_10": 0.019}
    assert _promotion_supported(
        {"status": "SUPPORTED"}, baseline, candidate,
    ) is True
    assert _promotion_supported(
        {"status": "INCONCLUSIVE"}, baseline, candidate,
    ) is False
    assert _promotion_supported(
        {"status": "SUPPORTED"}, baseline,
        {"brier": 0.211, "ece_10": 0.019},
    ) is False
    assert _promotion_supported(
        {"status": "SUPPORTED"}, baseline,
        {"brier": 0.209, "ece_10": 0.021},
    ) is False
