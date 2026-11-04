"""Market-free calibration and empirical uncertainty for combination v2."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

import numpy as np

from .contextual_family_calibration import (
    _fit_logistic_elastic_net,
    _metrics,
    _predict,
)
from .contextual_family_combination_v2 import (
    FAMILY_ORDER,
    PRIMARY_FAMILIES,
    combine_contextual_families_v2,
)


SCHEMA_VERSION = 2
CONFIDENCE_LEVEL = 0.90
WILSON_Z = 1.6448536269514722
MIN_BIN_SAMPLE = 80


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _chronological_partition(
    records: list[dict[str, Any]], fraction: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = sorted({record["row"]["event_date"] for record in records})
    counts = {
        day: sum(record["row"]["event_date"] == day for record in records)
        for day in dates
    }
    threshold = len(records) * float(fraction)
    first_dates: set[str] = set()
    cumulative = 0
    for day in dates:
        if cumulative < threshold:
            first_dates.add(day)
        cumulative += counts[day]
    return (
        [record for record in records if record["row"]["event_date"] in first_dates],
        [record for record in records if record["row"]["event_date"] not in first_dates],
    )


def _fit_platt(records: list[dict[str, Any]]) -> dict[str, Any]:
    x = np.asarray([[_logit(record["raw_probability"])] for record in records])
    y = np.asarray([
        1.0 if record["row"]["target_a_win"] else 0.0 for record in records
    ])
    intercept, weights, iterations = _fit_logistic_elastic_net(
        x,
        y,
        l1=0.0,
        l2=0.01,
        nonnegative_mask=np.asarray([True]),
    )
    return {
        "method": "PLATT_LOGIT_NONNEGATIVE",
        "intercept": float(intercept),
        "slope": float(weights[0]),
        "iterations": iterations,
    }


def _apply_calibrator(probability: float, model: dict[str, Any]) -> float:
    if model["method"] == "IDENTITY":
        return float(probability)
    value = model["intercept"] + model["slope"] * _logit(probability)
    return float(1.0 / (1.0 + math.exp(-min(max(value, -35.0), 35.0))))


def _select_calibrator(records: list[dict[str, Any]]) -> dict[str, Any]:
    fit, validation = _chronological_partition(records, 0.70)
    candidate = _fit_platt(fit)
    targets = np.asarray([
        1.0 if record["row"]["target_a_win"] else 0.0
        for record in validation
    ])
    identity_probability = np.asarray([
        record["raw_probability"] for record in validation
    ])
    platt_probability = np.asarray([
        _apply_calibrator(record["raw_probability"], candidate)
        for record in validation
    ])
    identity_metrics = _metrics(
        targets, identity_probability, total_targets=len(validation),
    )
    platt_metrics = _metrics(
        targets, platt_probability, total_targets=len(validation),
    )
    selected = (
        "PLATT_LOGIT_NONNEGATIVE"
        if platt_metrics["log_loss"] < identity_metrics["log_loss"]
        else "IDENTITY"
    )
    final = (
        _fit_platt(records) if selected == "PLATT_LOGIT_NONNEGATIVE"
        else {"method": "IDENTITY", "intercept": 0.0, "slope": 1.0}
    )
    return {
        **final,
        "selection_policy": "chronological_70_30_log_loss",
        "validation_candidates": {
            "IDENTITY": identity_metrics,
            "PLATT_LOGIT_NONNEGATIVE": platt_metrics,
        },
    }


def _family_available(row: dict[str, Any], family: str) -> bool:
    state = row.get("family_states", {}).get(family, {}).get("data_state")
    if state == "OBSERVED_NONE":
        return True
    if family == "surface_conditions":
        numeric = row.get("family_numeric_states", {}).get(family)
        if numeric in {"DIAGNOSTIC_ONLY", "UNAVAILABLE"}:
            return False
    return row.get("family_probabilities", {}).get(family) is not None


def _quality_group(row: dict[str, Any]) -> str:
    primary_ready = all(_family_available(row, family) for family in PRIMARY_FAMILIES)
    if not primary_ready:
        return "PRIMARY_DEGRADED"
    secondary_gaps = sum(
        not _family_available(row, family) for family in FAMILY_ORDER[2:]
    )
    return (
        "PRIMARY_READY_COMPLETE" if secondary_gaps == 0
        else "PRIMARY_READY_SECONDARY_GAPS"
    )


def _wilson(successes: int, sample: int) -> tuple[float, float]:
    if sample <= 0:
        raise ValueError("Wilson interval requires positive sample")
    p = successes / sample
    denominator = 1.0 + WILSON_Z * WILSON_Z / sample
    centre = (p + WILSON_Z * WILSON_Z / (2.0 * sample)) / denominator
    margin = (
        WILSON_Z
        * math.sqrt(
            (p * (1.0 - p) + WILSON_Z * WILSON_Z / (4.0 * sample))
            / sample
        )
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _quantile_edges(values: list[float], bins: int = 5) -> list[float]:
    if not values:
        return [0.0, 1.0]
    edges = [
        float(value)
        for value in np.quantile(np.asarray(values), np.linspace(0.0, 1.0, bins + 1))
    ]
    edges[0], edges[-1] = 0.0, 1.0
    unique = [edges[0]]
    for value in edges[1:]:
        if value > unique[-1] + 1e-9:
            unique.append(value)
    if unique[-1] < 1.0:
        unique.append(1.0)
    return unique if len(unique) >= 2 else [0.0, 1.0]


def _bin_index(probability: float, edges: list[float]) -> int:
    return min(
        len(edges) - 2,
        max(0, int(np.searchsorted(edges, probability, side="right") - 1)),
    )


def _fit_group(items: list[dict[str, Any]]) -> dict[str, Any]:
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
            "index": index,
            "lower_edge": edges[index],
            "upper_edge": edges[index + 1],
            "sample": len(selected),
            "successes": successes,
            "predicted_mean": predicted,
            "observed_rate": observed,
            "wilson_lower": lower,
            "wilson_upper": upper,
        })
    return {"sample": len(items), "edges": edges, "bins": bins}


def _fit_interval_model(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups = defaultdict(list)
    for record in records:
        groups[_quality_group(record["row"])].append(record)
    probabilities = [record["probability"] for record in records]
    return {
        "global": _fit_group(records),
        "groups": {name: _fit_group(items) for name, items in groups.items()},
        "supported_probability_range": {
            "lower": float(np.quantile(probabilities, 0.005)),
            "upper": float(np.quantile(probabilities, 0.995)),
            "quantiles": [0.005, 0.995],
        },
    }


def _lookup_interval(
    model: dict[str, Any], record: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    probability = record["probability"]
    global_group = model["global"]
    global_bin = global_group["bins"][
        _bin_index(probability, global_group["edges"])
    ]
    group_name = _quality_group(record["row"])
    group = model["groups"].get(group_name)
    if group:
        item = group["bins"][_bin_index(probability, group["edges"])]
        if item["sample"] >= MIN_BIN_SAMPLE:
            return item, group_name, global_bin
    return global_bin, "GLOBAL_FALLBACK", global_bin


def _fair_odd(probability: float, lower: float, upper: float) -> dict[str, float]:
    values = [min(max(float(value), 1e-6), 1.0 - 1e-6) for value in (
        probability, lower, upper,
    )]
    probability, lower, upper = values
    return {
        "central": round(1.0 / probability, 4),
        "lower_odd": round(1.0 / upper, 4),
        "upper_odd": round(1.0 / lower, 4),
    }


def calibrate_probability_uncertainty_v2(
    rows: list[dict[str, Any]], *, universe: str,
) -> dict[str, Any]:
    combination = combine_contextual_families_v2(
        rows, universe=universe, include_diagnostics=True,
    )
    diagnostics = combination.pop("_diagnostics")
    records = [
        {"row": row, "raw_probability": float(probability)}
        for row, probability in zip(
            diagnostics["holdout_rows"], diagnostics["holdout_probabilities"],
        )
    ]
    calibration, test = _chronological_partition(records, 0.50)
    calibrator = _select_calibrator(calibration)
    for record in calibration + test:
        record["probability"] = _apply_calibrator(
            record["raw_probability"], calibrator,
        )
    interval_model = _fit_interval_model(calibration)
    supported = interval_model["supported_probability_range"]
    evaluated = []
    grouped_test = defaultdict(list)
    for record in test:
        bin_item, source_group, global_bin = _lookup_interval(
            interval_model, record,
        )
        probability = record["probability"]
        lower = min(probability, float(bin_item["wilson_lower"]))
        upper = max(probability, float(bin_item["wilson_upper"]))
        quality_group = _quality_group(record["row"])
        if quality_group != "PRIMARY_READY_COMPLETE":
            lower = min(lower, float(global_bin["wilson_lower"]))
            upper = max(upper, float(global_bin["wilson_upper"]))
        extrapolation = not (supported["lower"] <= probability <= supported["upper"])
        primary_ready = quality_group != "PRIMARY_DEGRADED"
        reason_codes = []
        if not primary_ready:
            reason_codes.append("PRIMARY_FAMILY_UNAVAILABLE")
        if extrapolation:
            reason_codes.append("PROBABILITY_EXTRAPOLATION")
        if bin_item["sample"] < MIN_BIN_SAMPLE:
            reason_codes.append("CALIBRATION_BIN_SAMPLE_LOW")
        status = (
            "READY_FOR_PROSPECTIVE_SHADOW"
            if not reason_codes
            else "NOT_OPERATIONALLY_READY"
        )
        item = {
            "event_date": record["row"]["event_date"],
            "raw_probability": record["raw_probability"],
            "probability": probability,
            "probability_interval_90": [lower, upper],
            "interval_width": upper - lower,
            "fair_odd": _fair_odd(probability, lower, upper),
            "quality_group": quality_group,
            "calibration_source": source_group,
            "calibration_bin_sample": bin_item["sample"],
            "extrapolation": extrapolation,
            "status": status,
            "reason_codes": reason_codes,
            "target_a_win": bool(record["row"]["target_a_win"]),
        }
        evaluated.append(item)
        grouped_test[(source_group, bin_item["index"])].append(item)

    group_checks = []
    for (group, index), items in grouped_test.items():
        successes = sum(item["target_a_win"] for item in items)
        observed = successes / len(items)
        test_lower, test_upper = _wilson(successes, len(items))
        lower = min(item["probability_interval_90"][0] for item in items)
        upper = max(item["probability_interval_90"][1] for item in items)
        group_checks.append({
            "group": group,
            "bin_index": index,
            "sample": len(items),
            "observed_rate": observed,
            "interval_lower": lower,
            "interval_upper": upper,
            "test_wilson_lower": test_lower,
            "test_wilson_upper": test_upper,
            "covered": not (test_upper < lower or test_lower > upper),
        })
    targets = np.asarray([1.0 if item["target_a_win"] else 0.0 for item in evaluated])
    raw = np.asarray([item["raw_probability"] for item in evaluated])
    calibrated = np.asarray([item["probability"] for item in evaluated])
    widths = [item["interval_width"] for item in evaluated]
    ready = [item for item in evaluated if item["status"] == "READY_FOR_PROSPECTIVE_SHADOW"]
    blocked_by_reason = defaultdict(int)
    for item in evaluated:
        for reason in item["reason_codes"]:
            blocked_by_reason[reason] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "model_version": "contextual-probability-uncertainty-v2",
        "universe": str(universe).casefold(),
        "status": "UNCERTAINTY_CALIBRATED_FOR_SHADOW",
        "confidence_level": CONFIDENCE_LEVEL,
        "central_calibrator": calibrator,
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
            "blocked_by_reason": dict(sorted(blocked_by_reason.items())),
            "median_interval_width": round(float(np.median(widths)), 6),
            "p90_interval_width": round(float(np.quantile(widths, 0.9)), 6),
            "calibration_groups_covered": sum(item["covered"] for item in group_checks),
            "calibration_groups_total": len(group_checks),
            "raw_metrics": _metrics(targets, raw, total_targets=len(evaluated)),
            "calibrated_metrics": _metrics(
                targets, calibrated, total_targets=len(evaluated),
            ),
        },
        "group_checks": group_checks,
        "calibration_model": interval_model,
        "example_intervals": evaluated[:20],
        "fair_odd_status": "SHADOW_ONLY_NOT_OPERATIONAL",
        "market_used": False,
        "production_effect": False,
        "combination_summary": combination,
    }
