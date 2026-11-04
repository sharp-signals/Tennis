"""Empirical uncertainty and safety gates for the market-free probability."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

import numpy as np

from .contextual_family_combination import PRIMARY_FAMILIES, combine_contextual_families


SCHEMA_VERSION = 1
CONFIDENCE_LEVEL = 0.90
WILSON_Z = 1.6448536269514722
MIN_BIN_SAMPLE = 80


def _primary_ready(row: dict[str, Any]) -> bool:
    states = row.get("family_states", {})
    return all(
        states.get(family, {}).get("data_state") in {"OBSERVED", "OBSERVED_NONE"}
        for family in PRIMARY_FAMILIES
    )


def _quality_group(row: dict[str, Any]) -> str:
    return "PRIMARY_READY" if _primary_ready(row) else "PRIMARY_DEGRADED"


def _wilson(successes: int, sample: int, z: float = WILSON_Z) -> tuple[float, float]:
    if sample <= 0:
        raise ValueError("Wilson interval requires positive sample")
    p = successes / sample
    denominator = 1.0 + z * z / sample
    centre = (p + z * z / (2.0 * sample)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * sample)) / sample) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _chronological_halves(
    rows: list[dict[str, Any]], probabilities: list[float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = [
        {"row": row, "probability": float(probability)}
        for row, probability in zip(rows, probabilities)
    ]
    dates = sorted({record["row"]["event_date"] for record in records})
    counts = {
        day: sum(record["row"]["event_date"] == day for record in records)
        for day in dates
    }
    threshold = len(records) * 0.5
    first_dates: set[str] = set()
    cumulative = 0
    for day in dates:
        if cumulative < threshold:
            first_dates.add(day)
        cumulative += counts[day]
    first = [record for record in records if record["row"]["event_date"] in first_dates]
    second = [record for record in records if record["row"]["event_date"] not in first_dates]
    return first, second


def _quantile_edges(probabilities: list[float], bins: int = 5) -> list[float]:
    values = np.asarray(probabilities, dtype=float)
    if not len(values):
        return [0.0, 1.0]
    edges = [float(value) for value in np.quantile(values, np.linspace(0.0, 1.0, bins + 1))]
    edges[0], edges[-1] = 0.0, 1.0
    unique = [edges[0]]
    for value in edges[1:]:
        if value > unique[-1] + 1e-9:
            unique.append(value)
    if unique[-1] < 1.0:
        unique.append(1.0)
    return unique if len(unique) >= 2 else [0.0, 1.0]


def _bin_index(probability: float, edges: list[float]) -> int:
    return min(len(edges) - 2, max(0, int(np.searchsorted(edges, probability, side="right") - 1)))


def _fit_bins(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups = defaultdict(list)
    for record in records:
        groups[_quality_group(record["row"])].append(record)
    model = {"groups": {}, "global": None}

    def fit_group(items: list[dict[str, Any]]) -> dict[str, Any]:
        edges = _quantile_edges([item["probability"] for item in items])
        bins = []
        for index in range(len(edges) - 1):
            selected = [
                item for item in items
                if _bin_index(item["probability"], edges) == index
            ]
            successes = sum(bool(item["row"]["target_a_win"]) for item in selected)
            if selected:
                lower, upper = _wilson(successes, len(selected))
                observed = successes / len(selected)
                predicted = sum(item["probability"] for item in selected) / len(selected)
            else:
                lower = upper = observed = predicted = None
            bins.append({
                "index": index, "lower_edge": edges[index], "upper_edge": edges[index + 1],
                "sample": len(selected), "successes": successes,
                "predicted_mean": predicted, "observed_rate": observed,
                "wilson_lower": lower, "wilson_upper": upper,
            })
        return {"sample": len(items), "edges": edges, "bins": bins}

    model["global"] = fit_group(records)
    for name, items in groups.items():
        model["groups"][name] = fit_group(items)
    probabilities = [record["probability"] for record in records]
    model["supported_probability_range"] = {
        "lower": float(np.quantile(probabilities, 0.005)),
        "upper": float(np.quantile(probabilities, 0.995)),
        "quantiles": [0.005, 0.995],
    }
    return model


def _lookup_bin(model: dict[str, Any], record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    group_name = _quality_group(record["row"])
    group = model["groups"].get(group_name)
    if group:
        item = group["bins"][_bin_index(record["probability"], group["edges"])]
        if item["sample"] >= MIN_BIN_SAMPLE:
            return item, group_name
    global_group = model["global"]
    return (
        global_group["bins"][_bin_index(record["probability"], global_group["edges"])],
        "GLOBAL_FALLBACK",
    )


def _fair_odd_interval(probability: float, lower: float, upper: float) -> dict[str, float]:
    probability = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    lower = min(max(float(lower), 1e-6), 1.0 - 1e-6)
    upper = min(max(float(upper), 1e-6), 1.0 - 1e-6)
    return {
        "central": round(1.0 / probability, 4),
        "lower_odd": round(1.0 / upper, 4),
        "upper_odd": round(1.0 / lower, 4),
    }


def calibrate_probability_uncertainty(
    rows: list[dict[str, Any]], *, universe: str,
) -> dict[str, Any]:
    combination = combine_contextual_families(
        rows, universe=universe, include_diagnostics=True,
    )
    diagnostics = combination.pop("_diagnostics")
    calibration, test = _chronological_halves(
        diagnostics["holdout_rows"], diagnostics["holdout_probabilities"],
    )
    bin_model = _fit_bins(calibration)
    supported = bin_model["supported_probability_range"]
    evaluated = []
    grouped_test = defaultdict(list)
    for record in test:
        bin_item, source_group = _lookup_bin(bin_model, record)
        probability = record["probability"]
        lower = min(probability, float(bin_item["wilson_lower"]))
        upper = max(probability, float(bin_item["wilson_upper"]))
        extrapolation = not (supported["lower"] <= probability <= supported["upper"])
        primary_ready = _primary_ready(record["row"])
        status = (
            "READY_FOR_PROSPECTIVE_SHADOW"
            if primary_ready and not extrapolation and bin_item["sample"] >= MIN_BIN_SAMPLE
            else "NOT_OPERATIONALLY_READY"
        )
        item = {
            "event_date": record["row"]["event_date"],
            "probability": probability,
            "probability_interval_90": [lower, upper],
            "calibration_interval_90": [
                float(bin_item["wilson_lower"]), float(bin_item["wilson_upper"]),
            ],
            "interval_width": upper - lower,
            "fair_odd": _fair_odd_interval(probability, lower, upper),
            "quality_group": _quality_group(record["row"]),
            "calibration_source": source_group,
            "calibration_bin_sample": bin_item["sample"],
            "extrapolation": extrapolation,
            "status": status,
            "target_a_win": bool(record["row"]["target_a_win"]),
        }
        evaluated.append(item)
        grouped_test[(source_group, bin_item["index"])].append(item)

    group_checks = []
    for (group, index), items in grouped_test.items():
        successes = sum(item["target_a_win"] for item in items)
        observed = successes / len(items)
        test_lower, test_upper = _wilson(successes, len(items))
        lower = min(item["calibration_interval_90"][0] for item in items)
        upper = max(item["calibration_interval_90"][1] for item in items)
        group_checks.append({
            "group": group, "bin_index": index, "sample": len(items),
            "observed_rate": observed, "interval_lower": lower,
            "interval_upper": upper,
            "test_wilson_lower": test_lower,
            "test_wilson_upper": test_upper,
            "point_inside_calibration_interval": lower <= observed <= upper,
            "covered": not (test_upper < lower or test_lower > upper),
        })
    widths = [item["interval_width"] for item in evaluated]
    ready = [item for item in evaluated if item["status"] == "READY_FOR_PROSPECTIVE_SHADOW"]
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "status": "UNCERTAINTY_CALIBRATED_FOR_SHADOW",
        "confidence_level": CONFIDENCE_LEVEL,
        "holdout_partition": {
            "uncertainty_calibration": len(calibration),
            "uncertainty_test": len(test),
            "policy": "chronological_half_dates",
        },
        "supported_probability_range": supported,
        "test_summary": {
            "records": len(evaluated),
            "ready_for_prospective_shadow": len(ready),
            "ready_pct": round(100.0 * len(ready) / max(1, len(evaluated)), 2),
            "extrapolations": sum(item["extrapolation"] for item in evaluated),
            "median_interval_width": round(float(np.median(widths)), 6),
            "p90_interval_width": round(float(np.quantile(widths, 0.9)), 6),
            "calibration_groups_covered": sum(item["covered"] for item in group_checks),
            "calibration_groups_total": len(group_checks),
        },
        "group_checks": group_checks,
        "calibration_model": bin_model,
        "example_intervals": evaluated[:20],
        "fair_odd_status": "SHADOW_ONLY_NOT_OPERATIONAL",
        "market_used": False,
        "production_effect": False,
        "combination_summary": combination,
    }
