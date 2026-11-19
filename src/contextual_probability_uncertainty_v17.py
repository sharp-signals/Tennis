"""Chronological uncertainty calibration for governed recent form v17."""

from __future__ import annotations

from typing import Any

import numpy as np

from .contextual_family_combination_v17 import (
    MODEL_VERSION as COMBINATION_MODEL_VERSION,
    predict_contextual_combination_v17,
)
from .contextual_family_calibration import _metrics
from .contextual_probability_uncertainty_v2 import (
    _apply_calibrator,
    _chronological_partition,
    _logit,
    calibrate_probability_uncertainty_v2,
)


MODEL_VERSION = "contextual-probability-uncertainty-v17"


def _fit_symmetric_platt(records: list[dict[str, Any]]) -> dict[str, Any]:
    logits = np.asarray([_logit(record["raw_probability"]) for record in records])
    targets = np.asarray([
        1.0 if record["row"]["target_a_win"] else 0.0 for record in records
    ])
    slope = 1.0
    for iteration in range(1, 101):
        probability = 1.0 / (
            1.0 + np.exp(-np.clip(slope * logits, -35.0, 35.0))
        )
        gradient = float(
            np.mean(logits * (probability - targets)) + 0.01 * slope
        )
        hessian = float(
            np.mean(logits * logits * probability * (1.0 - probability))
            + 0.01
        )
        updated = max(0.0, slope - gradient / max(hessian, 1e-12))
        if abs(updated - slope) <= 1e-10:
            slope = updated
            break
        slope = updated
    return {
        "method": "PLATT_LOGIT_NONNEGATIVE",
        "intercept": 0.0,
        "slope": slope,
        "iterations": iteration,
        "symmetry_preserved": True,
    }


def _select_symmetric_calibrator(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    fit, validation = _chronological_partition(records, 0.70)
    candidate = _fit_symmetric_platt(fit)
    targets = np.asarray([
        1.0 if record["row"]["target_a_win"] else 0.0
        for record in validation
    ])
    identity_probability = np.asarray([
        record["raw_probability"] for record in validation
    ])
    platt_probability = np.asarray([
        _apply_calibrator(record["raw_probability"], candidate)
        for record in validation
    ])
    identity_metrics = _metrics(
        targets, identity_probability, total_targets=len(validation),
    )
    platt_metrics = _metrics(
        targets, platt_probability, total_targets=len(validation),
    )
    selected = (
        "PLATT_LOGIT_NONNEGATIVE"
        if platt_metrics["log_loss"] < identity_metrics["log_loss"]
        else "IDENTITY"
    )
    final = (
        _fit_symmetric_platt(records)
        if selected == "PLATT_LOGIT_NONNEGATIVE"
        else {
            "method": "IDENTITY", "intercept": 0.0, "slope": 1.0,
            "symmetry_preserved": True,
        }
    )
    return {
        **final,
        "selection_policy": "chronological_70_30_symmetric_log_loss",
        "validation_candidates": {
            "IDENTITY": identity_metrics,
            "PLATT_LOGIT_NONNEGATIVE": platt_metrics,
        },
    }


def calibrate_probability_uncertainty_v17(
    rows: list[dict[str, Any]], *, universe: str,
    combination_contract: dict[str, Any],
) -> dict[str, Any]:
    if combination_contract.get("model_version") != COMBINATION_MODEL_VERSION:
        raise ValueError("v17 uncertainty requires the v17 combination")
    universe = str(universe).casefold()
    model = combination_contract.get("universes", {}).get(universe, {})
    chronology = model.get("chronology")
    if not isinstance(chronology, dict):
        raise ValueError("combination v17 chronology is required")
    holdout = [
        row for row in rows
        if str(chronology["holdout_from"]) <= str(row["event_date"])
        <= str(chronology["evaluation_through"])
    ]
    if len(holdout) != int(chronology["holdout_targets"]):
        raise ValueError("combination v17 frozen holdout cannot be reproduced")
    prediction = predict_contextual_combination_v17(
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
