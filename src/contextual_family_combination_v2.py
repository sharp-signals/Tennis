"""Hierarchy-constrained combination of the approved contextual families."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contextual_family_calibration import (
    DEFAULT_L1_GRID,
    _fit_logistic_elastic_net,
    _metrics,
    _predict,
    calibrate_family,
    fit_family_equation,
    predict_family_equation,
)
from .contextual_family_replay import _split


SCHEMA_VERSION = 1
FAMILY_ORDER = (
    "recent_form",
    "structural_strength",
    "surface_conditions",
    "matchup_h2h",
    "serve_return",
)
PRIMARY_FAMILIES = ("recent_form", "structural_strength")
SURFACE_CONTEXTS = ("hard_outdoor", "hard_indoor", "clay", "grass")
PROFILES = {
    "recent_form": "recent_v2",
    "structural_strength": "legacy_v0",
    "surface_conditions": "surface_exact_career_seasons_shrunk",
    "matchup_h2h": "h2h_global_shrunk_v1",
}


def _serve_profile(universe: str) -> str:
    return (
        "serve_return_points_recent_deviation_v1"
        if universe == "atp"
        else "serve_return_surface_points_shrunk_v1"
    )


def _logit(probability: float) -> float:
    p = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _surface_context(row: dict[str, Any]) -> str | None:
    value = row.get("diagnostics", {}).get("surface_context")
    return value if value in SURFACE_CONTEXTS else None


def _surface_vote_enabled(universe: str, context: str | None) -> bool:
    return context in SURFACE_CONTEXTS and not (
        universe == "wta" and context == "hard_indoor"
    )


def _select_l1(
    rows: list[dict[str, Any]], family: str, profile: str,
) -> float:
    result = calibrate_family(
        _split(rows), family=family, feature_profile=profile,
    )
    return float(result.get("selected_l1_on_validation", 0.1))


def _fit_family_bundle(
    rows: list[dict[str, Any]],
    *,
    universe: str,
    selected_l1: dict[str, Any],
) -> dict[str, Any]:
    models = {}
    for family in ("recent_form", "structural_strength", "matchup_h2h"):
        models[family] = fit_family_equation(
            rows,
            family=family,
            feature_profile=PROFILES[family],
            l1=float(selected_l1[family]),
        )
    models["serve_return"] = fit_family_equation(
        rows,
        family="serve_return",
        feature_profile=_serve_profile(universe),
        l1=float(selected_l1["serve_return"]),
    )
    models["surface_conditions"] = {
        context: fit_family_equation(
            [row for row in rows if _surface_context(row) == context],
            family="surface_conditions",
            feature_profile=PROFILES["surface_conditions"],
            l1=float(selected_l1["surface_conditions"].get(context, 0.1)),
        )
        for context in SURFACE_CONTEXTS
        if _surface_vote_enabled(universe, context)
    }
    return models


def _select_family_regularisation(
    rows: list[dict[str, Any]], *, universe: str,
) -> dict[str, Any]:
    selected = {
        family: _select_l1(rows, family, PROFILES[family])
        for family in ("recent_form", "structural_strength", "matchup_h2h")
    }
    selected["serve_return"] = _select_l1(
        rows, "serve_return", _serve_profile(universe),
    )
    selected["surface_conditions"] = {
        context: _select_l1(
            [row for row in rows if _surface_context(row) == context],
            "surface_conditions",
            PROFILES["surface_conditions"],
        )
        for context in SURFACE_CONTEXTS
        if _surface_vote_enabled(universe, context)
        and [row for row in rows if _surface_context(row) == context]
    }
    return selected


def _attach_predictions(
    rows: list[dict[str, Any]],
    models: dict[str, Any],
    *,
    universe: str,
) -> list[dict[str, Any]]:
    probabilities = {
        family: predict_family_equation(rows, models[family])
        for family in (
            "recent_form", "structural_strength", "matchup_h2h", "serve_return",
        )
    }
    surface_predictions: dict[str, list[float | None]] = {
        context: predict_family_equation(rows, model)
        for context, model in models["surface_conditions"].items()
    }
    result = []
    for index, row in enumerate(rows):
        context = _surface_context(row)
        surface_probability = None
        if _surface_vote_enabled(universe, context):
            surface_probability = surface_predictions.get(context, [None] * len(rows))[index]
        result.append({
            **row,
            "family_probabilities": {
                **{family: values[index] for family, values in probabilities.items()},
                "surface_conditions": surface_probability,
            },
            "family_numeric_states": {
                "surface_conditions": (
                    "OBSERVED" if surface_probability is not None
                    else "DIAGNOSTIC_ONLY" if context == "hard_indoor" and universe == "wta"
                    else "UNAVAILABLE"
                ),
            },
        })
    return result


def _meta_matrix(
    rows: list[dict[str, Any]],
    *,
    families: tuple[str, ...] = FAMILY_ORDER,
) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    columns = []
    for family in families:
        columns.extend([
            f"{family}__logit",
            f"{family}__unavailable",
            f"{family}__observed_none",
        ])
    data = []
    for row in rows:
        values = []
        states = row.get("family_states", {})
        for family in families:
            probability = row.get("family_probabilities", {}).get(family)
            state = states.get(family, {}).get("data_state")
            observed_none = state == "OBSERVED_NONE"
            values.extend([
                _logit(probability) if probability is not None else 0.0,
                1.0 if probability is None and not observed_none else 0.0,
                1.0 if observed_none else 0.0,
            ])
        data.append(values)
    x = np.asarray(data, dtype=float)
    y = np.asarray([1.0 if row["target_a_win"] else 0.0 for row in rows])
    nonnegative = np.asarray([name.endswith("__logit") for name in columns])
    return x, y, columns, nonnegative


def hierarchy_projector(columns: list[str]):
    """Project family coefficients into the approved ordinal hierarchy.

    The constraints have no hand-picked percentage weights: modifier capacity
    is derived from the fitted primary-family mass.
    """
    indexes = {family: columns.index(f"{family}__logit") for family in FAMILY_ORDER}

    def project(weights: np.ndarray) -> np.ndarray:
        result = signal_only_projector(columns)(weights)
        values = {
            family: max(0.0, float(result[index]))
            for family, index in indexes.items()
        }
        primary_total = values["recent_form"] + values["structural_strength"]
        values["surface_conditions"] = min(
            values["surface_conditions"], primary_total / 2.0,
        )
        values["matchup_h2h"] = min(
            values["matchup_h2h"], values["surface_conditions"],
        )
        values["serve_return"] = min(
            values["serve_return"], values["matchup_h2h"],
        )
        modifier_total = sum(values[family] for family in FAMILY_ORDER[2:])
        if modifier_total > primary_total > 0:
            scale = primary_total / modifier_total
            for family in FAMILY_ORDER[2:]:
                values[family] *= scale
        if primary_total <= 0:
            for family in FAMILY_ORDER[2:]:
                values[family] = 0.0
        for family, index in indexes.items():
            result[index] = values[family]
        return result

    return project


def signal_only_projector(columns: list[str]):
    """Keep availability states auditable but out of the central estimate."""
    non_signal = np.asarray([
        not name.endswith("__logit") for name in columns
    ])

    def project(weights: np.ndarray) -> np.ndarray:
        result = np.asarray(weights, dtype=float).copy()
        result[non_signal] = 0.0
        return result

    return project


def _fit_meta_candidates(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    l1_grid: Iterable[float],
    *,
    families: tuple[str, ...] = FAMILY_ORDER,
    projector=None,
) -> tuple[list[dict[str, Any]], float]:
    x_train, y_train, columns, nonnegative = _meta_matrix(
        train, families=families,
    )
    x_validation, y_validation, validation_columns, _ = _meta_matrix(
        validation, families=families,
    )
    if columns != validation_columns:
        raise ValueError("meta columns mismatch")
    candidates = []
    for l1 in tuple(float(value) for value in l1_grid):
        intercept, weights, iterations = _fit_logistic_elastic_net(
            x_train,
            y_train,
            l1=l1,
            nonnegative_mask=nonnegative,
            weight_projector=projector,
        )
        metrics = _metrics(
            y_validation,
            _predict(x_validation, intercept, weights),
            total_targets=len(validation),
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
            item["validation_log_loss"],
            item["nonzero_coefficients"],
            -item["l1"],
        ),
    )
    return candidates, float(selected["l1"])


def _fit_and_evaluate_meta(
    development: list[dict[str, Any]],
    holdout: list[dict[str, Any]],
    *,
    l1_grid: Iterable[float],
    families: tuple[str, ...] = FAMILY_ORDER,
    projector_factory=None,
) -> dict[str, Any]:
    meta_split = _split(development)
    meta_validation = meta_split["validation"] or meta_split["holdout"]
    probe_columns = _meta_matrix(
        meta_split["train"], families=families,
    )[2]
    projector = (
        projector_factory(probe_columns) if projector_factory else None
    )
    candidates, selected_l1 = _fit_meta_candidates(
        meta_split["train"],
        meta_validation,
        l1_grid,
        families=families,
        projector=projector,
    )
    x_development, y_development, columns, nonnegative = _meta_matrix(
        development, families=families,
    )
    projector = projector_factory(columns) if projector_factory else None
    intercept, weights, iterations = _fit_logistic_elastic_net(
        x_development,
        y_development,
        l1=selected_l1,
        nonnegative_mask=nonnegative,
        weight_projector=projector,
    )
    x_holdout, y_holdout, holdout_columns, _ = _meta_matrix(
        holdout, families=families,
    )
    if columns != holdout_columns:
        raise ValueError("holdout meta columns mismatch")
    probabilities = _predict(x_holdout, intercept, weights)
    return {
        "selected_l1": selected_l1,
        "candidates": candidates,
        "intercept": round(float(intercept), 8),
        "coefficients": {
            name: round(float(value), 8)
            for name, value in zip(columns, weights)
        },
        "metrics": _metrics(
            y_holdout, probabilities, total_targets=len(holdout),
        ),
        "_probabilities": [float(value) for value in probabilities],
        "iterations": iterations,
    }


def combine_contextual_families_v2(
    rows: list[dict[str, Any]],
    *,
    universe: str,
    l1_grid: Iterable[float] = DEFAULT_L1_GRID,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    universe = str(universe).casefold()
    split = _split(rows)
    if min(len(part) for part in split.values()) == 0:
        return {"status": "INSUFFICIENT_CHRONOLOGY", "universe": universe}

    family_l1 = _select_family_regularisation(split["train"], universe=universe)
    train_models = _fit_family_bundle(
        split["train"], universe=universe, selected_l1=family_l1,
    )
    development_meta = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    development = split["train"] + split["validation"]
    final_models = _fit_family_bundle(
        development, universe=universe, selected_l1=family_l1,
    )
    holdout = _attach_predictions(
        split["holdout"], final_models, universe=universe,
    )
    hierarchical = _fit_and_evaluate_meta(
        development_meta,
        holdout,
        l1_grid=l1_grid,
        projector_factory=hierarchy_projector,
    )
    primary_only = _fit_and_evaluate_meta(
        development_meta,
        holdout,
        l1_grid=l1_grid,
        families=PRIMARY_FAMILIES,
        projector_factory=signal_only_projector,
    )
    unconstrained = _fit_and_evaluate_meta(
        development_meta,
        holdout,
        l1_grid=l1_grid,
        projector_factory=signal_only_projector,
    )
    model_metrics = hierarchical["metrics"]
    columns = list(hierarchical["coefficients"])
    weights = np.asarray([
        hierarchical["coefficients"][name] for name in columns
    ])
    intercept = hierarchical["intercept"]
    selected_l1 = hierarchical["selected_l1"]
    candidates = hierarchical["candidates"]
    iterations = hierarchical["iterations"]
    y_holdout = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    y_development = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in development_meta
    ])
    base_rate = float(np.mean(y_development))
    baseline = _metrics(
        y_holdout,
        np.full(len(y_holdout), base_rate),
        total_targets=len(holdout),
    )
    coefficients = {
        name: round(float(value), 8)
        for name, value in zip(columns, weights)
    }
    family_coefficients = {
        family: coefficients[f"{family}__logit"] for family in FAMILY_ORDER
    }
    primary_total = sum(family_coefficients[name] for name in PRIMARY_FAMILIES)
    modifier_total = sum(family_coefficients[name] for name in FAMILY_ORDER[2:])
    result = {
        "schema_version": SCHEMA_VERSION,
        "model_version": "contextual-family-combination-v2-hierarchical",
        "universe": universe,
        "status": (
            "HIERARCHY_SUPPORTED"
            if model_metrics["log_loss"]
            < primary_only["metrics"]["log_loss"]
            else "HIERARCHY_NOT_SUPPORTED"
        ),
        "mode": "HIERARCHY_CONSTRAINED_OUT_OF_SAMPLE_STACK",
        "family_profiles": {
            **PROFILES,
            "serve_return": _serve_profile(universe),
        },
        "family_l1_selected_inside_train": family_l1,
        "meta_l1_selected_inside_validation": selected_l1,
        "meta_candidates": candidates,
        "intercept": round(float(intercept), 8),
        "coefficients": coefficients,
        "family_coefficients": family_coefficients,
        "hierarchy": {
            "primary": list(PRIMARY_FAMILIES),
            "surface_role": "CONTEXTUAL_AMPLIFIER",
            "h2h_role": "BOUNDED_OPTIONAL_MODIFIER",
            "serve_return_role": "SECONDARY_BOUNDED_MODIFIER",
            "primary_total": round(primary_total, 8),
            "modifier_total": round(modifier_total, 8),
            "modifier_total_not_above_primary_total": modifier_total <= primary_total + 1e-9,
            "surface_not_above_primary_average": (
                family_coefficients["surface_conditions"]
                <= primary_total / 2.0 + 1e-9
            ),
            "h2h_not_above_surface": (
                family_coefficients["matchup_h2h"]
                <= family_coefficients["surface_conditions"] + 1e-9
            ),
            "serve_not_above_h2h": (
                family_coefficients["serve_return"]
                <= family_coefficients["matchup_h2h"] + 1e-9
            ),
        },
        "runtime_family_models": final_models,
        "holdout": {
            "combined": model_metrics,
            "primary_only": primary_only["metrics"],
            "unconstrained_nonnegative": unconstrained["metrics"],
            "intercept_only_baseline": baseline,
            "gain_vs_baseline": round(
                baseline["log_loss"] - model_metrics["log_loss"], 6,
            ),
            "gain_vs_primary_only": round(
                primary_only["metrics"]["log_loss"]
                - model_metrics["log_loss"],
                6,
            ),
            "cost_vs_unconstrained": round(
                model_metrics["log_loss"]
                - unconstrained["metrics"]["log_loss"],
                6,
            ),
        },
        "decision_gate": {
            "beats_primary_only": (
                model_metrics["log_loss"]
                < primary_only["metrics"]["log_loss"]
            ),
            "beats_intercept_only": (
                model_metrics["log_loss"] < baseline["log_loss"]
            ),
            "missingness_contribution_is_zero": all(
                abs(value) <= 1e-12
                for name, value in coefficients.items()
                if not name.endswith("__logit")
            ),
            "market_independent": True,
            "production_unchanged": True,
        },
        "uncertainty_calibration_pending": True,
        "fair_odd_fitted": False,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "iterations_final": iterations,
    }
    if include_diagnostics:
        result["_diagnostics"] = {
            "holdout_rows": holdout,
            "holdout_probabilities": hierarchical["_probabilities"],
        }
    return result
