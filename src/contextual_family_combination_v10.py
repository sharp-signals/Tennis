"""Runtime prediction with consensus-aware realised family hierarchy."""

from __future__ import annotations

import math
from typing import Any

from .contextual_family_combination_v2 import _attach_predictions
from .contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    SECONDARY_FAMILIES,
    govern_consensus_aware_family_contributions,
)


MODEL_VERSION = "contextual-family-combination-v10-consensus-aware-hierarchy"
FAMILY_ORDER = (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def validate_combination_v10_contract(contract: dict[str, Any]) -> None:
    if contract.get("model_version") != MODEL_VERSION:
        raise ValueError("unexpected contextual combination v10 model version")
    if contract.get("mode") != "SHADOW_ONLY":
        raise ValueError("combination v10 contract must remain SHADOW_ONLY")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "promotion_authorized",
    )):
        raise ValueError("combination v10 isolation invariant failed")


def predict_contextual_combination_v10(
    rows: list[dict[str, Any]], *, universe: str, contract: dict[str, Any],
) -> dict[str, Any]:
    validate_combination_v10_contract(contract)
    universe = str(universe).casefold()
    model = contract.get("universes", {}).get(universe)
    if not isinstance(model, dict):
        raise ValueError(f"combination v10 missing universe: {universe}")
    attached = _attach_predictions(
        rows, model["runtime_family_models"], universe=universe,
    )
    calibration = model["realized_hierarchy"]["post_hierarchy_calibration"]
    probabilities = []
    for row in attached:
        raw = {
            family: (
                float(model["family_coefficients"].get(family, 0.0))
                * _logit(row["family_probabilities"][family])
                if row["family_probabilities"].get(family) is not None else 0.0
            )
            for family in FAMILY_ORDER
        }
        governed, audit = govern_consensus_aware_family_contributions(raw)
        governed_logit = float(model["intercept"]) + sum(governed.values())
        final_logit = (
            float(calibration["intercept"])
            + float(calibration["slope"]) * governed_logit
        )
        row["realized_family_contributions"] = governed
        row["calibrated_realized_family_contributions"] = {
            family: float(calibration["slope"]) * contribution
            for family, contribution in governed.items()
        }
        row["realized_hierarchy_audit"] = audit
        row["pre_hierarchy_family_contributions"] = raw
        probabilities.append(_sigmoid(final_logit))
    return {
        "model_version": MODEL_VERSION,
        "universe": universe,
        "rows": attached,
        "probabilities": probabilities,
        "refit_performed": False,
        "market_used": False,
        "production_effect": False,
    }
