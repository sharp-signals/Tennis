"""Second-level combination of out-of-sample contextual family estimates."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contextual_family_calibration import (
    DEFAULT_L1_GRID,
    DEFAULT_L2,
    _family_features,
    _fit_logistic_elastic_net,
    _metrics,
    _predict,
    calibrate_family,
    fit_family_equation,
    predict_family_equation,
)
from .contextual_family_replay import FEATURE_FAMILIES, _split


SCHEMA_VERSION = 1
FAMILY_ORDER = tuple(dict.fromkeys(FEATURE_FAMILIES.values()))
PRIMARY_FAMILIES = ("recent_form", "structural_strength")


def _logit(probability: float) -> float:
    p = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _select_family_hyperparameters(
    train_rows: list[dict[str, Any]],
) -> dict[str, float]:
    """Select family regularisation strictly inside the original train era."""
    inner = _split(train_rows)
    selected = {}
    for family in FAMILY_ORDER:
        result = calibrate_family(inner, family=family)
        if result.get("status") == "INSUFFICIENT_COVERAGE":
            selected[family] = 0.1
        else:
            selected[family] = float(result["selected_l1_on_validation"])
    return selected


def _fit_family_models(
    rows: list[dict[str, Any]], l1_by_family: dict[str, float],
) -> dict[str, dict[str, Any]]:
    return {
        family: fit_family_equation(rows, family=family, l1=l1_by_family[family])
        for family in FAMILY_ORDER
    }


def _attach_family_predictions(
    rows: list[dict[str, Any]], models: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    predicted = {
        family: predict_family_equation(rows, model)
        for family, model in models.items()
    }
    attached = []
    for index, row in enumerate(rows):
        probabilities = {family: predicted[family][index] for family in FAMILY_ORDER}
        attached.append({**row, "family_probabilities": probabilities})
    return attached


def _meta_matrix(
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    columns: list[str] = []
    data: list[list[float]] = []
    for family in FAMILY_ORDER:
        columns.extend([
            f"{family}__logit", f"{family}__unavailable",
            f"{family}__observed_none",
        ])
    for row in rows:
        values: list[float] = []
        states = row.get("family_states", {})
        for family in FAMILY_ORDER:
            probability = row.get("family_probabilities", {}).get(family)
            state = states.get(family, {}).get("data_state")
            values.extend([
                _logit(probability) if probability is not None else 0.0,
                1.0 if state in {"MISSING_DATA", "INSUFFICIENT_SAMPLE"} else 0.0,
                1.0 if state == "OBSERVED_NONE" else 0.0,
            ])
        data.append(values)
    x = np.asarray(data, dtype=float)
    y = np.asarray([1.0 if row["target_a_win"] else 0.0 for row in rows], dtype=float)
    nonnegative = np.asarray([name.endswith("__logit") for name in columns], dtype=bool)
    return x, y, columns, nonnegative


def _candidate_meta_models(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    l1_grid: Iterable[float],
) -> tuple[list[dict[str, Any]], float]:
    x_train, y_train, columns, mask = _meta_matrix(train_rows)
    x_validation, y_validation, validation_columns, _ = _meta_matrix(validation_rows)
    if columns != validation_columns:
        raise ValueError("meta-model column mismatch")
    candidates = []
    for l1 in tuple(float(value) for value in l1_grid):
        intercept, weights, iterations = _fit_logistic_elastic_net(
            x_train, y_train, l1=l1, nonnegative_mask=mask,
        )
        metrics = _metrics(
            y_validation, _predict(x_validation, intercept, weights),
            total_targets=len(validation_rows),
        )
        candidates.append({
            "l1": l1,
            "validation_log_loss": metrics["log_loss"],
            "validation_brier": metrics["brier"],
            "nonzero_coefficients": int(np.sum(np.abs(weights) > 1e-8)),
            "iterations": iterations,
        })
    selected = min(
        candidates,
        key=lambda item: (
            item["validation_log_loss"], item["nonzero_coefficients"], -item["l1"],
        ),
    )
    return candidates, float(selected["l1"])


def _primary_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ready = []
    for row in rows:
        states = row.get("family_states", {})
        ready.append(all(
            states.get(family, {}).get("data_state") in {"OBSERVED", "OBSERVED_NONE"}
            for family in PRIMARY_FAMILIES
        ))
    return {
        "ready": sum(ready),
        "total": len(ready),
        "ready_pct": round(100.0 * sum(ready) / max(1, len(ready)), 2),
    }


def combine_contextual_families(
    rows: list[dict[str, Any]], *, universe: str,
    l1_grid: Iterable[float] = DEFAULT_L1_GRID,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Fit a leakage-safe family stack and evaluate the frozen holdout once."""
    split = _split(rows)
    if min(len(part) for part in split.values()) == 0:
        return {"status": "INSUFFICIENT_CHRONOLOGY", "universe": universe}

    family_l1 = _select_family_hyperparameters(split["train"])
    train_family_models = _fit_family_models(split["train"], family_l1)
    meta_development = _attach_family_predictions(
        split["validation"], train_family_models,
    )
    meta_split = _split(meta_development)
    meta_train = meta_split["train"]
    meta_validation = meta_split["validation"]
    if not meta_validation:
        meta_validation = meta_split["holdout"]
    candidates, selected_l1 = _candidate_meta_models(
        meta_train, meta_validation, l1_grid,
    )

    x_meta, y_meta, columns, nonnegative = _meta_matrix(meta_development)
    meta_intercept, meta_weights, meta_iterations = _fit_logistic_elastic_net(
        x_meta, y_meta, l1=selected_l1, nonnegative_mask=nonnegative,
    )

    development = split["train"] + split["validation"]
    final_family_models = _fit_family_models(development, family_l1)
    holdout = _attach_family_predictions(split["holdout"], final_family_models)
    x_holdout, y_holdout, holdout_columns, _ = _meta_matrix(holdout)
    if columns != holdout_columns:
        raise ValueError("holdout meta-model column mismatch")
    probability = _predict(x_holdout, meta_intercept, meta_weights)
    model_metrics = _metrics(
        y_holdout, probability, total_targets=len(split["holdout"]),
    )
    base_rate = float(np.mean(y_meta))
    baseline_metrics = _metrics(
        y_holdout, np.full(len(y_holdout), base_rate),
        total_targets=len(split["holdout"]),
    )

    family_holdout_metrics = {}
    for family in FAMILY_ORDER:
        material = [
            (row["family_probabilities"][family], row["target_a_win"])
            for row in holdout if row["family_probabilities"][family] is not None
        ]
        if material:
            family_holdout_metrics[family] = _metrics(
                np.asarray([float(target) for _, target in material]),
                np.asarray([float(value) for value, _ in material]),
                total_targets=len(holdout),
            )
    best_family_loss = min(
        value["log_loss"] for value in family_holdout_metrics.values()
        if value["log_loss"] is not None
    )
    supported = (
        model_metrics["log_loss"] < baseline_metrics["log_loss"]
        and model_metrics["log_loss"] < best_family_loss
    )
    coefficients = {
        name: round(float(value), 8) for name, value in zip(columns, meta_weights)
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "status": "HOLDOUT_SUPPORTED" if supported else "NOT_SUPPORTED",
        "mode": "OUT_OF_SAMPLE_FAMILY_STACK",
        "split_targets": {name: len(part) for name, part in split.items()},
        "family_l1_selected_inside_train": family_l1,
        "meta_l1_selected_inside_validation": selected_l1,
        "meta_candidates": candidates,
        "equation": "logit(P(player_a wins)) = intercept + sum(nonnegative_family_coefficient * family_logit) + data_state_terms",
        "intercept": round(float(meta_intercept), 8),
        "coefficients": coefficients,
        "family_coefficients": {
            family: coefficients[f"{family}__logit"] for family in FAMILY_ORDER
        },
        "holdout": {
            "combined": model_metrics,
            "intercept_only_baseline": baseline_metrics,
            "individual_families": family_holdout_metrics,
            "best_individual_family_log_loss": best_family_loss,
            "gain_vs_baseline": round(
                baseline_metrics["log_loss"] - model_metrics["log_loss"], 6,
            ),
            "gain_vs_best_family": round(
                best_family_loss - model_metrics["log_loss"], 6,
            ),
            "primary_readiness": _primary_readiness(holdout),
        },
        "uncertainty_policy": {
            "missing_family_is_not_neutral": True,
            "missing_and_observed_none_are_distinct": True,
            "primary_families_required_for_operational_readiness": list(PRIMARY_FAMILIES),
            "interval_calibration_pending": True,
        },
        "directional_family_coefficients_nonnegative": True,
        "overall_probability_fitted": True,
        "fair_odd_fitted": False,
        "market_used": False,
        "production_effect": False,
        "iterations_final": meta_iterations,
    }
    if include_diagnostics:
        report["_diagnostics"] = {
            "holdout_rows": holdout,
            "holdout_probabilities": [float(value) for value in probability],
        }
    return report
