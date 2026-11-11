from src.contextual_family_combination_v4 import (
    MODEL_VERSION, predict_contextual_combination_v4,
    validate_combination_v4_contract,
)


def _contract():
    unavailable = {"status": "INSUFFICIENT_COVERAGE"}
    return {
        "model_version": MODEL_VERSION, "mode": "SHADOW_ONLY",
        "market_used": False, "production_effect": False,
        "promotion_authorized": False,
        "universes": {"atp": {
            "intercept": 0.0,
            "family_coefficients": {
                "recent_form": 1.0, "structural_strength": 1.0,
                "surface_conditions": 0.5, "matchup_h2h": 0.25,
                "serve_return": 0.25,
            },
            "runtime_family_models": {
                "recent_form": unavailable, "structural_strength": unavailable,
                "matchup_h2h": unavailable, "serve_return": unavailable,
                "surface_conditions": {},
            },
        }},
    }


def test_v4_prediction_is_frozen_market_free_and_does_not_refit():
    row = {"target_a_win": True, "family_states": {},
           "diagnostics": {}, "features": {}}
    result = predict_contextual_combination_v4(
        [row], universe="atp", contract=_contract(),
    )
    assert result["probabilities"] == [0.5]
    assert result["refit_performed"] is False
    assert result["market_used"] is False


def test_v4_contract_with_market_fails_closed():
    contract = _contract()
    contract["market_used"] = True
    try:
        validate_combination_v4_contract(contract)
    except ValueError as error:
        assert "isolation" in str(error)
    else:
        raise AssertionError("market-aware contract should fail closed")
