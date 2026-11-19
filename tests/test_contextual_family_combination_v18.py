import copy
import math
from unittest.mock import patch

from src.contextual_family_combination_v18 import (
    FAMILY_ORDER,
    MODEL_VERSION,
    V17_CONSENSUS_POLICY,
    govern_v18_family_contributions,
    predict_contextual_combination_v18,
)
from src.contextual_family_combination_v17 import mirror_contextual_row


def _contract():
    return {
        "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {
            "atp": {
                "runtime_family_models": {"recent_form": {}},
                "family_coefficients": {family: 1.0 for family in FAMILY_ORDER},
                "realized_hierarchy": {
                    "unanimous_policy": (
                        "FITTED_WEIGHTED_REINFORCEMENT_IF_BOTH_PRIMARIES_ALIGN"
                    ),
                    "h2h_multiplier": 1.0,
                    "recent_form_governance": {
                        "result_weight_floor": 0.05,
                        "opposing_modifier_cap": 0.5,
                    },
                    "post_hierarchy_calibration": {
                        "intercept": 0.0,
                        "slope": 1.0,
                    },
                },
            },
        },
    }


def _fake_attach(rows, _models, *, universe):
    assert universe == "atp"
    result = []
    for source in rows:
        row = copy.deepcopy(source)
        row["family_probabilities"] = {
            family: 1.0 / (1.0 + math.exp(-float(
                row["features"].get(f"signal_{family}", 0.0)
            )))
            for family in FAMILY_ORDER
        }
        result.append(row)
    return result


def test_unanimous_evidence_keeps_fitted_weighted_contributions():
    raw = {
        "recent_form": 0.03,
        "structural_strength": 0.06,
        "surface_conditions": 0.24,
        "matchup_h2h": 0.17,
        "serve_return": 0.22,
    }
    governed, audit = govern_v18_family_contributions(raw)
    assert governed == raw
    assert audit["policy"] == "UNANIMOUS_FITTED_WEIGHTED_REINFORCEMENT"
    assert audit["secondary_clipping"] is False


def test_medvedev_tiafoe_control_is_not_compressed_to_v17_ceiling():
    """Production evidence from run 44625234479 must retain its fitted strength."""
    raw = {
        "recent_form": 0.02311548 / 1.06789642,
        "structural_strength": 0.06350121 / 1.06789642,
        "surface_conditions": 0.240779 / 1.06789642,
        "matchup_h2h": 0.170123 / 1.06789642,
        "serve_return": 0.222535 / 1.06789642,
    }
    governed, _audit = govern_v18_family_contributions(raw)
    probability = 1.0 / (
        1.0 + math.exp(-1.06789642 * sum(governed.values()))
    )
    assert 0.66 < probability < 0.69
    assert 1.45 < 1.0 / probability < 1.52


def test_rejected_universe_keeps_v17_individual_consensus_cap():
    raw = {
        "recent_form": 0.03,
        "structural_strength": 0.06,
        "surface_conditions": 0.24,
        "matchup_h2h": 0.17,
        "serve_return": 0.22,
    }
    governed, audit = govern_v18_family_contributions(
        raw, unanimous_policy=V17_CONSENSUS_POLICY,
    )
    assert governed["surface_conditions"] == 0.06
    assert governed["matchup_h2h"] == 0.06
    assert governed["serve_return"] == 0.06
    assert audit["candidate_policy_rejected"] is True


def test_rejected_universe_matches_v17_when_one_primary_is_neutral():
    governed, audit = govern_v18_family_contributions({
        "recent_form": 0.0,
        "structural_strength": 0.06,
        "surface_conditions": 0.24,
        "matchup_h2h": 0.17,
        "serve_return": 0.22,
    }, unanimous_policy=V17_CONSENSUS_POLICY)
    assert governed["surface_conditions"] == 0.06
    assert governed["matchup_h2h"] == 0.06
    assert governed["serve_return"] == 0.06
    assert audit["candidate_policy_rejected"] is True


def test_secondary_only_evidence_cannot_create_prediction():
    governed, audit = govern_v18_family_contributions({
        "recent_form": 0.0,
        "structural_strength": 0.0,
        "surface_conditions": 0.8,
        "matchup_h2h": 0.7,
        "serve_return": 0.6,
    })
    assert all(governed[family] == 0.0 for family in FAMILY_ORDER)
    assert audit["policy"] == "STRICT_CONFLICT_BLOCK_CAP"


def test_primary_conflict_keeps_strict_hierarchy():
    governed, audit = govern_v18_family_contributions({
        "recent_form": 0.4,
        "structural_strength": -0.2,
        "surface_conditions": 1.2,
        "matchup_h2h": 0.9,
        "serve_return": 1.4,
    })
    primary = sum(abs(governed[key]) for key in (
        "recent_form", "structural_strength",
    ))
    secondary = sum(abs(governed[key]) for key in (
        "surface_conditions", "matchup_h2h", "serve_return",
    ))
    assert secondary <= primary + 1e-12
    assert audit["policy"] == "STRICT_CONFLICT_BLOCK_CAP"


def test_prediction_is_exactly_invariant_to_player_order():
    row = {"features": {
        "signal_recent_form": 0.7,
        "signal_structural_strength": 0.5,
        "signal_surface_conditions": 0.4,
        "signal_matchup_h2h": 0.3,
        "signal_serve_return": 0.8,
    }}
    with patch(
        "src.contextual_family_combination_v18._attach_predictions",
        side_effect=_fake_attach,
    ), patch(
        "src.contextual_family_combination_v18.govern_recent_form_signal",
        side_effect=lambda source, *_args, **_kwargs: (
            float(source["features"]["signal_recent_form"]), {"status": "READY"},
        ),
    ):
        direct = predict_contextual_combination_v18(
            [row], universe="atp", contract=_contract(),
        )["probabilities"][0]
        reverse = predict_contextual_combination_v18(
            [mirror_contextual_row(row)], universe="atp", contract=_contract(),
        )["probabilities"][0]
    assert math.isclose(direct, 1.0 - reverse, abs_tol=1e-12)


def test_neutral_evidence_is_exactly_fifty_fifty():
    row = {"features": {f"signal_{family}": 0.0 for family in FAMILY_ORDER}}
    with patch(
        "src.contextual_family_combination_v18._attach_predictions",
        side_effect=_fake_attach,
    ), patch(
        "src.contextual_family_combination_v18.govern_recent_form_signal",
        return_value=(0.0, {"status": "READY"}),
    ):
        probability = predict_contextual_combination_v18(
            [row], universe="atp", contract=_contract(),
        )["probabilities"][0]
    assert probability == 0.5
