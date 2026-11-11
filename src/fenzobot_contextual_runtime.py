"""Market-free prospective runtime for the globally named contextual release."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .contextual_family_combination_v2 import FAMILY_ORDER
from .contextual_family_combination_v8 import predict_contextual_combination_v8
from .contextual_family_calibration import explain_family_equation
from .contextual_family_methodology import family_methodology
from .contextual_factor_orchestrator import FAMILY_DEFINITIONS
from .contextual_probability_uncertainty_v2 import (
    MIN_BIN_SAMPLE,
    _apply_calibrator,
    _fair_odd,
    _family_available,
    _lookup_interval,
    _quality_group,
)


GLOBAL_RELEASE_ID = "FENZOBOT_CONTEXTUAL_2026_11"
RELEASE_SLUG = "fenzobot-contextual-2026-11"
DEFAULT_MODEL_PATH = Path("data/models/fenzobot-contextual-2026-11.json")

DEPENDENCE_MATERIAL_FAVORITE = 0.55
DEPENDENCE_CRITICAL_FAVORITE = 0.60
DEPENDENCE_MATERIAL_DELTA_PP = 10.0
DEPENDENCE_CRITICAL_DELTA_PP = 15.0


def _coverage_grade(data_state: str | None, probability: float | None) -> str:
    """Separate researched neutrality, partial evidence and true availability."""
    state = str(data_state or "MISSING_DATA").upper()
    if state == "OBSERVED_NONE":
        return "OBSERVED_NEUTRAL"
    if probability is None:
        return "UNAVAILABLE"
    if state == "OBSERVED":
        return "SOLID"
    if state == "INSUFFICIENT_SAMPLE":
        return "PARTIAL"
    return "UNAVAILABLE"


def _impact_intensity(delta_pp: float) -> str:
    value = abs(float(delta_pp))
    if value < 3.0:
        return "SLIGHT"
    if value < 7.0:
        return "MODERATE"
    if value < 12.0:
        return "STRONG"
    return "DECISIVE"


def _dependency_grade(
    *, full_probability: float, without_probability: float, central_side: str,
) -> str:
    """Grade a favorite flip instead of treating every flip as a fatal error."""
    flipped = (
        without_probability <= 0.5 if central_side == "a"
        else without_probability >= 0.5
    )
    if not flipped:
        return "ROBUST"
    favorite_probability = (
        full_probability if central_side == "a" else 1.0 - full_probability
    )
    delta_pp = 100.0 * abs(full_probability - without_probability)
    if (
        favorite_probability >= DEPENDENCE_CRITICAL_FAVORITE
        or delta_pp >= DEPENDENCE_CRITICAL_DELTA_PP
    ):
        return "CRITICAL_DEPENDENCE"
    if (
        favorite_probability >= DEPENDENCE_MATERIAL_FAVORITE
        or delta_pp >= DEPENDENCE_MATERIAL_DELTA_PP
    ):
        return "MATERIAL_DEPENDENCE"
    return "BALANCED_SENSITIVE"


def _family_lead_authority(
    family_row: Mapping[str, Any], *, contribution: float,
) -> dict[str, Any]:
    """Decide whether one *primary* family may legitimately lead.

    A family is not authorised merely because it is numerically strong.  It
    must be primary, solid and supported by at least two active internal
    components pointing mostly in the same direction.  This keeps secondary,
    partial and internally contradictory evidence fail-closed.
    """
    key = str(family_row.get("key") or "")
    methodology = family_methodology(key)
    features = (family_row.get("internal_trace") or {}).get("features") or []
    active = [
        item for item in features
        if not item.get("missing")
        and abs(float(item.get("logit_contribution") or 0.0)) > 1e-9
    ]
    direction = 1 if contribution > 0 else -1 if contribution < 0 else 0
    aligned = sum(
        1 for item in active
        if (1 if float(item.get("logit_contribution") or 0.0) > 0 else -1)
        == direction
    )
    agreement = aligned / len(active) if active else 0.0
    authorised = bool(
        methodology["role"] in {"PRIMARY", "PRIMARY_CONTEXT"}
        and methodology["can_lead"]
        and family_row.get("coverage_grade") == "SOLID"
        and len(active) >= 2
        and agreement >= 2.0 / 3.0
    )
    return {
        "authorised": authorised,
        "role": methodology["role"],
        "role_label": methodology["role_label"],
        "coverage_grade": family_row.get("coverage_grade"),
        "active_components": len(active),
        "aligned_components": aligned,
        "directional_agreement": round(agreement, 4),
    }


@lru_cache(maxsize=4)
def load_contract(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("global_release_id") != GLOBAL_RELEASE_ID
        or value.get("release_slug") != RELEASE_SLUG
        or value.get("mode") != "PROSPECTIVE_SHADOW_ONLY"
        or value.get("market_used_for_prediction") is not False
        or value.get("production_effect") is not False
        or value.get("promotion_authorized") is not False
        or set(value.get("universes") or {}) != {"atp", "wta"}
    ):
        raise ValueError("invalid global Fenzobot contextual release")
    return value


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(value)))


def _centred_empirical_interval(
    probability: float, bin_item: Mapping[str, Any],
    global_bin: Mapping[str, Any], *, quality_group: str,
    sensitivity_probabilities: list[float],
) -> tuple[float, float]:
    """Centre empirical uncertainty on the actual prediction.

    Wilson width is learned from chronological calibration cohorts.  It is a
    width, not a second point prediction.  Leave-one-family-out probabilities
    widen the range when the result depends materially on one family.
    """
    widths = [float(bin_item["wilson_upper"]) - float(bin_item["wilson_lower"])]
    if quality_group != "PRIMARY_READY_COMPLETE":
        widths.append(
            float(global_bin["wilson_upper"]) - float(global_bin["wilson_lower"])
        )
    half_width = max(widths) / 2.0
    lower = probability - half_width
    upper = probability + half_width
    if sensitivity_probabilities:
        lower = min(lower, *sensitivity_probabilities)
        upper = max(upper, *sensitivity_probabilities)
    return max(1e-6, lower), min(1.0 - 1e-6, upper)


def _fair_odd_b(lower_a: float, probability_a: float, upper_a: float) -> dict[str, float]:
    probability_b = 1.0 - probability_a
    lower_b = 1.0 - upper_a
    upper_b = 1.0 - lower_a
    return {
        "central": round(1.0 / probability_b, 4),
        "lower_odd": round(1.0 / upper_b, 4),
        "upper_odd": round(1.0 / lower_b, 4),
    }


def predict_fenzobot_contextual(
    row: Mapping[str, Any], contract: Mapping[str, Any], *, universe: str,
) -> dict[str, Any]:
    universe = str(universe).strip().casefold()
    if universe not in {"atp", "wta"}:
        raise ValueError("global contextual release supports ATP/WTA only")
    universe_contract = contract["universes"][universe]
    combination_contract = {
        "model_version": contract["components"]["family_combination"],
        "mode": "SHADOW_ONLY",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {universe: universe_contract["combination"]},
    }
    prediction = predict_contextual_combination_v8(
        [dict(row)], universe=universe, contract=combination_contract,
    )
    working = prediction["rows"][0]
    raw_probability = float(prediction["probabilities"][0])
    calibration = universe_contract["calibration"]
    probability = _apply_calibrator(
        raw_probability, calibration["central_calibrator"],
    )
    record = {"row": working, "probability": probability}
    bin_item, interval_source, global_bin = _lookup_interval(
        calibration["calibration_model"], record,
    )
    quality_group = _quality_group(working)
    supported = calibration["supported_probability_range"]
    extrapolation = not (
        float(supported["lower"]) <= probability <= float(supported["upper"])
    )
    reason_codes = []
    if quality_group == "PRIMARY_DEGRADED":
        reason_codes.append("PRIMARY_FAMILY_UNAVAILABLE")
    if extrapolation:
        reason_codes.append("PROBABILITY_EXTRAPOLATION")
    if int(bin_item["sample"]) < MIN_BIN_SAMPLE:
        reason_codes.append("CALIBRATION_BIN_SAMPLE_LOW")
    labels = {item["key"]: item["label"] for item in FAMILY_DEFINITIONS}
    family_probabilities = working["family_probabilities"]
    coefficients = universe_contract["combination"]["family_coefficients"]
    runtime_models = universe_contract["combination"]["runtime_family_models"]
    surface_context = (working.get("diagnostics") or {}).get("surface_context")
    equation_audit = row.get("candidate_equation_audit") or {}
    family_rows = []
    family_rows_by_key: dict[str, dict[str, Any]] = {}
    contributions: dict[str, float] = {}
    for family in FAMILY_ORDER:
        family_probability = family_probabilities.get(family)
        contribution = (
            float(coefficients.get(family, 0.0)) * _logit(family_probability)
            if family_probability is not None else 0.0
        )
        contributions[family] = contribution
        model = runtime_models.get(family)
        if family == "surface_conditions":
            model = (model or {}).get(surface_context)
        data_state = (
            (row.get("family_states") or {}).get(family) or {}
        ).get("data_state")
        family_row = {
            "key": family,
            "label": labels[family],
            "probability_model_a": (
                round(float(family_probability), 6)
                if family_probability is not None else None
            ),
            "logit_contribution": round(contribution, 8),
            "data_state": data_state,
            "coverage_grade": _coverage_grade(data_state, family_probability),
            "internal_trace": (
                explain_family_equation(dict(row), model)
                if isinstance(model, dict) else {"status": "UNAVAILABLE", "features": []}
            ),
            "context_audit": (
                dict(equation_audit.get("structural_strength_v7") or {})
                if family == "structural_strength"
                else dict(equation_audit.get("recent_form_v1") or {})
                if family == "recent_form"
                else dict(equation_audit.get("matchup_h2h") or {})
                if family == "matchup_h2h"
                else {}
            ),
        }
        family_rows.append(family_row)
        family_rows_by_key[family] = family_row
    raw_logit = _logit(raw_probability)
    sensitivity = []
    for family, contribution in contributions.items():
        if abs(contribution) <= 1e-12:
            continue
        probability_without_family = _apply_calibrator(
            _sigmoid(raw_logit - contribution), calibration["central_calibrator"],
        )
        calibrated_impact_pp = 100.0 * (
            probability - probability_without_family
        )
        family_rows_by_key[family].update({
            "impact_pp_model_a": round(calibrated_impact_pp, 3),
            "impact_direction": (
                "a" if calibrated_impact_pp > 0
                else "b" if calibrated_impact_pp < 0 else "neutral"
            ),
            "impact_intensity": _impact_intensity(calibrated_impact_pp),
        })
        sensitivity.append({
            "family": family,
            "probability_model_a_without_family": round(
                probability_without_family, 6,
            ),
            "impact_pp_model_a": round(calibrated_impact_pp, 3),
        })
    sensitivity_probabilities = [
        float(item["probability_model_a_without_family"]) for item in sensitivity
    ]
    central_side = "a" if probability > 0.5 else "b" if probability < 0.5 else None
    stable_side = bool(central_side) and all(
        (value > 0.5 if central_side == "a" else value < 0.5)
        for value in sensitivity_probabilities
    )
    dominant_family = None
    dependency_grade = "ROBUST"
    lead_authority = None
    if central_side and sensitivity:
        for scenario in sensitivity:
            scenario["dependency_grade"] = _dependency_grade(
                full_probability=probability,
                without_probability=float(
                    scenario["probability_model_a_without_family"]
                ),
                central_side=central_side,
            )
        grade_order = {
            "ROBUST": 0, "BALANCED_SENSITIVE": 1,
            "MATERIAL_DEPENDENCE": 2, "CRITICAL_DEPENDENCE": 3,
        }
        worst = max(sensitivity, key=lambda item: grade_order[item["dependency_grade"]])
        dependency_grade = worst["dependency_grade"]
        if dependency_grade != "ROBUST":
            dominant_family = worst["family"]
        if dependency_grade == "CRITICAL_DEPENDENCE":
            lead_authority = _family_lead_authority(
                family_rows_by_key[dominant_family],
                contribution=contributions[dominant_family],
            )
            if lead_authority["authorised"]:
                dependency_grade = "MATERIAL_DEPENDENCE"
                worst["dependency_grade"] = "PRIMARY_FAMILY_LEAD"
            else:
                reason_codes.append("CRITICAL_SINGLE_FAMILY_DEPENDENCE")
    lower, upper = _centred_empirical_interval(
        probability, bin_item, global_bin,
        quality_group=quality_group,
        sensitivity_probabilities=sensitivity_probabilities,
    )
    grade_counts = {
        grade: sum(row["coverage_grade"] == grade for row in family_rows)
        for grade in ("SOLID", "PARTIAL", "OBSERVED_NEUTRAL", "UNAVAILABLE")
    }
    usable_families = grade_counts["SOLID"] + grade_counts["PARTIAL"]
    measured_families = usable_families + grade_counts["OBSERVED_NEUTRAL"]
    status = (
        "READY_FOR_PROSPECTIVE_SHADOW"
        if not reason_codes else "NOT_OPERATIONALLY_READY"
    )
    return {
        "schema_version": 3,
        "global_release_id": contract["global_release_id"],
        "release_slug": contract["release_slug"],
        "runtime_generation": contract["components"]["runtime_generation"],
        "component_versions": dict(contract["components"]),
        "configuration_fingerprint": contract["configuration_fingerprint"],
        "mode": "PROSPECTIVE_SHADOW_ONLY",
        "universe": universe,
        "model_orientation": {
            "player_a": row["player_a"],
            "player_b": row["player_b"],
            **dict(row.get("orientation") or {}),
        },
        "probability_model_a_raw": round(raw_probability, 6),
        "probability_model_a": round(probability, 6),
        "probability_model_b": round(1.0 - probability, 6),
        "probability_interval_90_model_a": [round(lower, 6), round(upper, 6)],
        "fair_odd_model_a": _fair_odd(probability, lower, upper),
        "fair_odd_model_b": _fair_odd_b(lower, probability, upper),
        "families": family_rows,
        "family_sensitivity": {
            "method": "LEAVE_ONE_FAMILY_OUT",
            "central_side": central_side,
            "favorite_confirmed": stable_side,
            "dependency_grade": dependency_grade,
            "dominant_family_if_unstable": dominant_family,
            "lead_authority": lead_authority,
            "scenarios": sensitivity,
        },
        "family_coverage": {
            "solid": grade_counts["SOLID"],
            "partial": grade_counts["PARTIAL"],
            "observed_neutral": grade_counts["OBSERVED_NEUTRAL"],
            "unavailable": grade_counts["UNAVAILABLE"],
            "usable": usable_families,
            "measured": measured_families,
            "total": len(FAMILY_ORDER),
            "pct": round(100.0 * measured_families / len(FAMILY_ORDER), 2),
        },
        "surface_context": surface_context,
        "quality_group": quality_group,
        "interval_source": interval_source,
        "calibration_bin_sample": int(bin_item["sample"]),
        "extrapolation": extrapolation,
        "status": status,
        "reason_codes": reason_codes,
        "market_used": False,
        "edge_calculated": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
    }
