from src.contextual_probability_uncertainty_v4 import (
    calibrate_probability_uncertainty_v4,
)


def test_v4_missing_frozen_chronology_fails_closed():
    try:
        calibrate_probability_uncertainty_v4(
            [], universe="atp", combination_contract={"universes": {"atp": {}}},
        )
    except ValueError as error:
        assert "chronology" in str(error)
    else:
        raise AssertionError("missing chronology should fail closed")


def test_v4_holdout_size_mismatch_fails_before_prediction():
    contract = {"universes": {"atp": {"chronology": {
        "holdout_from": "2026-01-01", "evaluation_through": "2026-12-31",
        "holdout_targets": 2,
    }}}}
    try:
        calibrate_probability_uncertainty_v4(
            [{"event_date": "2026-06-01"}],
            universe="atp", combination_contract=contract,
        )
    except ValueError as error:
        assert "cannot be reproduced" in str(error)
    else:
        raise AssertionError("holdout mismatch should fail closed")
