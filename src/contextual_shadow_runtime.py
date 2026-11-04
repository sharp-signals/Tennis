"""Market-free prospective runtime for the contextual family SHADOW model."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .contextual_factor_orchestrator import FAMILY_DEFINITIONS

DEFAULT_MODEL_PATH = Path("data/models/contextual-family-shadow-v1.json")
MIN_BIN_SAMPLE = 80


@lru_cache(maxsize=4)
def load_contract(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("mode") != "PROSPECTIVE_SHADOW_ONLY"
        or value.get("market_used") is not False
        or value.get("production_effect") is not False
    ):
        raise ValueError("invalid contextual SHADOW contract")
    return value


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def _logit(probability: float) -> float:
    p = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _family_probability(row: Mapping[str, Any], model: Mapping[str, Any]) -> float | None:
    features = row.get("features") if isinstance(row.get("features"), Mapping) else {}
    if not any(features.get(name) is not None for name in model["features"]):
        return None
    linear = float(model["intercept"])
    coefficients = (
        dict(zip(model["columns"], model["weights"]))
        if "columns" in model and "weights" in model
        else model["coefficients"]
    )
    for name in model["features"]:
        params = model["preprocessor"]["features"][name]
        missing = features.get(name) is None
        raw = float(params["median"] if missing else features[name])
        if params["available"]:
            raw = min(max(raw, float(params["lower"])), float(params["upper"]))
            transformed = (raw - float(params["median"])) / float(params["scale"])
        else:
            transformed = 0.0
        linear += float(coefficients.get(name, 0.0)) * transformed
        linear += float(coefficients.get(f"{name}__missing", 0.0)) * float(missing)
    return _sigmoid(linear)


def _quality_group(row: Mapping[str, Any], primary: list[str]) -> str:
    states = row.get("family_states") if isinstance(row.get("family_states"), Mapping) else {}
    ready = all(
        (states.get(name) or {}).get("data_state") in {"OBSERVED", "OBSERVED_NONE"}
        for name in primary
    )
    return "PRIMARY_READY" if ready else "PRIMARY_DEGRADED"


def _bin_index(probability: float, edges: list[float]) -> int:
    for index in range(len(edges) - 1):
        if probability < edges[index + 1] or index == len(edges) - 2:
            return index
    return len(edges) - 2


def _interval(
    probability: float, row: Mapping[str, Any], model: Mapping[str, Any], primary: list[str],
) -> tuple[float, float, str, int, bool]:
    group_name = _quality_group(row, primary)
    group = model["groups"].get(group_name)
    source = group_name
    selected = None
    if group:
        selected = group["bins"][_bin_index(probability, group["edges"])]
    if not selected or int(selected["sample"]) < MIN_BIN_SAMPLE:
        group = model["global"]
        selected = group["bins"][_bin_index(probability, group["edges"])]
        source = "GLOBAL_FALLBACK"
    lower = min(probability, float(selected["wilson_lower"]))
    upper = max(probability, float(selected["wilson_upper"]))
    return lower, upper, source, int(selected["sample"]), group_name == "PRIMARY_READY"


def predict_contextual_shadow(
    row: Mapping[str, Any], contract: Mapping[str, Any], *, universe: str,
) -> dict[str, Any]:
    universe = str(universe).strip().casefold()
    model = contract["universes"][universe]
    states = row.get("family_states") if isinstance(row.get("family_states"), Mapping) else {}
    family_probabilities = {
        name: _family_probability(row, family_model)
        for name, family_model in model["families"].items()
    }
    linear = float(model["combination"]["intercept"])
    coefficients = model["combination"]["coefficients"]
    for name, probability in family_probabilities.items():
        state = (states.get(name) or {}).get("data_state")
        linear += float(coefficients.get(f"{name}__logit", 0.0)) * (
            _logit(probability) if probability is not None else 0.0
        )
        linear += float(coefficients.get(f"{name}__unavailable", 0.0)) * float(
            state in {"MISSING_DATA", "INSUFFICIENT_SAMPLE"}
        )
        linear += float(coefficients.get(f"{name}__observed_none", 0.0)) * float(
            state == "OBSERVED_NONE"
        )
    probability = _sigmoid(linear)
    uncertainty = model["uncertainty"]
    supported = uncertainty["supported_probability_range"]
    extrapolation = not (
        float(supported["lower"]) <= probability <= float(supported["upper"])
    )
    lower, upper, interval_source, bin_sample, primary_ready = _interval(
        probability, row, uncertainty["calibration_model"],
        model["combination"]["primary_families"],
    )
    readiness = (
        "READY_FOR_PROSPECTIVE_SHADOW"
        if primary_ready and not extrapolation and bin_sample >= MIN_BIN_SAMPLE
        else "NOT_OPERATIONALLY_READY"
    )
    labels = {item["key"]: item["label"] for item in FAMILY_DEFINITIONS}
    family_rows = []
    for name in model["families"]:
        family_rows.append({
            "key": name, "label": labels[name],
            "probability_model_a": (
                round(family_probabilities[name], 6)
                if family_probabilities[name] is not None else None
            ),
            "data_state": (states.get(name) or {}).get("data_state"),
            "samples": dict(row.get("samples") or {}),
        })
    return {
        "schema_version": 1,
        "model_version": contract["model_version"],
        "configuration_fingerprint": contract["configuration_fingerprint"],
        "mode": "PROSPECTIVE_SHADOW_ONLY",
        "universe": universe,
        "model_orientation": {
            "player_a": row["player_a"], "player_b": row["player_b"],
            **dict(row.get("orientation") or {}),
        },
        "probability_model_a": round(probability, 6),
        "probability_model_b": round(1.0 - probability, 6),
        "probability_interval_90_model_a": [round(lower, 6), round(upper, 6)],
        "fair_odd_model_a": {
            "central": round(1.0 / probability, 4),
            "lower": round(1.0 / upper, 4), "upper": round(1.0 / lower, 4),
        },
        "fair_odd_model_b": {
            "central": round(1.0 / (1.0 - probability), 4),
            "lower": round(1.0 / (1.0 - lower), 4),
            "upper": round(1.0 / (1.0 - upper), 4),
        },
        "families": family_rows,
        "quality_group": _quality_group(row, model["combination"]["primary_families"]),
        "interval_source": interval_source,
        "calibration_bin_sample": bin_sample,
        "extrapolation": extrapolation,
        "status": readiness,
        "market_used": False, "edge_calculated": False,
        "production_effect": False, "paper_eligible": False, "green_eligible": False,
    }
