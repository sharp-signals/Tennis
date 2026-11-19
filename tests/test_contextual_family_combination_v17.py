import copy
import math
from unittest.mock import patch

from src.contextual_family_combination_v17 import (
    FAMILY_ORDER,
    MODEL_VERSION,
    govern_recent_form_signal,
    mirror_contextual_row,
    predict_contextual_combination_v17,
)
from src.contextual_family_hierarchy import govern_ordered_family_contributions


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
                    "h2h_multiplier": 1.5,
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


def _row():
    return {
        "features": {
            "signal_recent_form": 0.7,
            "signal_structural_strength": 0.5,
            "signal_surface_conditions": 0.4,
            "signal_matchup_h2h": 0.3,
            "signal_serve_return": 0.8,
        },
    }


def test_prediction_is_exactly_invariant_to_player_order():
    with patch(
        "src.contextual_family_combination_v17._attach_predictions",
        side_effect=_fake_attach,
    ), patch(
        "src.contextual_family_combination_v17.govern_recent_form_signal",
        side_effect=lambda row, *_args, **_kwargs: (
            float(row["features"]["signal_recent_form"]), {"status": "READY"},
        ),
    ):
        direct = predict_contextual_combination_v17(
            [_row()], universe="atp", contract=_contract(),
        )["probabilities"][0]
        mirrored = predict_contextual_combination_v17(
            [mirror_contextual_row(_row())], universe="atp", contract=_contract(),
        )["probabilities"][0]
    assert math.isclose(direct, 1.0 - mirrored, abs_tol=1e-12)


def test_neutral_evidence_is_exactly_fifty_fifty():
    neutral = {"features": {f"signal_{family}": 0.0 for family in FAMILY_ORDER}}
    with patch(
        "src.contextual_family_combination_v17._attach_predictions",
        side_effect=_fake_attach,
    ), patch(
        "src.contextual_family_combination_v17.govern_recent_form_signal",
        return_value=(0.0, {"status": "READY"}),
    ):
        probability = predict_contextual_combination_v17(
            [neutral], universe="atp", contract=_contract(),
        )["probabilities"][0]
    assert probability == 0.5


def test_realised_hierarchy_keeps_secondary_block_below_primary_block():
    governed, audit = govern_ordered_family_contributions({
        "recent_form": 0.4,
        "structural_strength": 0.2,
        "surface_conditions": 1.2,
        "matchup_h2h": 0.9,
        "serve_return": 1.4,
    })
    primary = abs(governed["recent_form"]) + abs(governed["structural_strength"])
    secondary = sum(abs(governed[key]) for key in (
        "surface_conditions", "matchup_h2h", "serve_return",
    ))
    assert secondary <= primary + 1e-12
    assert abs(governed["surface_conditions"]) <= 0.3 + 1e-12
    assert abs(governed["matchup_h2h"]) <= 0.3 + 1e-12
    assert abs(governed["serve_return"]) <= 0.15 + 1e-12
    assert audit["absence_votes"] is False


def test_absent_primary_evidence_prevents_secondary_only_prediction():
    governed, _audit = govern_ordered_family_contributions({
        "recent_form": 0.0,
        "structural_strength": 0.0,
        "surface_conditions": 0.9,
        "matchup_h2h": 0.8,
        "serve_return": 0.7,
    })
    assert all(governed[family] == 0.0 for family in FAMILY_ORDER)


def test_recent_modifiers_cannot_reverse_material_results_base():
    explanation = {
        "status": "READY",
        "features": [
            {
                "key": "contextual_recent_result_main_v7",
                "coefficient": 0.0,
                "standardized_value": 1.0,
                "logit_contribution": 0.0,
                "missing_logit_contribution": 0.0,
            },
            {
                "key": "contextual_recent_competitiveness_main_v7",
                "coefficient": 0.2,
                "standardized_value": 1.0,
                "logit_contribution": 0.2,
                "missing_logit_contribution": 0.0,
            },
            {
                "key": "contextual_recent_win_quality_v1",
                "coefficient": 1.0,
                "standardized_value": -1.0,
                "logit_contribution": -1.0,
                "missing_logit_contribution": 0.0,
            },
        ],
    }
    with patch(
        "src.contextual_family_combination_v17.explain_symmetric_family_equation",
        return_value=explanation,
    ):
        signal, audit = govern_recent_form_signal(
            {}, {}, result_weight_floor=0.1, opposing_modifier_cap=0.5,
        )
    assert math.isclose(signal, 0.15)
    assert audit["result_floor_applied"] is True
    assert audit["direction_reversed_by_modifiers"] is False


def test_medvedev_tiafoe_recent_profile_no_longer_votes_for_tiafoe():
    explanation = {
        "status": "READY",
        "features": [
            {
                "key": "contextual_recent_result_main_v7",
                "coefficient": 0.0,
                "standardized_value": 0.60100107,
                "logit_contribution": 0.0,
                "missing_logit_contribution": 0.0,
            },
            {
                "key": "contextual_recent_competitiveness_main_v7",
                "coefficient": 0.1169106,
                "standardized_value": 0.63063753,
                "logit_contribution": 0.07690885,
                "missing_logit_contribution": 0.0,
            },
            {
                "key": "contextual_recent_win_quality_v1",
                "coefficient": 0.24709833,
                "standardized_value": -0.5766312,
                "logit_contribution": -0.13367906,
                "missing_logit_contribution": 0.0,
            },
            {
                "key": "contextual_recent_tier_win_credit_v7",
                "coefficient": 0.32922148,
                "standardized_value": -0.85910949,
                "logit_contribution": -0.27522154,
                "missing_logit_contribution": 0.0,
            },
        ],
    }
    with patch(
        "src.contextual_family_combination_v17.explain_symmetric_family_equation",
        return_value=explanation,
    ):
        signal, audit = govern_recent_form_signal(
            {}, {}, result_weight_floor=0.05, opposing_modifier_cap=0.5,
        )
    assert signal > 0.0
    assert audit["modifier_logit_after_governance"] < 0.0
    assert audit["direction_reversed_by_modifiers"] is False
