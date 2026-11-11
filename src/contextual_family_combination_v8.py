"""Runtime prediction for the competition-context aware combination."""

from __future__ import annotations

from typing import Any

import numpy as np

from .contextual_family_calibration import _predict
from .contextual_family_combination_v2 import _attach_predictions, _meta_matrix


MODEL_VERSION = "contextual-family-combination-v8-tier-context"


def validate_combination_v8_contract(contract: dict[str, Any]) -> None:
    if contract.get("model_version") != MODEL_VERSION:
        raise ValueError("unexpected contextual combination v8 model version")
    if contract.get("mode") != "SHADOW_ONLY":
        raise ValueError("combination v8 contract must remain SHADOW_ONLY")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "promotion_authorized",
    )):
        raise ValueError("combination v8 isolation invariant failed")


def predict_contextual_combination_v8(
    rows: list[dict[str, Any]], *, universe: str, contract: dict[str, Any],
) -> dict[str, Any]:
    validate_combination_v8_contract(contract)
    universe = str(universe).casefold()
    model = contract.get("universes", {}).get(universe)
    if not isinstance(model, dict):
        raise ValueError(f"combination v8 missing universe: {universe}")
    attached = _attach_predictions(
        rows, model["runtime_family_models"], universe=universe,
    )
    x, _, columns, _ = _meta_matrix(attached)
    coefficients = model["family_coefficients"]
    weights = np.asarray([
        float(coefficients[name.removesuffix("__logit")])
        if name.endswith("__logit") else 0.0
        for name in columns
    ])
    probabilities = _predict(x, float(model["intercept"]), weights)
    return {
        "model_version": MODEL_VERSION,
        "universe": universe,
        "rows": attached,
        "probabilities": [float(value) for value in probabilities],
        "refit_performed": False,
        "market_used": False,
        "production_effect": False,
    }
