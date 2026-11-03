"""Chronological, market-free calibration of each contextual family.

Each family is fitted independently per universe.  Train estimates candidate
equations, validation selects regularisation, and holdout is touched once for
final descriptive evaluation.  No family is combined into production pricing.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contextual_family_replay import FEATURE_FAMILIES, _split


SCHEMA_VERSION = 1
DEFAULT_L1_GRID = (0.0, 0.0005, 0.001, 0.003, 0.01, 0.03, 0.1)
DEFAULT_L2 = 0.01
CALIBRATION_FEATURE_PROFILES = {
    "legacy_v0": {
        "structural_strength": ("current_rank_log_ratio",),
        "surface_conditions": (
            "same_surface_result_balance_90d", "career_surface_win_rate_margin",
        ),
    },
    "contextual_v1": {
        "structural_strength": ("contextual_structural_signal_v1",),
        "surface_conditions": ("contextual_surface_signal_v1",),
    },
    "contextual_v2": {
        "structural_strength": ("contextual_structural_signal_v2",),
        "surface_conditions": ("contextual_surface_signal_v1",),
    },
}


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _soft_threshold(values: np.ndarray, threshold: float) -> np.ndarray:
    return np.sign(values) * np.maximum(np.abs(values) - threshold, 0.0)


def _fit_logistic_elastic_net(
    x: np.ndarray,
    y: np.ndarray,
    *,
    l1: float,
    l2: float = DEFAULT_L2,
    max_iter: int = 5000,
    tolerance: float = 1e-9,
    nonnegative_mask: np.ndarray | None = None,
) -> tuple[float, np.ndarray, int]:
    if x.ndim != 2 or y.ndim != 1 or len(x) != len(y) or not len(y):
        raise ValueError("invalid calibration matrix")
    if not 0.0 < float(y.mean()) < 1.0:
        raise ValueError("both outcomes are required")
    design = np.column_stack([np.ones(len(x)), x])
    spectral = float(np.linalg.norm(design, ord=2))
    lipschitz = 0.25 * spectral * spectral / len(x) + float(l2) + 1e-12
    step = 1.0 / lipschitz
    intercept = math.log(float(y.mean()) / (1.0 - float(y.mean())))
    weights = np.zeros(x.shape[1], dtype=float)
    if nonnegative_mask is not None:
        nonnegative_mask = np.asarray(nonnegative_mask, dtype=bool)
        if nonnegative_mask.shape != weights.shape:
            raise ValueError("nonnegative_mask has invalid shape")

    for iteration in range(1, max_iter + 1):
        probability = _sigmoid(intercept + x @ weights)
        residual = probability - y
        next_intercept = intercept - step * float(residual.mean())
        gradient = (x.T @ residual) / len(x) + float(l2) * weights
        next_weights = _soft_threshold(weights - step * gradient, step * float(l1))
        if nonnegative_mask is not None:
            next_weights[nonnegative_mask] = np.maximum(
                next_weights[nonnegative_mask], 0.0,
            )
        delta = max(
            abs(next_intercept - intercept),
            float(np.max(np.abs(next_weights - weights))) if len(weights) else 0.0,
        )
        intercept, weights = next_intercept, next_weights
        if delta <= tolerance:
            return intercept, weights, iteration
    return intercept, weights, max_iter


def _family_features(family: str, feature_profile: str = "legacy_v0") -> tuple[str, ...]:
    profile = CALIBRATION_FEATURE_PROFILES.get(feature_profile)
    if profile is None:
        raise ValueError(f"unknown feature profile: {feature_profile}")
    if family in profile:
        return profile[family]
    return tuple(key for key, owner in FEATURE_FAMILIES.items() if owner == family)


def _directional_mask(columns: list[str], feature_profile: str) -> np.ndarray | None:
    if feature_profile not in {"contextual_v1", "contextual_v2"}:
        return None
    return np.asarray([
        name in {
            "contextual_structural_signal_v1", "contextual_structural_signal_v2",
            "contextual_surface_signal_v1",
        }
        for name in columns
    ], dtype=bool)


def _covered_rows(rows: Iterable[dict[str, Any]], features: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if any(row.get("features", {}).get(feature) is not None for feature in features)
    ]


def _fit_preprocessor(
    rows: list[dict[str, Any]], features: tuple[str, ...],
) -> dict[str, Any]:
    parameters = {}
    for feature in features:
        material = np.array([
            float(row["features"][feature])
            for row in rows if row["features"].get(feature) is not None
        ], dtype=float)
        if not len(material):
            parameters[feature] = {
                "available": False, "median": 0.0, "lower": 0.0,
                "upper": 0.0, "scale": 1.0,
            }
            continue
        lower, upper = np.quantile(material, [0.01, 0.99])
        median = float(np.median(material))
        clipped = np.clip(material, lower, upper)
        q25, q75 = np.quantile(clipped, [0.25, 0.75])
        scale = float((q75 - q25) / 1.349)
        if not math.isfinite(scale) or scale <= 1e-12:
            scale = float(np.std(clipped))
        if not math.isfinite(scale) or scale <= 1e-12:
            scale = 1.0
        parameters[feature] = {
            "available": True,
            "median": median,
            "lower": float(lower),
            "upper": float(upper),
            "scale": scale,
        }
    return {
        "method": "train_only_median_winsor_1_99_robust_scale",
        "missing_policy": "median_imputation_plus_explicit_missing_indicator",
        "features": parameters,
    }


def _transform(
    rows: list[dict[str, Any]],
    features: tuple[str, ...],
    preprocessor: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    columns: list[np.ndarray] = []
    names: list[str] = []
    for feature in features:
        params = preprocessor["features"][feature]
        missing = np.array([
            row["features"].get(feature) is None for row in rows
        ], dtype=float)
        raw = np.array([
            params["median"] if row["features"].get(feature) is None
            else float(row["features"][feature])
            for row in rows
        ], dtype=float)
        if params["available"]:
            raw = np.clip(raw, params["lower"], params["upper"])
            standard = (raw - params["median"]) / params["scale"]
        else:
            standard = np.zeros(len(rows), dtype=float)
        columns.extend([standard, missing])
        names.extend([feature, f"{feature}__missing"])
    x = np.column_stack(columns) if columns else np.empty((len(rows), 0))
    y = np.array([1.0 if row["target_a_win"] else 0.0 for row in rows], dtype=float)
    return x, y, names


def _metrics(y: np.ndarray, probability: np.ndarray, *, total_targets: int) -> dict[str, Any]:
    if not len(y):
        return {
            "covered": 0, "coverage_pct": 0.0, "log_loss": None,
            "brier": None, "accuracy_pct": None, "ece_10": None,
        }
    p = np.clip(probability, 1e-9, 1.0 - 1e-9)
    log_loss = -float(np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    brier = float(np.mean((p - y) ** 2))
    accuracy = float(np.mean((p >= 0.5) == (y >= 0.5)))
    ece = 0.0
    for low in np.linspace(0.0, 0.9, 10):
        high = low + 0.1
        selected = (p >= low) & ((p < high) if high < 1.0 else (p <= high))
        if selected.any():
            ece += float(selected.mean()) * abs(float(p[selected].mean() - y[selected].mean()))
    return {
        "covered": int(len(y)),
        "coverage_pct": round(100.0 * len(y) / max(1, total_targets), 2),
        "log_loss": round(log_loss, 6),
        "brier": round(brier, 6),
        "accuracy_pct": round(100.0 * accuracy, 2),
        "ece_10": round(ece, 6),
        "predicted_mean": round(float(p.mean()), 6),
        "observed_rate": round(float(y.mean()), 6),
    }


def _predict(x: np.ndarray, intercept: float, weights: np.ndarray) -> np.ndarray:
    return _sigmoid(float(intercept) + x @ weights)


def fit_family_equation(
    rows: list[dict[str, Any]], *, family: str, l1: float,
    feature_profile: str = "legacy_v0",
) -> dict[str, Any]:
    """Fit one frozen family equation for later out-of-sample prediction."""
    features = _family_features(family, feature_profile)
    covered = _covered_rows(rows, features)
    if not covered:
        return {
            "family": family, "status": "INSUFFICIENT_COVERAGE",
            "feature_profile": feature_profile,
        }
    preprocessor = _fit_preprocessor(covered, features)
    x, y, columns = _transform(covered, features, preprocessor)
    intercept, weights, iterations = _fit_logistic_elastic_net(
        x, y, l1=l1,
        nonnegative_mask=_directional_mask(columns, feature_profile),
    )
    return {
        "family": family,
        "feature_profile": feature_profile,
        "status": "FITTED",
        "features": list(features),
        "preprocessor": preprocessor,
        "intercept": float(intercept),
        "columns": columns,
        "weights": [float(value) for value in weights],
        "l1": float(l1),
        "l2": DEFAULT_L2,
        "iterations": iterations,
        "market_used": False,
    }


def predict_family_equation(
    rows: list[dict[str, Any]], model: dict[str, Any],
) -> list[float | None]:
    """Predict only rows with at least one observed family component."""
    if model.get("status") != "FITTED":
        return [None] * len(rows)
    features = tuple(model["features"])
    wanted = [
        index for index, row in enumerate(rows)
        if any(row.get("features", {}).get(feature) is not None for feature in features)
    ]
    result: list[float | None] = [None] * len(rows)
    if not wanted:
        return result
    selected = [rows[index] for index in wanted]
    x, _, columns = _transform(selected, features, model["preprocessor"])
    if columns != model["columns"]:
        raise ValueError("family equation column mismatch")
    probability = _predict(
        x, float(model["intercept"]), np.asarray(model["weights"], dtype=float),
    )
    for index, value in zip(wanted, probability):
        result[index] = float(value)
    return result


def calibrate_family(
    split: dict[str, list[dict[str, Any]]],
    *,
    family: str,
    l1_grid: Iterable[float] = DEFAULT_L1_GRID,
    feature_profile: str = "legacy_v0",
) -> dict[str, Any]:
    features = _family_features(family, feature_profile)
    covered = {name: _covered_rows(rows, features) for name, rows in split.items()}
    if min(len(covered["train"]), len(covered["validation"]), len(covered["holdout"])) == 0:
        return {
            "family": family, "status": "INSUFFICIENT_COVERAGE",
            "features": list(features), "feature_profile": feature_profile,
        }

    train_preprocessor = _fit_preprocessor(covered["train"], features)
    x_train, y_train, column_names = _transform(
        covered["train"], features, train_preprocessor,
    )
    x_validation, y_validation, _ = _transform(
        covered["validation"], features, train_preprocessor,
    )
    baseline_rate = float(np.clip(y_train.mean(), 1e-9, 1.0 - 1e-9))
    candidates = []
    fitted = {}
    for l1 in tuple(float(value) for value in l1_grid):
        intercept, weights, iterations = _fit_logistic_elastic_net(
            x_train, y_train, l1=l1,
            nonnegative_mask=_directional_mask(column_names, feature_profile),
        )
        validation_metrics = _metrics(
            y_validation, _predict(x_validation, intercept, weights),
            total_targets=len(split["validation"]),
        )
        item = {
            "l1": l1,
            "validation_log_loss": validation_metrics["log_loss"],
            "validation_brier": validation_metrics["brier"],
            "nonzero_coefficients": int(np.sum(np.abs(weights) > 1e-8)),
            "iterations": iterations,
        }
        candidates.append(item)
        fitted[l1] = (intercept, weights)
    selected = min(
        candidates,
        key=lambda item: (
            item["validation_log_loss"], item["nonzero_coefficients"], -item["l1"],
        ),
    )

    development = covered["train"] + covered["validation"]
    final_preprocessor = _fit_preprocessor(development, features)
    x_development, y_development, final_columns = _transform(
        development, features, final_preprocessor,
    )
    x_holdout, y_holdout, _ = _transform(
        covered["holdout"], features, final_preprocessor,
    )
    intercept, weights, iterations = _fit_logistic_elastic_net(
        x_development, y_development, l1=selected["l1"],
        nonnegative_mask=_directional_mask(final_columns, feature_profile),
    )
    holdout_probability = _predict(x_holdout, intercept, weights)
    holdout_metrics = _metrics(
        y_holdout, holdout_probability, total_targets=len(split["holdout"]),
    )
    development_rate = float(np.clip(y_development.mean(), 1e-9, 1.0 - 1e-9))
    baseline_holdout = _metrics(
        y_holdout, np.full(len(y_holdout), development_rate),
        total_targets=len(split["holdout"]),
    )
    validation_baseline = _metrics(
        y_validation, np.full(len(y_validation), baseline_rate),
        total_targets=len(split["validation"]),
    )
    validation_supported = selected["validation_log_loss"] < validation_baseline["log_loss"]
    holdout_supported = holdout_metrics["log_loss"] < baseline_holdout["log_loss"]
    coefficients = {
        name: round(float(value), 8)
        for name, value in zip(final_columns, weights)
    }
    return {
        "family": family,
        "feature_profile": feature_profile,
        "status": (
            "HOLDOUT_SUPPORTED" if validation_supported and holdout_supported
            else "NOT_SUPPORTED"
        ),
        "features": list(features),
        "equation": "logit(P(player_a wins | family observed)) = intercept + sum(coefficient * transformed_component)",
        "intercept": round(float(intercept), 8),
        "coefficients": coefficients,
        "active_coefficients": [
            name for name, value in coefficients.items() if abs(value) > 1e-8
        ],
        "selected_l1_on_validation": selected["l1"],
        "fixed_l2": DEFAULT_L2,
        "selection_candidates": candidates,
        "preprocessor": final_preprocessor,
        "validation": {
            "model": next(
                item for item in candidates if item["l1"] == selected["l1"]
            ),
            "baseline": validation_baseline,
        },
        "holdout": {
            "model": holdout_metrics,
            "intercept_only_baseline": baseline_holdout,
            "log_loss_improvement": round(
                baseline_holdout["log_loss"] - holdout_metrics["log_loss"], 6,
            ),
        },
        "iterations_final": iterations,
        "market_used": False,
        "production_effect": False,
    }


def calibrate_contextual_families(
    rows: list[dict[str, Any]], *, universe: str,
    feature_profile: str = "legacy_v0",
) -> dict[str, Any]:
    split = _split(rows)
    families = tuple(dict.fromkeys(FEATURE_FAMILIES.values()))
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "mode": "FAMILY_LEVEL_CHRONOLOGICAL_CALIBRATION",
        "feature_profile": feature_profile,
        "split_targets": {name: len(items) for name, items in split.items()},
        "families": {
            family: calibrate_family(
                split, family=family, feature_profile=feature_profile,
            ) for family in families
        },
        "families_combined": False,
        "overall_probability_fitted": False,
        "fair_odd_fitted": False,
        "market_used": False,
        "production_effect": False,
    }


def _runtime_model(calibration: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "FITTED",
        "features": calibration["features"],
        "preprocessor": calibration["preprocessor"],
        "intercept": calibration["intercept"],
        "columns": list(calibration["coefficients"]),
        "weights": list(calibration["coefficients"].values()),
    }


def compare_family_feature_profiles(
    rows: list[dict[str, Any]], *, universe: str,
    contextual_profile: str = "contextual_v1",
) -> dict[str, Any]:
    """Compare legacy and contextual equations on the same chronological holdout."""
    split = _split(rows)
    comparisons = {}
    for family in ("structural_strength", "surface_conditions"):
        legacy = calibrate_family(split, family=family, feature_profile="legacy_v0")
        contextual = calibrate_family(
            split, family=family, feature_profile=contextual_profile,
        )
        profiles = {"legacy_v0": legacy, contextual_profile: contextual}
        if any(item.get("status") == "INSUFFICIENT_COVERAGE" for item in profiles.values()):
            comparisons[family] = {"status": "INSUFFICIENT_PAIRED_COVERAGE", "profiles": profiles}
            continue
        holdout = split["holdout"]
        legacy_prediction = predict_family_equation(holdout, _runtime_model(legacy))
        contextual_prediction = predict_family_equation(holdout, _runtime_model(contextual))
        paired = [
            (row, old, new) for row, old, new in zip(
                holdout, legacy_prediction, contextual_prediction,
            ) if old is not None and new is not None
        ]
        if not paired:
            comparisons[family] = {"status": "INSUFFICIENT_PAIRED_COVERAGE", "profiles": profiles}
            continue
        targets = np.asarray([float(row["target_a_win"]) for row, _, _ in paired])
        legacy_metrics = _metrics(
            targets, np.asarray([old for _, old, _ in paired]), total_targets=len(holdout),
        )
        contextual_metrics = _metrics(
            targets, np.asarray([new for _, _, new in paired]), total_targets=len(holdout),
        )
        delta = legacy_metrics["log_loss"] - contextual_metrics["log_loss"]
        comparisons[family] = {
            "status": "CONTEXTUAL_BETTER" if delta > 0 else "LEGACY_BETTER_OR_EQUAL",
            "paired_holdout_targets": len(paired),
            "legacy_v0": legacy_metrics,
            contextual_profile: contextual_metrics,
            "contextual_log_loss_gain": round(delta, 6),
            "profiles": profiles,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "mode": "PAIRED_CHRONOLOGICAL_FAMILY_PROFILE_COMPARISON",
        "contextual_profile": contextual_profile,
        "split_targets": {name: len(items) for name, items in split.items()},
        "comparisons": comparisons,
        "market_used": False,
        "production_effect": False,
    }
