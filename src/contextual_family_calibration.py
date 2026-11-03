"""Chronological, market-free calibration of each contextual family.

Each family is fitted independently per universe.  Train estimates candidate
equations, validation selects regularisation, and holdout is touched once for
final descriptive evaluation.  No family is combined into production pricing.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contextual_family_replay import (
    FEATURE_FAMILIES,
    RECENT_LOSS_CONTEXT_GRID_V2,
    _split,
    recent_loss_context_feature,
)


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
    "surface_v2": {
        "surface_conditions": ("contextual_surface_signal_v2",),
    },
    "surface_v3": {
        "surface_conditions": ("contextual_surface_signal_v3",),
    },
    "surface_exact_career_raw": {
        "surface_conditions": ("exact_surface_career_margin_raw",),
    },
    "surface_exact_career_previous_raw": {
        "surface_conditions": (
            "exact_surface_career_margin_raw",
            "exact_surface_previous_margin_raw",
        ),
    },
    "surface_exact_career_seasons_raw": {
        "surface_conditions": (
            "exact_surface_career_margin_raw",
            "exact_surface_previous_margin_raw",
            "exact_surface_current_margin_raw",
        ),
    },
    "surface_exact_career_seasons_shrunk": {
        "surface_conditions": (
            "exact_surface_career_margin_shrunk",
            "exact_surface_previous_margin_shrunk",
            "exact_surface_current_margin_shrunk",
        ),
    },
    "contextual_v2": {
        "structural_strength": ("contextual_structural_signal_v2",),
        "surface_conditions": ("contextual_surface_signal_v1",),
    },
    "contextual_v3": {
        "structural_strength": (
            "contextual_structural_rank_core_v3",
            "contextual_structural_trajectory_margin_v3",
            "contextual_structural_inactivity_margin_v3",
            "contextual_structural_recovery_margin_v3",
        ),
        "surface_conditions": ("contextual_surface_signal_v1",),
    },
    "contextual_v4": {
        "structural_strength": (
            "contextual_structural_rank_core_v3",
            "contextual_structural_trajectory_margin_v3",
            "contextual_structural_inactivity_margin_v3",
            "contextual_structural_recovery_margin_v3",
            "contextual_structural_material_band_gap_v4",
        ),
        "surface_conditions": ("contextual_surface_signal_v1",),
    },
    "contextual_v5": {
        "structural_strength": (
            "contextual_structural_rank_core_v3",
            "contextual_structural_trajectory_margin_v3",
            "contextual_structural_inactivity_margin_v3",
            "contextual_structural_recovery_margin_v3",
            "contextual_structural_points_log_ratio_v5",
        ),
        "surface_conditions": ("contextual_surface_signal_v1",),
    },
    "recent_v0": {
        "recent_form": ("contextual_recent_result_core_v1",),
    },
    "recent_v1": {
        "recent_form": (
            "contextual_recent_result_core_v1",
            "contextual_recent_competitiveness_v1",
        ),
    },
    "recent_v2": {
        "recent_form": (
            "contextual_recent_result_core_v1",
            "contextual_recent_competitiveness_v1",
            "contextual_recent_win_quality_v1",
        ),
    },
    "recent_v3": {
        "recent_form": (
            "contextual_recent_result_core_v1",
            "contextual_recent_competitiveness_v1",
            "contextual_recent_win_quality_v1",
            "contextual_recent_loss_context_v1",
        ),
    },
    "recent_guarded_v4": {
        "recent_form": (
            "contextual_recent_result_core_v1",
            "contextual_recent_competitiveness_residual_v2",
            "contextual_recent_win_quality_v1",
            "contextual_recent_bad_loss_penalty_v2",
        ),
    },
}
for _alpha in RECENT_LOSS_CONTEXT_GRID_V2:
    CALIBRATION_FEATURE_PROFILES[
        f"recent_capped_loss_{int(round(_alpha * 100)):03d}"
    ] = {
        "recent_form": (
            recent_loss_context_feature(_alpha),
            "contextual_recent_competitiveness_v1",
            "contextual_recent_win_quality_v1",
        ),
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
    if feature_profile not in {
        "contextual_v1", "contextual_v2", "contextual_v3", "contextual_v4",
        "contextual_v5", "recent_v0", "recent_v1", "recent_v2", "recent_v3",
        "recent_guarded_v4",
        "surface_v2",
        "surface_v3",
        "surface_exact_career_raw",
        "surface_exact_career_previous_raw",
        "surface_exact_career_seasons_raw",
        "surface_exact_career_seasons_shrunk",
        *(f"recent_capped_loss_{int(round(value * 100)):03d}"
          for value in RECENT_LOSS_CONTEXT_GRID_V2),
    }:
        return None
    return np.asarray([
        name in {
            "contextual_structural_signal_v1", "contextual_structural_signal_v2",
            "contextual_surface_signal_v1",
            "contextual_surface_signal_v2",
            "contextual_surface_signal_v3",
            "exact_surface_career_margin_raw",
            "exact_surface_previous_margin_raw",
            "exact_surface_current_margin_raw",
            "exact_surface_career_margin_shrunk",
            "exact_surface_previous_margin_shrunk",
            "exact_surface_current_margin_shrunk",
            "contextual_structural_rank_core_v3",
            "contextual_structural_trajectory_margin_v3",
            "contextual_structural_inactivity_margin_v3",
            "contextual_structural_recovery_margin_v3",
            "contextual_structural_material_band_gap_v4",
            "contextual_structural_points_log_ratio_v5",
            "contextual_recent_result_core_v1",
            "contextual_recent_competitiveness_v1",
            "contextual_recent_win_quality_v1",
            "contextual_recent_loss_context_v1",
            "contextual_recent_competitiveness_residual_v2",
            "contextual_recent_bad_loss_penalty_v2",
        } or name.startswith("contextual_recent_adjusted_result_loss_")
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


def _structural_segment_labels(row: dict[str, Any]) -> tuple[str, ...]:
    """Return overlapping, ex-ante diagnostic segments for structural v2."""
    labels = ["all"]
    ranks = row.get("diagnostics", {})
    rank_a = ranks.get("rank_a")
    rank_b = ranks.get("rank_b")
    if rank_a and rank_b:
        ratio = max(float(rank_a), float(rank_b)) / min(float(rank_a), float(rank_b))
        if ratio < 1.5:
            labels.append("rank_gap_close_lt_1_5x")
        elif ratio < 3.0:
            labels.append("rank_gap_moderate_1_5_to_3x")
        elif ratio < 8.0:
            labels.append("rank_gap_large_3_to_8x")
        else:
            labels.append("rank_gap_extreme_ge_8x")
        if min(float(rank_a), float(rank_b)) <= 20 and max(float(rank_a), float(rank_b)) >= 100:
            labels.append("elite_top20_vs_rank100_plus")

    audit_root = row.get("candidate_equation_audit", {})
    audit = (
        audit_root.get("structural_strength_v5")
        or audit_root.get("structural_strength_v4")
        or audit_root.get("structural_strength_v3")
        or audit_root.get("structural_strength_v2", {})
    )
    components = audit.get("components", {})
    days = [
        value for value in (
            components.get("days_since_last_match_a"),
            components.get("days_since_last_match_b"),
        ) if value is not None
    ]
    if days and max(float(value) for value in days) > 90:
        labels.append("inactivity_over_90d")
    trajectories = [
        abs(float(value)) for value in (
            components.get("trajectory_a"), components.get("trajectory_b"),
        ) if value is not None
    ]
    if trajectories and max(trajectories) >= 0.25:
        labels.append("ranking_trajectory_material")
    if abs(float(components.get("supported_recovery") or 0.0)) > 1e-9:
        labels.append("supported_ranking_recovery")
    return tuple(labels)


def _paired_segment_diagnostics(
    paired: list[tuple[dict[str, Any], float, float]],
) -> dict[str, Any]:
    buckets: dict[str, list[tuple[dict[str, Any], float, float]]] = {}
    for item in paired:
        for label in _structural_segment_labels(item[0]):
            buckets.setdefault(label, []).append(item)
    result = {}
    for label, items in buckets.items():
        targets = np.asarray([float(row["target_a_win"]) for row, _, _ in items])
        old = np.clip(np.asarray([value for _, value, _ in items]), 1e-9, 1.0 - 1e-9)
        new = np.clip(np.asarray([value for _, _, value in items]), 1e-9, 1.0 - 1e-9)
        old_loss = -(targets * np.log(old) + (1.0 - targets) * np.log(1.0 - old))
        new_loss = -(targets * np.log(new) + (1.0 - targets) * np.log(1.0 - new))
        gain = old_loss - new_loss
        mean = float(gain.mean())
        standard_error = float(gain.std(ddof=1) / np.sqrt(len(gain))) if len(gain) > 1 else None
        lower = mean - 1.96 * standard_error if standard_error is not None else None
        upper = mean + 1.96 * standard_error if standard_error is not None else None
        if lower is not None and lower > 0:
            verdict = "CONTEXTUAL_BETTER"
        elif upper is not None and upper < 0:
            verdict = "LEGACY_BETTER"
        else:
            verdict = "INCONCLUSIVE"
        result[label] = {
            "paired_targets": len(items),
            "legacy_log_loss": round(float(old_loss.mean()), 6),
            "contextual_log_loss": round(float(new_loss.mean()), 6),
            "contextual_log_loss_gain": round(mean, 6),
            "gain_95pct_ci": (
                None if lower is None else [round(lower, 6), round(upper, 6)]
            ),
            "verdict": verdict,
        }
    return result


def _surface_segment_labels(row: dict[str, Any]) -> tuple[str, ...]:
    """Return ex-ante surface/condition segments without using the result."""
    labels = ["all"]
    surface = str(row.get("surface") or "unknown").strip().casefold()
    labels.append(f"surface_{surface}")
    diagnostics = row.get("diagnostics", {})
    venue = str(diagnostics.get("venue") or "unknown").strip().casefold()
    labels.append(f"venue_{venue}")
    pace = str(diagnostics.get("pace") or "unknown").strip().casefold()
    labels.append(f"pace_{pace}")
    samples = row.get("samples", {})
    bilateral = min(
        int(samples.get("surface_a") or 0),
        int(samples.get("surface_b") or 0),
    )
    if bilateral < 5:
        labels.append("bilateral_surface_sample_lt5")
    elif bilateral < 15:
        labels.append("bilateral_surface_sample_5_14")
    elif bilateral < 30:
        labels.append("bilateral_surface_sample_15_29")
    else:
        labels.append("bilateral_surface_sample_ge30")
    audit = row.get("candidate_equation_audit", {}).get("surface_conditions", {})
    components = audit.get("components", {})
    if abs(float(components.get("transition_signal") or 0.0)) > 1e-12:
        labels.append("surface_transition_present")
    else:
        labels.append("surface_transition_absent")
    if components.get("selected_specific_context"):
        labels.append("specific_context_available")
    else:
        labels.append("specific_context_unavailable")
    return tuple(labels)


def _paired_diagnostics_by_labels(
    paired: list[tuple[dict[str, Any], float, float]], labeler,
) -> dict[str, Any]:
    buckets: dict[str, list[tuple[dict[str, Any], float, float]]] = {}
    for item in paired:
        for label in labeler(item[0]):
            buckets.setdefault(label, []).append(item)
    result = {}
    for label, items in buckets.items():
        targets = np.asarray([float(row["target_a_win"]) for row, _, _ in items])
        old = np.asarray([value for _, value, _ in items])
        new = np.asarray([value for _, _, value in items])
        old_metrics = _metrics(targets, old, total_targets=len(items))
        new_metrics = _metrics(targets, new, total_targets=len(items))
        gain = _paired_probability_gain(targets, old, new)
        result[label] = {
            "paired_targets": len(items),
            "legacy": old_metrics,
            "contextual": new_metrics,
            **gain,
        }
    return result


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
        if family == "structural_strength" and contextual_profile in {
            "contextual_v2", "contextual_v3", "contextual_v4",
            "contextual_v5",
        }:
            comparisons[family]["segment_diagnostics"] = _paired_segment_diagnostics(paired)
        if family == "surface_conditions":
            comparisons[family]["segment_diagnostics"] = (
                _paired_diagnostics_by_labels(paired, _surface_segment_labels)
            )
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


def compare_recent_form_feature_profiles(
    rows: list[dict[str, Any]], *, universe: str,
) -> dict[str, Any]:
    """Compare nested recent-form equations on one untouched holdout.

    The hierarchy is human-defined: results, competitiveness, win quality and
    finally loss context. History may reject an addition or refine its size;
    it does not reorder those roles.
    """
    split = _split(rows)
    profile_names = ("recent_v0", "recent_v1", "recent_v2", "recent_v3")
    profiles = {
        name: calibrate_family(
            split, family="recent_form", feature_profile=name,
        )
        for name in profile_names
    }
    guarded_split, guarded_audit = _build_guarded_recent_split(split)
    profiles["recent_guarded_v4"] = calibrate_family(
        guarded_split, family="recent_form", feature_profile="recent_guarded_v4",
    )
    if any(item.get("status") == "INSUFFICIENT_COVERAGE" for item in profiles.values()):
        return {
            "schema_version": SCHEMA_VERSION,
            "universe": str(universe).strip().casefold(),
            "status": "INSUFFICIENT_PAIRED_COVERAGE",
            "profiles": profiles,
            "market_used": False,
            "production_effect": False,
        }
    holdout = split["holdout"]
    predictions = {
        name: predict_family_equation(holdout, _runtime_model(model))
        for name, model in profiles.items()
        if name != "recent_guarded_v4"
    }
    predictions["recent_guarded_v4"] = predict_family_equation(
        guarded_split["holdout"], _runtime_model(profiles["recent_guarded_v4"]),
    )
    all_profile_names = profile_names + ("recent_guarded_v4",)
    wanted = [
        index for index in range(len(holdout))
        if all(predictions[name][index] is not None for name in all_profile_names)
    ]
    if not wanted:
        return {
            "schema_version": SCHEMA_VERSION,
            "universe": str(universe).strip().casefold(),
            "status": "INSUFFICIENT_PAIRED_COVERAGE",
            "profiles": profiles,
            "market_used": False,
            "production_effect": False,
        }
    targets = np.asarray([
        float(holdout[index]["target_a_win"]) for index in wanted
    ])
    paired_metrics = {
        name: _metrics(
            targets,
            np.asarray([predictions[name][index] for index in wanted]),
            total_targets=len(holdout),
        )
        for name in all_profile_names
    }
    incremental = {}
    for previous, current in zip(profile_names, profile_names[1:]):
        old = np.clip(np.asarray([
            predictions[previous][index] for index in wanted
        ]), 1e-9, 1.0 - 1e-9)
        new = np.clip(np.asarray([
            predictions[current][index] for index in wanted
        ]), 1e-9, 1.0 - 1e-9)
        old_loss = -(targets * np.log(old) + (1.0 - targets) * np.log(1.0 - old))
        new_loss = -(targets * np.log(new) + (1.0 - targets) * np.log(1.0 - new))
        paired_gain = old_loss - new_loss
        gain = float(paired_gain.mean())
        standard_error = (
            float(paired_gain.std(ddof=1) / np.sqrt(len(paired_gain)))
            if len(paired_gain) > 1 else None
        )
        lower = gain - 1.96 * standard_error if standard_error is not None else None
        upper = gain + 1.96 * standard_error if standard_error is not None else None
        if lower is not None and lower > 0:
            verdict = "SUPPORTED"
        elif upper is not None and upper < 0:
            verdict = "REJECTED"
        else:
            verdict = "INCONCLUSIVE"
        incremental[f"{previous}_to_{current}"] = {
            "log_loss_gain": round(gain, 6),
            "gain_95pct_ci": (
                None if lower is None else [round(lower, 6), round(upper, 6)]
            ),
            "status": verdict,
        }
    guard_old = np.clip(np.asarray([
        predictions["recent_v3"][index] for index in wanted
    ]), 1e-9, 1.0 - 1e-9)
    guard_new = np.clip(np.asarray([
        predictions["recent_guarded_v4"][index] for index in wanted
    ]), 1e-9, 1.0 - 1e-9)
    old_loss = -(targets * np.log(guard_old) + (1.0 - targets) * np.log(1.0 - guard_old))
    new_loss = -(targets * np.log(guard_new) + (1.0 - targets) * np.log(1.0 - guard_new))
    guard_gain = old_loss - new_loss
    guard_mean = float(guard_gain.mean())
    guard_se = (
        float(guard_gain.std(ddof=1) / np.sqrt(len(guard_gain)))
        if len(guard_gain) > 1 else None
    )
    guard_lower = guard_mean - 1.96 * guard_se if guard_se is not None else None
    guard_upper = guard_mean + 1.96 * guard_se if guard_se is not None else None
    if guard_lower is not None and guard_lower > 0:
        guard_verdict = "GUARDED_BETTER"
    elif guard_upper is not None and guard_upper < 0:
        guard_verdict = "RAW_BETTER"
    else:
        guard_verdict = "INCONCLUSIVE"
    capped_profiles = {}
    capped_candidates = []
    for alpha in RECENT_LOSS_CONTEXT_GRID_V2:
        name = f"recent_capped_loss_{int(round(alpha * 100)):03d}"
        model = calibrate_family(
            split, family="recent_form", feature_profile=name,
        )
        capped_profiles[name] = model
        validation = model.get("validation", {}).get("model", {})
        capped_candidates.append({
            "profile": name,
            "alpha": alpha,
            "validation_log_loss": validation.get("validation_log_loss"),
            "validation_brier": validation.get("validation_brier"),
        })
    selectable = [
        item for item in capped_candidates
        if item["validation_log_loss"] is not None
    ]
    selected_capped = min(
        selectable,
        key=lambda item: (item["validation_log_loss"], item["alpha"]),
    ) if selectable else None
    capped_comparison: dict[str, Any]
    if selected_capped is None:
        capped_comparison = {
            "status": "INSUFFICIENT_COVERAGE",
            "candidates": capped_candidates,
        }
    else:
        selected_name = selected_capped["profile"]
        selected_prediction = predict_family_equation(
            holdout, _runtime_model(capped_profiles[selected_name]),
        )
        baseline_prediction = predictions["recent_v2"]
        capped_wanted = [
            index for index in range(len(holdout))
            if selected_prediction[index] is not None
            and baseline_prediction[index] is not None
        ]
        capped_targets = np.asarray([
            float(holdout[index]["target_a_win"]) for index in capped_wanted
        ])
        baseline_values = np.asarray([
            baseline_prediction[index] for index in capped_wanted
        ])
        selected_values = np.asarray([
            selected_prediction[index] for index in capped_wanted
        ])
        baseline_metrics = _metrics(
            capped_targets, baseline_values, total_targets=len(holdout),
        )
        selected_metrics = _metrics(
            capped_targets, selected_values, total_targets=len(holdout),
        )
        capped_gain = _paired_probability_gain(
            capped_targets, baseline_values, selected_values,
        )
        capped_comparison = {
            "status": "OBSERVATIONAL_ONLY",
            "selection_partition": "validation",
            "selected_profile": selected_name,
            "selected_alpha": selected_capped["alpha"],
            "candidates": capped_candidates,
            "paired_holdout_targets": len(capped_wanted),
            "baseline_profile": "recent_v2_without_loss_context",
            "baseline_holdout": baseline_metrics,
            "selected_holdout": selected_metrics,
            "paired_gain": capped_gain,
            "selected_model": capped_profiles[selected_name],
            "strong_loss_relief_cannot_cross_zero": True,
            "bad_loss_is_penalty_only": True,
            "promotion_authorized": False,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "status": "OBSERVATIONAL_ONLY",
        "mode": "PAIRED_CHRONOLOGICAL_RECENT_FORM_COMPARISON",
        "split_targets": {name: len(items) for name, items in split.items()},
        "paired_holdout_targets": len(wanted),
        "profiles": profiles,
        "paired_holdout_metrics": paired_metrics,
        "incremental_comparisons": incremental,
        "guarded_comparison": {
            "baseline": "recent_v3",
            "candidate": "recent_guarded_v4",
            "log_loss_gain": round(guard_mean, 6),
            "gain_95pct_ci": (
                None if guard_lower is None else [
                    round(guard_lower, 6), round(guard_upper, 6),
                ]
            ),
            "status": guard_verdict,
            "audit": guarded_audit,
        },
        "capped_loss_context_comparison": capped_comparison,
        "loss_context_promotion_blocked": True,
        "loss_context_requires_asymmetric_guard": True,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def compare_surface_feature_profiles(
    rows: list[dict[str, Any]], *, universe: str,
) -> dict[str, Any]:
    """Compare surface v1 with the no-transition-vote candidate v2."""
    split = _split(rows)
    profile_names = ("legacy_v0", "contextual_v1", "surface_v2", "surface_v3")
    profiles = {
        name: calibrate_family(
            split, family="surface_conditions", feature_profile=name,
        )
        for name in profile_names
    }
    if any(item.get("status") == "INSUFFICIENT_COVERAGE" for item in profiles.values()):
        return {
            "schema_version": SCHEMA_VERSION,
            "universe": str(universe).strip().casefold(),
            "status": "INSUFFICIENT_PAIRED_COVERAGE",
            "profiles": profiles,
            "production_effect": False,
        }
    holdout = split["holdout"]
    predictions = {
        name: predict_family_equation(holdout, _runtime_model(model))
        for name, model in profiles.items()
    }
    wanted = [
        index for index in range(len(holdout))
        if all(predictions[name][index] is not None for name in profile_names)
    ]
    targets = np.asarray([
        float(holdout[index]["target_a_win"]) for index in wanted
    ])
    metrics = {
        name: _metrics(
            targets,
            np.asarray([predictions[name][index] for index in wanted]),
            total_targets=len(holdout),
        )
        for name in profile_names
    }
    paired_v1_v2 = [
        (
            holdout[index], predictions["contextual_v1"][index],
            predictions["surface_v2"][index],
        )
        for index in wanted
    ]
    paired_v2_v3 = [
        (
            holdout[index], predictions["surface_v2"][index],
            predictions["surface_v3"][index],
        )
        for index in wanted
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "status": "POST_AUDIT_EXPLORATORY",
        "mode": "PAIRED_SURFACE_V1_V2_COMPARISON",
        "split_targets": {name: len(items) for name, items in split.items()},
        "paired_holdout_targets": len(wanted),
        "profiles": profiles,
        "paired_holdout_metrics": metrics,
        "v1_to_v2_gain": _paired_probability_gain(
            targets,
            np.asarray([predictions["contextual_v1"][index] for index in wanted]),
            np.asarray([predictions["surface_v2"][index] for index in wanted]),
        ),
        "v2_segment_diagnostics": _paired_diagnostics_by_labels(
            paired_v1_v2, _surface_segment_labels,
        ),
        "v2_to_v3_baseline_only_gain": _paired_probability_gain(
            targets,
            np.asarray([predictions["surface_v2"][index] for index in wanted]),
            np.asarray([predictions["surface_v3"][index] for index in wanted]),
        ),
        "v3_segment_diagnostics": _paired_diagnostics_by_labels(
            paired_v2_v3, _surface_segment_labels,
        ),
        "transition_numeric_vote_v2": False,
        "transition_remains_diagnostic": True,
        "holdout_reused_after_v1_segment_audit": True,
        "future_confirmation_required": True,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def compare_exact_surface_profiles(
    rows: list[dict[str, Any]], *, universe: str,
) -> dict[str, Any]:
    """Compare the four-context career and season candidates pairwise."""
    exact_contexts = {"hard_outdoor", "hard_indoor", "clay", "grass"}
    eligible_rows = [
        row for row in rows
        if row.get("diagnostics", {}).get("surface_context") in exact_contexts
    ]
    split = _split(eligible_rows)
    profile_names = (
        "surface_exact_career_raw",
        "surface_exact_career_previous_raw",
        "surface_exact_career_seasons_raw",
        "surface_exact_career_seasons_shrunk",
    )
    profiles = {
        name: calibrate_family(
            split, family="surface_conditions", feature_profile=name,
        )
        for name in profile_names
    }
    if any(
        item.get("status") == "INSUFFICIENT_COVERAGE"
        for item in profiles.values()
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "universe": str(universe).strip().casefold(),
            "status": "INSUFFICIENT_PAIRED_COVERAGE",
            "profiles": profiles,
            "production_effect": False,
        }
    holdout = split["holdout"]
    predictions = {
        name: predict_family_equation(holdout, _runtime_model(model))
        for name, model in profiles.items()
    }
    wanted = [
        index for index in range(len(holdout))
        if all(predictions[name][index] is not None for name in profile_names)
    ]
    targets = np.asarray([
        float(holdout[index]["target_a_win"]) for index in wanted
    ])
    metrics = {
        name: _metrics(
            targets,
            np.asarray([predictions[name][index] for index in wanted]),
            total_targets=len(holdout),
        )
        for name in profile_names
    }
    incremental = []
    for baseline, candidate in zip(profile_names, profile_names[1:]):
        incremental.append({
            "baseline": baseline,
            "candidate": candidate,
            **_paired_probability_gain(
                targets,
                np.asarray([
                    predictions[baseline][index] for index in wanted
                ]),
                np.asarray([
                    predictions[candidate][index] for index in wanted
                ]),
            ),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "status": "POST_AUDIT_EXPLORATORY",
        "mode": "PAIRED_EXACT_SURFACE_CAREER_SEASON_COMPARISON",
        "split_targets": {name: len(items) for name, items in split.items()},
        "source_targets": len(rows),
        "exact_context_targets": len(eligible_rows),
        "paired_holdout_targets": len(wanted),
        "profiles": profiles,
        "paired_holdout_metrics": metrics,
        "incremental_comparisons": incremental,
        "four_exact_contexts": True,
        "holdout_reused_after_method_design": True,
        "future_confirmation_required": True,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def _paired_probability_gain(
    targets: np.ndarray, baseline: np.ndarray, candidate: np.ndarray,
) -> dict[str, Any]:
    old = np.clip(np.asarray(baseline, dtype=float), 1e-9, 1.0 - 1e-9)
    new = np.clip(np.asarray(candidate, dtype=float), 1e-9, 1.0 - 1e-9)
    truth = np.asarray(targets, dtype=float)
    old_loss = -(truth * np.log(old) + (1.0 - truth) * np.log(1.0 - old))
    new_loss = -(truth * np.log(new) + (1.0 - truth) * np.log(1.0 - new))
    gain = old_loss - new_loss
    mean = float(gain.mean()) if len(gain) else 0.0
    standard_error = (
        float(gain.std(ddof=1) / np.sqrt(len(gain))) if len(gain) > 1 else None
    )
    lower = mean - 1.96 * standard_error if standard_error is not None else None
    upper = mean + 1.96 * standard_error if standard_error is not None else None
    if lower is not None and lower > 0:
        status = "SUPPORTED"
    elif upper is not None and upper < 0:
        status = "REJECTED"
    else:
        status = "INCONCLUSIVE"
    return {
        "log_loss_gain": round(mean, 6),
        "gain_95pct_ci": (
            None if lower is None else [round(lower, 6), round(upper, 6)]
        ),
        "status": status,
    }


def _build_guarded_recent_split(
    split: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Remove result duplication from margin using train-only information."""
    result_key = "contextual_recent_result_core_v1"
    margin_key = "contextual_recent_competitiveness_v1"
    residual_key = "contextual_recent_competitiveness_residual_v2"
    pairs = [
        (float(row["features"][result_key]), float(row["features"][margin_key]))
        for row in split["train"]
        if row.get("features", {}).get(result_key) is not None
        and row.get("features", {}).get(margin_key) is not None
    ]
    if pairs:
        x = np.asarray([item[0] for item in pairs], dtype=float)
        y = np.asarray([item[1] for item in pairs], dtype=float)
        denominator = float(x @ x)
        slope = float((x @ y) / denominator) if denominator > 1e-12 else 0.0
    else:
        slope = 0.0
    guarded: dict[str, list[dict[str, Any]]] = {}
    for part, rows in split.items():
        guarded[part] = []
        for row in rows:
            features = dict(row.get("features", {}))
            result = features.get(result_key)
            margin = features.get(margin_key)
            features[residual_key] = (
                float(margin) - slope * float(result)
                if result is not None and margin is not None else None
            )
            guarded[part].append({**row, "features": features})
    return guarded, {
        "fit_partition": "train_only",
        "intercept_forced_to_zero_for_antisymmetry": True,
        "result_to_margin_slope": round(slope, 8),
        "meaning": "margin component unexplained by win/loss balance",
        "bad_loss_is_penalty_only": True,
        "strong_loss_positive_credit_prohibited": True,
    }
