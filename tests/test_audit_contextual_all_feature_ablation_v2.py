from scripts.audit_contextual_all_feature_ablation_v2 import (
    frozen_feature_inventory,
    zero_frozen_feature_everywhere,
)


def test_surface_feature_is_removed_from_every_exact_context_model():
    combination = {
        "runtime_family_models": {
            "surface_conditions": {
                "hard_outdoor": {"columns": ["career"], "weights": [0.3]},
                "hard_indoor": {"columns": ["career"], "weights": [0.2]},
            },
        },
    }
    candidate, original = zero_frozen_feature_everywhere(
        combination, family="surface_conditions", feature="career",
    )
    assert original == {"hard_outdoor": 0.3, "hard_indoor": 0.2}
    models = candidate["runtime_family_models"]["surface_conditions"]
    assert models["hard_outdoor"]["weights"] == [0.0]
    assert models["hard_indoor"]["weights"] == [0.0]


def test_inventory_separates_active_zero_and_missingness_columns():
    combination = {
        "runtime_family_models": {
            "recent_form": {
                "columns": ["result", "result__missing", "quality"],
                "weights": [0.0, 0.0, 0.4],
            },
        },
    }
    inventory = frozen_feature_inventory(combination)
    assert [item["feature"] for item in inventory["active"]] == ["quality"]
    assert [
        item["feature"] for item in inventory["inactive_zero_weight"]
    ] == ["result"]
