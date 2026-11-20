"""Order-invariant pricing with governed recent-form semantics v17."""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from .contextual_family_combination_v2 import _attach_predictions
from .contextual_family_calibration import explain_family_equation
from .contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    SECONDARY_FAMILIES,
    govern_consensus_with_individual_cap,
    govern_ordered_family_contributions,
)


MODEL_VERSION = "contextual-family-combination-v17-recent-form-governance"
FAMILY_ORDER = (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
RECENT_RESULT_KEY = "contextual_recent_result_main_v7"
RECENT_MODIFIER_KEYS = frozenset({
    "contextual_recent_win_quality_v1",
    "contextual_recent_tier_win_credit_v7",
    "contextual_recent_circuit_downshift_v8",
})


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def mirror_contextual_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror directional margins while preserving missingness and context.

    Replay features are defined as player-A minus player-B quantities.  Their
    sign must therefore reverse when the players are exchanged.  Samples and
    categorical context describe evidence availability and remain unchanged.
    """
    mirrored = copy.deepcopy(dict(row))
    mirrored["features"] = {
        key: (
            -float(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else value
        )
        for key, value in dict(row.get("features") or {}).items()
    }
    if "target_a_win" in mirrored:
        mirrored["target_a_win"] = not bool(mirrored["target_a_win"])
    return mirrored


def validate_combination_v17_contract(contract: dict[str, Any]) -> None:
    if contract.get("model_version") != MODEL_VERSION:
        raise ValueError("unexpected contextual combination v17 model version")
    if contract.get("mode") != "SHADOW_ONLY":
        raise ValueError("combination v17 contract must remain SHADOW_ONLY")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "promotion_authorized",
    )):
        raise ValueError("combination v17 isolation invariant failed")


def explain_symmetric_family_equation(
    row: dict[str, Any], model: dict[str, Any],
) -> dict[str, Any]:
    """Explain the same paired antisymmetric signal used by v17 pricing."""
    direct = explain_family_equation(row, model)
    reverse = explain_family_equation(mirror_contextual_row(row), model)
    if direct.get("status") != "READY" or reverse.get("status") != "READY":
        return {"status": "UNAVAILABLE", "features": []}
    reverse_by_key = {item["key"]: item for item in reverse["features"]}
    features = []
    for item in direct["features"]:
        opposite = reverse_by_key[item["key"]]
        features.append({
            **item,
            "standardized_value": round(0.5 * (
                float(item["standardized_value"])
                - float(opposite["standardized_value"])
            ), 8),
            "logit_contribution": round(0.5 * (
                float(item["logit_contribution"])
                - float(opposite["logit_contribution"])
            ), 8),
            "missing_logit_contribution": round(0.5 * (
                float(item["missing_logit_contribution"])
                - float(opposite["missing_logit_contribution"])
            ), 8),
        })
    return {
        **direct,
        "intercept": 0.0,
        "features": features,
        "orientation_policy": "PAIRED_DIRECTIONAL_ANTISYMMETRY",
    }


def govern_recent_form_signal(
    row: dict[str, Any], model: dict[str, Any], *, result_weight_floor: float,
    opposing_modifier_cap: float,
) -> tuple[float | None, dict[str, Any]]:
    """Keep recent results as the base and quality/tier as modifiers.

    The fitted family remains the statistical source.  Governance only repairs
    the semantic failure where regularisation zeroes the direct result factor
    and allows contextual modifiers to reverse a material recent-form base.
    """
    explanation = explain_symmetric_family_equation(row, model)
    if explanation.get("status") != "READY":
        return None, {"status": "UNAVAILABLE"}
    base = 0.0
    modifiers = 0.0
    result_floor_applied = False
    fitted_result_contribution = 0.0
    effective_result_contribution = 0.0
    for item in explanation["features"]:
        key = str(item["key"])
        contribution = (
            float(item["logit_contribution"])
            + float(item["missing_logit_contribution"])
        )
        if key == RECENT_RESULT_KEY:
            fitted_result_contribution = contribution
            fitted_weight = float(item.get("coefficient", 0.0))
            if fitted_weight < result_weight_floor:
                contribution = (
                    float(result_weight_floor)
                    * float(item["standardized_value"])
                )
                result_floor_applied = True
            effective_result_contribution = contribution
        if key in RECENT_MODIFIER_KEYS:
            modifiers += contribution
        else:
            base += contribution
    governed_modifiers = modifiers
    if base * modifiers < 0.0:
        governed_modifiers = math.copysign(
            min(abs(modifiers), opposing_modifier_cap * abs(base)), modifiers,
        )
    signal = base + governed_modifiers
    return signal, {
        "status": "READY",
        "policy": "RESULTS_AND_COMPETITIVENESS_BASE_CONTEXT_AS_MODIFIER",
        "base_logit": base,
        "modifier_logit_before_governance": modifiers,
        "modifier_logit_after_governance": governed_modifiers,
        "result_weight_floor": result_weight_floor,
        "result_floor_applied": result_floor_applied,
        "result_logit_before_floor": fitted_result_contribution,
        "result_logit_after_floor": effective_result_contribution,
        "opposing_modifier_cap": opposing_modifier_cap,
        "direction_reversed_by_modifiers": (
            base != 0.0 and signal != 0.0 and base * signal < 0.0
        ),
    }


def predict_contextual_combination_v17(
    rows: list[dict[str, Any]], *, universe: str, contract: dict[str, Any],
) -> dict[str, Any]:
    """Predict with exact A/B invariance and an explicit realised hierarchy."""
    validate_combination_v17_contract(contract)
    universe = str(universe).casefold()
    model = contract.get("universes", {}).get(universe)
    if not isinstance(model, dict):
        raise ValueError(f"combination v17 missing universe: {universe}")
    calibration = model["realized_hierarchy"]["post_hierarchy_calibration"]
    if abs(float(calibration.get("intercept", 0.0))) > 1e-12:
        raise ValueError("combination v17 calibration intercept must be zero")

    attached = _attach_predictions(
        rows, model["runtime_family_models"], universe=universe,
    )
    mirrored = _attach_predictions(
        [mirror_contextual_row(row) for row in rows],
        model["runtime_family_models"], universe=universe,
    )
    h2h_multiplier = float(model["realized_hierarchy"].get("h2h_multiplier", 1.0))
    recent_governance = model["realized_hierarchy"]["recent_form_governance"]
    probabilities = []
    for row, mirror in zip(attached, mirrored, strict=True):
        family_signals = {}
        for family in FAMILY_ORDER:
            original_probability = row["family_probabilities"].get(family)
            mirror_probability = mirror["family_probabilities"].get(family)
            if original_probability is None or mirror_probability is None:
                family_signals[family] = None
                continue
            family_signals[family] = 0.5 * (
                _logit(original_probability) - _logit(mirror_probability)
            )
        if family_signals["recent_form"] is None:
            recent_audit = {"status": "UNAVAILABLE", "absence_votes": False}
        else:
            recent_signal, recent_audit = govern_recent_form_signal(
                row, model["runtime_family_models"]["recent_form"],
                result_weight_floor=float(
                    recent_governance["result_weight_floor"]
                ),
                opposing_modifier_cap=float(
                    recent_governance["opposing_modifier_cap"]
                ),
            )
            family_signals["recent_form"] = recent_signal
        row["family_probabilities"] = {
            family: (
                _sigmoid(signal) if signal is not None else None
            )
            for family, signal in family_signals.items()
        }
        raw = {
            family: (
                float(model["family_coefficients"].get(family, 0.0))
                * float(family_signals[family])
                * (h2h_multiplier if family == "matchup_h2h" else 1.0)
                if family_signals[family] is not None else 0.0
            )
            for family in FAMILY_ORDER
        }
        directions = {
            1 if value > 0.0 else -1 if value < 0.0 else 0
            for value in raw.values()
        }
        unanimous = len(directions - {0}) == 1
        if unanimous:
            governed, audit = govern_consensus_with_individual_cap(
                raw, consensus_cap_basis="strongest_primary",
            )
        else:
            governed, audit = govern_ordered_family_contributions(raw)
        final_logit = float(calibration["slope"]) * sum(governed.values())
        row["pre_hierarchy_family_contributions"] = raw
        row["realized_family_contributions"] = governed
        row["calibrated_realized_family_contributions"] = {
            family: float(calibration["slope"]) * contribution
            for family, contribution in governed.items()
        }
        row["realized_hierarchy_audit"] = {
            **audit,
            "hierarchy_contract": "ORDER_INVARIANT_REALIZED_HIERARCHY",
            "missingness_policy": "ABSENCE_NEVER_VOTES",
            "h2h_multiplier": h2h_multiplier,
            "recent_form_governance": recent_audit,
            "unanimous_reinforcement_preserved": unanimous,
        }
        row["orientation_audit"] = {
            "policy": "PAIRED_DIRECTIONAL_ANTISYMMETRY",
            "alphabetical_order_votes": False,
            "neutral_probability": 0.5,
        }
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
