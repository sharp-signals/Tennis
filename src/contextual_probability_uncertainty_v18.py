"""Chronological uncertainty calibration for contextual consensus v18."""

from __future__ import annotations

from typing import Any

from .contextual_family_combination_v18 import (
    MODEL_VERSION as COMBINATION_MODEL_VERSION,
    predict_contextual_combination_v18,
)
from .contextual_probability_uncertainty_v17 import _select_symmetric_calibrator
from .contextual_probability_uncertainty_v2 import calibrate_probability_uncertainty_v2


MODEL_VERSION = "contextual-probability-uncertainty-v18"


def calibrate_probability_uncertainty_v18(
    rows: list[dict[str, Any]], *, universe: str,
    combination_contract: dict[str, Any],
) -> dict[str, Any]:
    if combination_contract.get("model_version") != COMBINATION_MODEL_VERSION:
        raise ValueError("v18 uncertainty requires the v18 combination")
    universe = str(universe).casefold()
    model = combination_contract.get("universes", {}).get(universe, {})
    chronology = model.get("chronology")
    if not isinstance(chronology, dict):
        raise ValueError("combination v18 chronology is required")
    holdout = [
        row for row in rows
        if str(chronology["holdout_from"]) <= str(row["event_date"])
        <= str(chronology["evaluation_through"])
    ]
    if len(holdout) != int(chronology["holdout_targets"]):
        raise ValueError("combination v18 frozen holdout cannot be reproduced")
    prediction = predict_contextual_combination_v18(
        holdout, universe=universe, contract=combination_contract,
    )
    records = [
        {"row": row, "raw_probability": probability}
        for row, probability in zip(
            prediction["rows"], prediction["probabilities"], strict=True,
        )
    ]
    result = calibrate_probability_uncertainty_v2(
        rows, universe=universe, prediction_records=records,
        combination_summary={
            "model_version": COMBINATION_MODEL_VERSION,
            "status": "FROZEN_CONTRACT_REUSED_WITHOUT_REFIT",
            "refit_performed": False,
            "market_used": False,
            "production_effect": False,
        },
        model_version=MODEL_VERSION,
        calibrator_selector=_select_symmetric_calibrator,
    )
    return {
        **result,
        "combination_model_version": COMBINATION_MODEL_VERSION,
        "combination_refit_performed": False,
    }
