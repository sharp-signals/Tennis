import json
from pathlib import Path

from src.contextual_family_combination_v12 import MODEL_VERSION


MODEL = Path("data/models/contextual-family-combination-v12.json")


def _family_models(universe):
    models = universe["runtime_family_models"]
    for family, value in models.items():
        if family == "surface_conditions":
            for model in value.values():
                yield family, model
        else:
            yield family, value


def test_v12_reserves_absence_for_coverage_and_uncertainty_only():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    assert contract["model_version"] == MODEL_VERSION
    for universe in contract["universes"].values():
        audit = universe["missingness_audit"]
        assert audit["all_missing_indicator_weights_zero"] is True
        assert audit["nonzero_missing_indicator_weights"] == 0
        assert audit["absence_changes_central_probability"] is False
        assert audit["absence_reserved_for_coverage_and_uncertainty"] is True
        for _, model in _family_models(universe):
            assert model["missingness_vote"] is False
            assert all(
                abs(float(weight)) <= 1e-12
                for column, weight in zip(
                    model["columns"], model["weights"], strict=True,
                )
                if column.endswith("__missing")
            )


def test_v12_chronological_replay_does_not_claim_an_unproven_gain():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    for universe in contract["universes"].values():
        paired = universe["holdout"]["paired_gain_vs_v11"]
        assert paired["status"] == "INCONCLUSIVE"
        assert paired["gain_95pct_ci"][0] <= 0.0 <= paired["gain_95pct_ci"][1]
