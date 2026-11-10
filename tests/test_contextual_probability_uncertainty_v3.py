from src.contextual_probability_uncertainty_v3 import (
    calibrate_probability_uncertainty_v3,
)


def test_missing_frozen_chronology_fails_closed():
    contract = {"universes": {"atp": {}}}
    try:
        calibrate_probability_uncertainty_v3(
            [], universe="atp", combination_contract=contract,
        )
    except ValueError as error:
        assert "chronology" in str(error)
    else:
        raise AssertionError("missing chronology should fail closed")


def test_frozen_holdout_size_mismatch_fails_before_prediction():
    contract = {
        "universes": {
            "atp": {
                "chronology": {
                    "holdout_from": "2026-01-01",
                    "evaluation_through": "2026-12-31",
                    "holdout_targets": 2,
                },
            },
        },
    }
    rows = [{"event_date": "2026-06-01"}]
    try:
        calibrate_probability_uncertainty_v3(
            rows, universe="atp", combination_contract=contract,
        )
    except ValueError as error:
        assert "cannot be reproduced" in str(error)
    else:
        raise AssertionError("holdout mismatch should fail closed")
