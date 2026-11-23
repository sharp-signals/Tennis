from scripts.promote_contextual_atp_structural_v8 import (
    ATP_STRUCTURAL_PROFILE,
    candidate_profiles,
)
from src.contextual_family_combination_v18 import MODEL_VERSION


def test_candidate_changes_only_structural_profile():
    baseline = {
        "family_profiles": {
            "recent_form": "recent",
            "structural_strength": "contextual_v7",
            "surface_conditions": "surface",
            "matchup_h2h": "h2h",
            "serve_return": "serve",
        },
    }
    candidate = candidate_profiles(baseline)
    assert candidate["structural_strength"] == ATP_STRUCTURAL_PROFILE
    assert {
        key: value for key, value in candidate.items()
        if key != "structural_strength"
    } == {
        key: value for key, value in baseline["family_profiles"].items()
        if key != "structural_strength"
    }
    assert baseline["family_profiles"]["structural_strength"] == "contextual_v7"


def test_combination_version_used_for_frozen_wta_is_v18():
    assert MODEL_VERSION == "contextual-family-combination-v18-unanimous-consensus"
