import json
from pathlib import Path

from src.contextual_family_combination_v13 import MODEL_VERSION
from src.contextual_family_hierarchy import govern_consensus_with_individual_cap


MODEL = Path("data/models/contextual-family-combination-v13.json")


def test_v13_enforces_consensus_aware_primary_hierarchy():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    assert contract["model_version"] == MODEL_VERSION
    for universe in contract["universes"].values():
        hierarchy = universe["realized_hierarchy"]
        assert hierarchy["policy"] == "CONSENSUS_WITH_INDIVIDUAL_SECONDARY_CAP"
        assert hierarchy[
            "conflict_single_secondary_not_above_primary_average"
        ] is True
        assert hierarchy["conflict_secondary_total_not_above_primary_total"] is True
        assert hierarchy["consensus_secondary_not_above_strongest_primary"] is True
        assert hierarchy["unanimous_reinforcement_preserved"] is True


def test_consensus_caps_each_secondary_at_the_strongest_primary():
    governed, audit = govern_consensus_with_individual_cap({
        "recent_form": 0.4,
        "structural_strength": 0.2,
        "surface_conditions": 0.8,
        "matchup_h2h": 0.3,
        "serve_return": 0.1,
    })
    assert audit["policy"] == "CONSENSUS_WITH_INDIVIDUAL_SECONDARY_CAP"
    assert governed["surface_conditions"] == 0.4
    assert governed["matchup_h2h"] == 0.3


def test_conflict_uses_strict_primary_block_limits():
    governed, audit = govern_consensus_with_individual_cap({
        "recent_form": 0.4,
        "structural_strength": -0.2,
        "surface_conditions": 0.8,
        "matchup_h2h": 0.6,
        "serve_return": 0.4,
    })
    secondary = sum(
        abs(governed[key])
        for key in ("surface_conditions", "matchup_h2h", "serve_return")
    )
    assert audit["policy"] == "STRICT_CONFLICT_BLOCK_CAP"
    assert secondary <= 0.6 + 1e-12
    assert max(
        abs(governed[key])
        for key in ("surface_conditions", "matchup_h2h", "serve_return")
    ) <= 0.3 + 1e-12


def test_v13_replay_does_not_claim_an_unproven_gain():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    for universe in contract["universes"].values():
        paired = universe["holdout"]["paired_gain_vs_v12"]
        assert paired["status"] == "INCONCLUSIVE"
        assert paired["gain_95pct_ci"][0] <= 0.0 <= paired["gain_95pct_ci"][1]


def test_v13_preserves_missingness_no_vote_invariant():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    for universe in contract["universes"].values():
        assert universe["missingness_audit"][
            "all_missing_indicator_weights_zero"
        ] is True
