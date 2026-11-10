"""Calibrate probability and uncertainty from the frozen combination v3."""

from __future__ import annotations

from typing import Any

from .contextual_family_combination_v3 import (
    MODEL_VERSION as COMBINATION_MODEL_VERSION,
    predict_contextual_combination_v3,
)
from .contextual_probability_uncertainty_v2 import (
    calibrate_probability_uncertainty_v2,
)


MODEL_VERSION = "contextual-probability-uncertainty-v3"


def calibrate_probability_uncertainty_v3(
    rows: list[dict[str, Any]], *, universe: str,
    combination_contract: dict[str, Any],
) -> dict[str, Any]:
    """Use the frozen v3 holdout; never refit the five family equations."""
    universe_model = combination_contract.get("universes", {}).get(
        str(universe).casefold(), {}
    )
    chronology = universe_model.get("chronology")
    if not isinstance(chronology, dict):
        raise ValueError("combination v3 chronology is required")
    holdout_from = str(chronology["holdout_from"])
    evaluation_through = str(chronology["evaluation_through"])
    holdout = [
        row for row in rows
        if holdout_from <= str(row["event_date"]) <= evaluation_through
    ]
    if len(holdout) != int(chronology["holdout_targets"]):
        raise ValueError("combination v3 frozen holdout cannot be reproduced")
    prediction = predict_contextual_combination_v3(
        holdout, universe=universe, contract=combination_contract,
    )
    records = [
        {"row": row, "raw_probability": probability}
        for row, probability in zip(
            prediction["rows"], prediction["probabilities"],
        )
    ]
    result = calibrate_probability_uncertainty_v2(
        rows,
        universe=universe,
        prediction_records=records,
        combination_summary={
            "model_version": COMBINATION_MODEL_VERSION,
            "status": "FROZEN_CONTRACT_REUSED_WITHOUT_REFIT",
            "refit_performed": False,
            "market_used": False,
            "production_effect": False,
        },
        model_version=MODEL_VERSION,
    )
    return {
        **result,
        "combination_model_version": COMBINATION_MODEL_VERSION,
        "combination_refit_performed": False,
    }
