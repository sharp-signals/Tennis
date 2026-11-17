import json
from pathlib import Path

import pytest

from src.contextual_family_combination_v14 import MODEL_VERSION
from src.contextual_family_hierarchy import govern_consensus_with_individual_cap


MODEL = Path("data/models/contextual-family-combination-v14.json")


def test_v14_uses_chronologically_selected_universe_policies():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    assert contract["model_version"] == MODEL_VERSION
    assert contract["universes"]["atp"]["realized_hierarchy"][
        "consensus_cap_basis"
    ] == "aligned_primary_total"
    assert contract["universes"]["wta"]["realized_hierarchy"][
        "consensus_cap_basis"
    ] == "strongest_primary"


def test_atp_consensus_allows_secondary_up_to_aligned_primary_total():
    governed, audit = govern_consensus_with_individual_cap({
        "recent_form": 0.4,
        "structural_strength": 0.2,
        "surface_conditions": 0.8,
        "matchup_h2h": 0.3,
        "serve_return": 0.1,
    }, consensus_cap_basis="aligned_primary_total")
    assert audit["consensus_cap_absolute_impact"] == pytest.approx(0.6)
    assert governed["surface_conditions"] == pytest.approx(0.6)
    assert governed["matchup_h2h"] == 0.3


def test_conflict_still_uses_strict_primary_block_limits():
    governed, audit = govern_consensus_with_individual_cap({
        "recent_form": 0.4,
        "structural_strength": -0.2,
        "surface_conditions": 0.8,
        "matchup_h2h": 0.6,
        "serve_return": 0.4,
    }, consensus_cap_basis="aligned_primary_total")
    secondary = sum(
        abs(governed[key])
        for key in ("surface_conditions", "matchup_h2h", "serve_return")
    )
    assert audit["policy"] == "STRICT_CONFLICT_BLOCK_CAP"
    assert secondary <= 0.6 + 1e-12


def test_v14_does_not_claim_unproven_holdout_gain():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    for universe in contract["universes"].values():
        paired = universe["holdout"]["paired_gain_vs_v13"]
        assert paired["status"] == "INCONCLUSIVE"
        assert paired["gain_95pct_ci"][0] <= 0.0 <= paired["gain_95pct_ci"][1]


def test_v14_preserves_missingness_no_vote_invariant():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    for universe in contract["universes"].values():
        assert universe["missingness_audit"][
            "all_missing_indicator_weights_zero"
        ] is True
