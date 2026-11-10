"""Market-free prospective runtime for the globally named contextual release."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .contextual_family_combination_v2 import FAMILY_ORDER
from .contextual_family_combination_v3 import predict_contextual_combination_v3
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
    prediction = predict_contextual_combination_v3(
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
    lower = min(probability, float(bin_item["wilson_lower"]))
    upper = max(probability, float(bin_item["wilson_upper"]))
    quality_group = _quality_group(working)
    if quality_group != "PRIMARY_READY_COMPLETE":
        lower = min(lower, float(global_bin["wilson_lower"]))
        upper = max(upper, float(global_bin["wilson_upper"]))
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
    status = (
        "READY_FOR_PROSPECTIVE_SHADOW"
        if not reason_codes else "NOT_OPERATIONALLY_READY"
    )
    labels = {item["key"]: item["label"] for item in FAMILY_DEFINITIONS}
    family_probabilities = working["family_probabilities"]
    coefficients = universe_contract["combination"]["family_coefficients"]
    family_rows = []
    for family in FAMILY_ORDER:
        family_probability = family_probabilities.get(family)
        contribution = (
            float(coefficients.get(family, 0.0)) * _logit(family_probability)
            if family_probability is not None else 0.0
        )
        family_rows.append({
            "key": family,
            "label": labels[family],
            "probability_model_a": (
                round(float(family_probability), 6)
                if family_probability is not None else None
            ),
            "logit_contribution": round(contribution, 8),
            "data_state": (
                (row.get("family_states") or {}).get(family) or {}
            ).get("data_state"),
        })
    observed_families = sum(
        _family_available(working, family) for family in FAMILY_ORDER
    )
    surface_context = (working.get("diagnostics") or {}).get("surface_context")
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
