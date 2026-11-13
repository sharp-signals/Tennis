"""Context-aware hierarchy candidate with primary agreement and H2H trust."""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contextual_family_calibration import DEFAULT_L1_GRID, _metrics, _predict
from .contextual_family_combination_v2 import (
    FAMILY_ORDER,
    PRIMARY_FAMILIES,
    _attach_predictions,
    _effective_profiles,
    _fit_and_evaluate_meta,
    _fit_family_bundle,
    _meta_matrix,
    _select_family_regularisation,
    hierarchy_projector,
    signal_only_projector,
)
from .contextual_family_replay import _split


MODEL_VERSION = "contextual-family-combination-v9-primary-agreement"
META_FAMILIES = (*FAMILY_ORDER, "primary_agreement")


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(value)))


def h2h_sample_reliability(sample: int) -> float:
    """Keep one meeting factual-only and grow trust progressively thereafter."""
    count = max(0, int(sample))
    if count <= 1:
        return 0.0
    return min(1.0, (count - 1.0) / 3.0)


def _primary_agreement_probability(
    probabilities: dict[str, Any], *, threshold: float = 0.0,
) -> float:
    values = []
    for family in PRIMARY_FAMILIES:
        probability = probabilities.get(family)
        if probability is None:
            return 0.5
        values.append(_logit(float(probability)))
    if values[0] == 0.0 or values[1] == 0.0 or values[0] * values[1] <= 0.0:
        return 0.5
    direction = 1.0 if values[0] > 0.0 else -1.0
    excess = max(0.0, min(abs(value) for value in values) - threshold)
    return _sigmoid(direction * excess)


def prepare_contextual_meta_rows(
    rows: list[dict[str, Any]], *, h2h_policy: str = "progressive",
    include_primary_agreement: bool = True,
    primary_agreement_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Apply governed contextual gates before the chronological meta-model."""
    prepared = []
    for row in rows:
        probabilities = dict(row.get("family_probabilities") or {})
        samples = row.get("samples") or {}
        h2h_sample = int(samples.get("h2h") or 0)
        h2h_probability = probabilities.get("matchup_h2h")
        if h2h_policy == "raw":
            reliability = 1.0
        elif h2h_policy == "single_neutral":
            reliability = 0.0 if h2h_sample <= 1 else 1.0
        elif h2h_policy == "progressive":
            reliability = h2h_sample_reliability(h2h_sample)
        else:
            raise ValueError(f"unexpected H2H policy: {h2h_policy}")
        if h2h_probability is not None:
            probabilities["matchup_h2h"] = _sigmoid(
                _logit(float(h2h_probability)) * reliability,
            )
        if include_primary_agreement:
            probabilities["primary_agreement"] = (
                _primary_agreement_probability(
                    probabilities, threshold=primary_agreement_threshold,
                )
            )
        states = dict(row.get("family_states") or {})
        if include_primary_agreement:
            states["primary_agreement"] = {
                "data_state": "OBSERVED",
                "signal_state": "AVAILABLE",
            }
        prepared.append({
            **row,
            "family_probabilities": probabilities,
            "family_states": states,
            "combination_context_v9": {
                "h2h_sample": h2h_sample,
                "h2h_reliability": round(reliability, 6),
                "primary_agreement_probability": (
                    round(probabilities["primary_agreement"], 6)
                    if include_primary_agreement else None
                ),
            },
        })
    return prepared


def hierarchy_v9_projector(columns: list[str]):
    """Preserve the family hierarchy and bound the agreement interaction."""
    base_project = hierarchy_projector(columns)
    agreement_index = columns.index("primary_agreement__logit")
    recent_index = columns.index("recent_form__logit")
    structural_index = columns.index("structural_strength__logit")

    def project(weights: np.ndarray) -> np.ndarray:
        result = base_project(weights)
        result[agreement_index] = min(
            max(0.0, float(result[agreement_index])),
            float(result[recent_index]),
            float(result[structural_index]),
        )
        return result

    return project


def combine_contextual_families_v9(
    rows: list[dict[str, Any]], *, universe: str,
    l1_grid: Iterable[float] = DEFAULT_L1_GRID,
    include_diagnostics: bool = False,
    h2h_policy: str = "progressive",
    include_primary_agreement: bool = True,
    primary_agreement_threshold: float = 0.0,
) -> dict[str, Any]:
    """Fit the candidate strictly on chronological development/holdout data."""
    universe = str(universe).casefold()
    split = _split(rows)
    if min(len(part) for part in split.values()) == 0:
        return {"status": "INSUFFICIENT_CHRONOLOGY", "universe": universe}
    profiles = _effective_profiles(universe, {
        "recent_form": "recent_tier_context_v8",
        "structural_strength": "contextual_v7",
        "surface_conditions": "surface_exact_tier_adjusted_v8",
    })
    family_l1 = _select_family_regularisation(
        split["train"], universe=universe, profiles=profiles,
    )
    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=family_l1, profiles=profiles,
    )
    development_meta = prepare_contextual_meta_rows(
        _attach_predictions(split["validation"], train_models, universe=universe),
        h2h_policy=h2h_policy,
        include_primary_agreement=include_primary_agreement,
        primary_agreement_threshold=primary_agreement_threshold,
    )
    development = split["train"] + split["validation"]
    final_models = _fit_family_bundle(
        development, universe=universe,
        selected_l1=family_l1, profiles=profiles,
    )
    holdout = prepare_contextual_meta_rows(
        _attach_predictions(split["holdout"], final_models, universe=universe),
        h2h_policy=h2h_policy,
        include_primary_agreement=include_primary_agreement,
        primary_agreement_threshold=primary_agreement_threshold,
    )
    meta_families = META_FAMILIES if include_primary_agreement else FAMILY_ORDER
    projector = (
        hierarchy_v9_projector
        if include_primary_agreement else hierarchy_projector
    )
    candidate = _fit_and_evaluate_meta(
        development_meta, holdout, l1_grid=l1_grid,
        families=meta_families,
        projector_factory=projector,
    )
    primary_only = _fit_and_evaluate_meta(
        development_meta, holdout, l1_grid=l1_grid,
        families=PRIMARY_FAMILIES,
        projector_factory=signal_only_projector,
    )
    coefficients = dict(candidate["coefficients"])
    family_coefficients = {
        family: coefficients[f"{family}__logit"]
        for family in meta_families
    }
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline_rate = float(np.mean([
        1.0 if row["target_a_win"] else 0.0 for row in development_meta
    ]))
    baseline = _metrics(
        targets, np.full(len(targets), baseline_rate),
        total_targets=len(holdout),
    )
    result = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "universe": universe,
        "status": "CANDIDATE_FITTED",
        "mode": "CONTEXT_GATED_CHRONOLOGICAL_STACK",
        "h2h_policy": h2h_policy,
        "include_primary_agreement": include_primary_agreement,
        "primary_agreement_threshold": primary_agreement_threshold,
        "family_profiles": profiles,
        "family_l1_selected_inside_train": family_l1,
        "meta_l1_selected_inside_validation": candidate["selected_l1"],
        "meta_candidates": candidate["candidates"],
        "intercept": candidate["intercept"],
        "coefficients": coefficients,
        "family_coefficients": family_coefficients,
        "runtime_family_models": final_models,
        "hierarchy": {
            "primary": list(PRIMARY_FAMILIES),
            "primary_agreement_role": (
                "BOUNDED_CONTEXTUAL_INTERACTION"
                if include_primary_agreement else "DISABLED_FOR_ABLATION"
            ),
            "primary_agreement_not_above_each_primary": (
                all((
                family_coefficients["primary_agreement"]
                <= family_coefficients[name] + 1e-9
                for name in PRIMARY_FAMILIES
                )) if include_primary_agreement else None
            ),
            "h2h_role": h2h_policy,
            "single_h2h_directional_vote": h2h_policy == "raw",
        },
        "holdout": {
            "combined": candidate["metrics"],
            "primary_only": primary_only["metrics"],
            "intercept_only_baseline": baseline,
            "gain_vs_baseline": round(
                baseline["log_loss"] - candidate["metrics"]["log_loss"], 6,
            ),
        },
        "decision_gate": {
            "beats_primary_only": (
                candidate["metrics"]["log_loss"]
                < primary_only["metrics"]["log_loss"]
            ),
            "beats_intercept_only": (
                candidate["metrics"]["log_loss"] < baseline["log_loss"]
            ),
            "primary_agreement_fitted_not_fixed": include_primary_agreement,
            "single_h2h_is_factual_only": h2h_policy != "raw",
            "market_independent": True,
            "production_unchanged": True,
        },
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }
    if include_diagnostics:
        result["_diagnostics"] = {
            "holdout_rows": holdout,
            "holdout_probabilities": candidate["_probabilities"],
        }
    return result


def validate_combination_v9_contract(contract: dict[str, Any]) -> None:
    if contract.get("model_version") != MODEL_VERSION:
        raise ValueError("unexpected contextual combination v9 model version")
    if contract.get("mode") != "SHADOW_ONLY":
        raise ValueError("combination v9 contract must remain SHADOW_ONLY")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "promotion_authorized",
    )):
        raise ValueError("combination v9 isolation invariant failed")


def predict_contextual_combination_v9(
    rows: list[dict[str, Any]], *, universe: str, contract: dict[str, Any],
) -> dict[str, Any]:
    validate_combination_v9_contract(contract)
    universe = str(universe).casefold()
    model = contract.get("universes", {}).get(universe)
    if not isinstance(model, dict):
        raise ValueError(f"combination v9 missing universe: {universe}")
    include_agreement = bool(model.get("include_primary_agreement", True))
    attached = prepare_contextual_meta_rows(
        _attach_predictions(
            rows, model["runtime_family_models"], universe=universe,
        ),
        h2h_policy=str(model.get("h2h_policy") or "progressive"),
        include_primary_agreement=include_agreement,
        primary_agreement_threshold=float(
            model.get("primary_agreement_threshold") or 0.0,
        ),
    )
    meta_families = META_FAMILIES if include_agreement else FAMILY_ORDER
    x, _, columns, _ = _meta_matrix(attached, families=meta_families)
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
