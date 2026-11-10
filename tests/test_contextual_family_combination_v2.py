import inspect

import numpy as np

from src.contextual_family_combination_v2 import (
    FAMILY_ORDER,
    PROFILES,
    _effective_profiles,
    _meta_matrix,
    combine_contextual_families_v2,
    hierarchy_projector,
)


def _columns():
    columns = []
    for family in FAMILY_ORDER:
        columns.extend([
            f"{family}__logit",
            f"{family}__unavailable",
            f"{family}__observed_none",
        ])
    return columns


def test_hierarchy_projection_caps_modifiers_without_inventing_primary_mass():
    columns = _columns()
    weights = np.zeros(len(columns))
    for family, value in {
        "recent_form": 0.8,
        "structural_strength": 0.6,
        "surface_conditions": 2.0,
        "matchup_h2h": 1.5,
        "serve_return": 1.2,
    }.items():
        weights[columns.index(f"{family}__logit")] = value
    projected = hierarchy_projector(columns)(weights)
    values = {
        family: projected[columns.index(f"{family}__logit")]
        for family in FAMILY_ORDER
    }
    assert values["surface_conditions"] <= 0.7
    assert values["matchup_h2h"] <= values["surface_conditions"]
    assert values["serve_return"] <= values["matchup_h2h"]
    assert sum(values[name] for name in FAMILY_ORDER[2:]) <= 1.4 + 1e-9


def test_secondary_weights_are_zero_when_primary_mass_is_zero():
    columns = _columns()
    weights = np.ones(len(columns))
    weights[columns.index("recent_form__logit")] = 0.0
    weights[columns.index("structural_strength__logit")] = 0.0
    projected = hierarchy_projector(columns)(weights)
    assert all(
        projected[columns.index(f"{family}__logit")] == 0.0
        for family in FAMILY_ORDER[2:]
    )


def test_missing_numeric_family_is_explicitly_unavailable():
    row = {
        "target_a_win": True,
        "family_probabilities": {family: 0.6 for family in FAMILY_ORDER},
        "family_states": {family: {"data_state": "OBSERVED"} for family in FAMILY_ORDER},
    }
    row["family_probabilities"]["surface_conditions"] = None
    x, _, columns, _ = _meta_matrix([row])
    assert x[0, columns.index("surface_conditions__unavailable")] == 1.0


def test_missingness_never_becomes_directional_evidence():
    columns = _columns()
    projected = hierarchy_projector(columns)(np.ones(len(columns)))
    assert all(
        projected[index] == 0.0
        for index, name in enumerate(columns)
        if not name.endswith("__logit")
    )


def test_profile_override_is_isolated_and_preserves_other_families():
    profiles = _effective_profiles(
        "atp", {"structural_strength": "contextual_v6"},
    )
    assert profiles["structural_strength"] == "contextual_v6"
    assert profiles["recent_form"] == PROFILES["recent_form"]
    assert profiles["surface_conditions"] == PROFILES["surface_conditions"]
    assert PROFILES["structural_strength"] == "legacy_v0"


def test_unknown_profile_family_is_rejected():
    try:
        _effective_profiles("atp", {"unknown_family": "anything"})
    except ValueError as error:
        assert "unknown family" in str(error)
    else:
        raise AssertionError("unknown family override should fail closed")


def test_default_model_version_remains_v2_in_public_signature():
    signature = inspect.signature(combine_contextual_families_v2)
    assert (
        signature.parameters["model_version"].default
        == "contextual-family-combination-v2-hierarchical"
    )
