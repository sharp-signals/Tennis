"""Prospective, market-free runtime for contextual model v2."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .contextual_family_calibration import predict_family_equation
from .contextual_family_combination_v2 import FAMILY_ORDER
from .contextual_factor_orchestrator import FAMILY_DEFINITIONS
from .contextual_probability_uncertainty_v2 import (
    MIN_BIN_SAMPLE,
    _apply_calibrator,
    _fair_odd,
    _family_available,
    _lookup_interval,
    _quality_group,
)


DEFAULT_MODEL_PATH = Path("data/models/contextual-family-shadow-v2.json")


@lru_cache(maxsize=4)
def load_contract(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("model_version") != "contextual-family-shadow-v2"
        or value.get("mode") != "PROSPECTIVE_SHADOW_ONLY"
        or value.get("market_used") is not False
        or value.get("production_effect") is not False
        or set(value.get("universes") or {}) != {"atp", "wta"}
    ):
        raise ValueError("invalid contextual SHADOW v2 contract")
    return value


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _surface_context(row: Mapping[str, Any]) -> str | None:
    diagnostics = row.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return None
    value = diagnostics.get("surface_context")
    return str(value) if value else None


def _family_probability(
    row: Mapping[str, Any], family: str, models: Mapping[str, Any],
) -> tuple[float | None, str | None]:
    if family == "surface_conditions":
        context = _surface_context(row)
        model = models.get(context) if context else None
        if not isinstance(model, Mapping):
            return None, context
    else:
        model = models
    material = dict(row)
    # The shared transformer also returns historical targets.  A prospective
    # prediction has no result yet, so provide a non-semantic placeholder that
    # is never used by the probability calculation.
    material.setdefault("target_a_win", False)
    probability = predict_family_equation([material], dict(model))[0]
    return probability, _surface_context(row) if family == "surface_conditions" else None


def _fair_odd_b(lower_a: float, probability_a: float, upper_a: float) -> dict[str, float]:
    probability_b = 1.0 - probability_a
    lower_b = 1.0 - upper_a
    upper_b = 1.0 - lower_a
    return {
        "central": round(1.0 / probability_b, 4),
        "lower_odd": round(1.0 / upper_b, 4),
        "upper_odd": round(1.0 / lower_b, 4),
    }


def predict_contextual_shadow_v2(
    row: Mapping[str, Any], contract: Mapping[str, Any], *, universe: str,
) -> dict[str, Any]:
    universe = str(universe).strip().casefold()
    if universe not in {"atp", "wta"}:
        raise ValueError("contextual SHADOW v2 supports ATP/WTA only")
    model = contract["universes"][universe]
    family_probabilities = {}
    surface_context = None
    for family in FAMILY_ORDER:
        probability, context = _family_probability(
            row, family, model["families"][family],
        )
        family_probabilities[family] = probability
        if family == "surface_conditions":
            surface_context = context

    working = dict(row)
    working["family_probabilities"] = family_probabilities
    working["family_numeric_states"] = {
        "surface_conditions": (
            "OBSERVED" if family_probabilities["surface_conditions"] is not None
            else "DIAGNOSTIC_ONLY"
            if universe == "wta" and surface_context == "hard_indoor"
            else "UNAVAILABLE"
        ),
    }
    combination = model["combination"]
    linear = float(combination["intercept"])
    family_contributions = {}
    for family in FAMILY_ORDER:
        probability = family_probabilities[family]
        coefficient = float(
            combination["coefficients"].get(f"{family}__logit", 0.0)
        )
        contribution = coefficient * (
            _logit(probability) if probability is not None else 0.0
        )
        family_contributions[family] = contribution
        linear += contribution
    raw_probability = _sigmoid(linear)
    uncertainty = model["uncertainty"]
    probability = _apply_calibrator(
        raw_probability, uncertainty["central_calibrator"],
    )
    record = {"row": working, "probability": probability}
    bin_item, interval_source, global_bin = _lookup_interval(
        uncertainty["calibration_model"], record,
    )
    lower = min(probability, float(bin_item["wilson_lower"]))
    upper = max(probability, float(bin_item["wilson_upper"]))
    quality_group = _quality_group(working)
    if quality_group != "PRIMARY_READY_COMPLETE":
        lower = min(lower, float(global_bin["wilson_lower"]))
        upper = max(upper, float(global_bin["wilson_upper"]))
    supported = uncertainty["supported_probability_range"]
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
    status = (
        "READY_FOR_PROSPECTIVE_SHADOW"
        if not reason_codes else "NOT_OPERATIONALLY_READY"
    )
    labels = {item["key"]: item["label"] for item in FAMILY_DEFINITIONS}
    family_rows = [
        {
            "key": family,
            "label": labels[family],
            "probability_model_a": (
                round(family_probabilities[family], 6)
                if family_probabilities[family] is not None else None
            ),
            "logit_contribution": round(family_contributions[family], 8),
            "data_state": (
                (row.get("family_states") or {}).get(family) or {}
            ).get("data_state"),
        }
        for family in FAMILY_ORDER
    ]
    observed_families = sum(
        _family_available(working, family) for family in FAMILY_ORDER
    )
    return {
        "schema_version": 2,
        "model_version": contract["model_version"],
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
        "family_coverage": {
            "observed": observed_families,
            "total": len(FAMILY_ORDER),
            "pct": round(100.0 * observed_families / len(FAMILY_ORDER), 2),
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
