"""Chronological read-only audit of surgical family-hierarchy policies.

This script does not build or promote a model.  It reuses the frozen v11
family equations, recalibrates each candidate on the development partition
only and compares the candidates on the untouched chronological holdout.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Callable

import numpy as np

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    _fit_logistic_elastic_net,
    _metrics,
    _paired_probability_gain,
)
from src.contextual_family_combination_v2 import (
    _attach_predictions,
    _effective_profiles,
    _fit_family_bundle,
)
from src.contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    SECONDARY_FAMILIES,
    govern_consensus_aware_family_contributions,
)
from src.contextual_family_replay import _split


FAMILIES = (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
Policy = Callable[[dict[str, float]], dict[str, float]]


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def _cap_magnitude(value: float, limit: float) -> float:
    return math.copysign(min(abs(float(value)), max(0.0, float(limit))), value)


def _baseline_policy(raw: dict[str, float]) -> dict[str, float]:
    governed, _ = govern_consensus_aware_family_contributions(raw)
    return governed


def _service_below_surface(raw: dict[str, float]) -> dict[str, float]:
    governed = _baseline_policy(raw)
    surface = abs(governed["surface_conditions"])
    if surface > 1e-12:
        governed["serve_return"] = _cap_magnitude(
            governed["serve_return"], surface,
        )
    return governed


def _ordered_single_family_caps(raw: dict[str, float]) -> dict[str, float]:
    """Apply ordinal single-family limits without capping secondary totals."""
    governed = _baseline_policy(raw)
    primary_strongest = max(
        abs(governed[family]) for family in PRIMARY_FAMILIES
    )
    if primary_strongest <= 1e-12:
        return governed
    governed["surface_conditions"] = _cap_magnitude(
        governed["surface_conditions"], primary_strongest,
    )
    governed["matchup_h2h"] = _cap_magnitude(
        governed["matchup_h2h"], primary_strongest,
    )
    service_limit = primary_strongest
    surface = abs(governed["surface_conditions"])
    if surface > 1e-12:
        service_limit = min(service_limit, surface)
    governed["serve_return"] = _cap_magnitude(
        governed["serve_return"], service_limit,
    )
    return governed


POLICIES: dict[str, Policy] = {
    "V11_CONSENSUS_BASELINE": _baseline_policy,
    "SERVICE_NOT_ABOVE_SURFACE": _service_below_surface,
    "ORDERED_SINGLE_FAMILY_CAPS": _ordered_single_family_caps,
}


def _raw_contributions(row: dict, model: dict) -> dict[str, float]:
    probabilities = row["family_probabilities"]
    return {
        family: (
            float(model["family_coefficients"].get(family, 0.0))
            * _logit(probabilities[family])
            if probabilities.get(family) is not None else 0.0
        )
        for family in FAMILIES
    }


def _policy_logits(
    rows: list[dict], *, model: dict, policy: Policy,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    contributions, logits = [], []
    for row in rows:
        governed = policy(_raw_contributions(row, model))
        contributions.append(governed)
        logits.append(float(model["intercept"]) + sum(governed.values()))
    return np.asarray(logits, dtype=float), contributions


def _fit_platt(logits: np.ndarray, rows: list[dict]) -> tuple[float, float]:
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in rows
    ])
    intercept, weights, _ = _fit_logistic_elastic_net(
        logits.reshape(-1, 1), targets, l1=0.0, l2=1e-6,
        nonnegative_mask=np.asarray([True]),
    )
    return float(intercept), float(weights[0])


def _consensus_feature(contributions: list[dict[str, float]]) -> np.ndarray:
    values = []
    for item in contributions:
        active = [float(item[family]) for family in FAMILIES]
        directions = {
            1 if value > 1e-12 else -1 if value < -1e-12 else 0
            for value in active
        }
        if 0 not in directions and len(directions) == 1:
            values.append(sum(active))
        else:
            values.append(0.0)
    return np.asarray(values, dtype=float)


def _fit_consensus_calibration(
    logits: np.ndarray, contributions: list[dict[str, float]], rows: list[dict],
) -> tuple[float, np.ndarray]:
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in rows
    ])
    features = np.column_stack((logits, _consensus_feature(contributions)))
    intercept, weights, _ = _fit_logistic_elastic_net(
        features, targets, l1=0.0, l2=1e-6,
        nonnegative_mask=np.asarray([True, True]),
    )
    return float(intercept), np.asarray(weights, dtype=float)


def _priority_violations(contributions: list[dict[str, float]]) -> dict:
    counts = {
        "serve_above_surface": 0,
        "serve_above_recent": 0,
        "serve_above_structural": 0,
        "surface_above_both_primaries": 0,
        "h2h_above_both_primaries": 0,
    }
    for item in contributions:
        impact = {family: abs(item[family]) for family in FAMILIES}
        counts["serve_above_surface"] += (
            impact["serve_return"] > impact["surface_conditions"] + 1e-12
        )
        counts["serve_above_recent"] += (
            impact["serve_return"] > impact["recent_form"] + 1e-12
        )
        counts["serve_above_structural"] += (
            impact["serve_return"] > impact["structural_strength"] + 1e-12
        )
        primary_strongest = max(
            impact["recent_form"], impact["structural_strength"],
        )
        counts["surface_above_both_primaries"] += (
            impact["surface_conditions"] > primary_strongest + 1e-12
        )
        counts["h2h_above_both_primaries"] += (
            impact["matchup_h2h"] > primary_strongest + 1e-12
        )
    sample = max(1, len(contributions))
    return {
        "sample": len(contributions),
        "counts": counts,
        "percentages": {
            key: round(100.0 * value / sample, 2)
            for key, value in counts.items()
        },
    }


def _favorite_reliability(
    targets: np.ndarray, probabilities: np.ndarray, indexes: np.ndarray,
) -> list[dict]:
    bins = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.000001)
    rows = []
    for lower, upper in zip(bins, bins[1:]):
        selected = []
        for index in indexes:
            probability = float(probabilities[index])
            favorite_probability = max(probability, 1.0 - probability)
            if lower <= favorite_probability < upper:
                favorite_won = (
                    float(targets[index])
                    if probability >= 0.5 else 1.0 - float(targets[index])
                )
                selected.append((favorite_probability, favorite_won))
        if not selected:
            continue
        predicted = float(np.mean([item[0] for item in selected]))
        observed = float(np.mean([item[1] for item in selected]))
        rows.append({
            "band": f"{lower:.2f}-{min(upper, 1.0):.2f}",
            "sample": len(selected),
            "mean_predicted_favorite_pct": round(100.0 * predicted, 2),
            "observed_favorite_win_pct": round(100.0 * observed, 2),
            "observed_minus_predicted_pp": round(100.0 * (observed - predicted), 2),
        })
    return rows


def audit_universe(rows: list[dict], *, universe: str, contract: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    model = contract["universes"][universe]
    profiles = _effective_profiles(universe, model["family_profiles"])
    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=model["family_l1_selected_inside_train"],
        profiles=profiles,
    )
    development = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    holdout = _attach_predictions(
        split["holdout"], model["runtime_family_models"], universe=universe,
    )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    result = {}
    probabilities_by_policy = {}
    for name, policy in POLICIES.items():
        development_logits, _ = _policy_logits(
            development, model=model, policy=policy,
        )
        calibration_intercept, calibration_slope = _fit_platt(
            development_logits, development,
        )
        holdout_logits, contributions = _policy_logits(
            holdout, model=model, policy=policy,
        )
        probabilities = np.asarray([
            _sigmoid(calibration_intercept + calibration_slope * value)
            for value in holdout_logits
        ])
        probabilities_by_policy[name] = probabilities
        result[name] = {
            "post_policy_calibration": {
                "method": "DEVELOPMENT_ONLY_NONNEGATIVE_PLATT",
                "intercept": round(calibration_intercept, 8),
                "slope": round(calibration_slope, 8),
                "development_targets": len(development),
            },
            "holdout": _metrics(
                targets, probabilities, total_targets=len(holdout),
            ),
            "priority_violations": _priority_violations(contributions),
        }
    baseline = probabilities_by_policy["V11_CONSENSUS_BASELINE"]
    for name, probabilities in probabilities_by_policy.items():
        result[name]["paired_gain_vs_v11"] = _paired_probability_gain(
            targets, baseline, probabilities,
        )

    development_logits, development_contributions = _policy_logits(
        development, model=model, policy=_baseline_policy,
    )
    consensus_intercept, consensus_weights = _fit_consensus_calibration(
        development_logits, development_contributions, development,
    )
    holdout_logits, holdout_contributions = _policy_logits(
        holdout, model=model, policy=_baseline_policy,
    )
    holdout_consensus = _consensus_feature(holdout_contributions)
    consensus_probabilities = np.asarray([
        _sigmoid(
            consensus_intercept
            + consensus_weights[0] * governed_logit
            + consensus_weights[1] * consensus_signal
        )
        for governed_logit, consensus_signal in zip(
            holdout_logits, holdout_consensus, strict=True,
        )
    ])
    consensus_indexes = np.flatnonzero(np.abs(holdout_consensus) > 1e-12)
    consensus_subset = None
    if len(consensus_indexes):
        consensus_subset = {
            "sample": int(len(consensus_indexes)),
            "baseline": _metrics(
                targets[consensus_indexes], baseline[consensus_indexes],
                total_targets=len(consensus_indexes),
            ),
            "candidate": _metrics(
                targets[consensus_indexes],
                consensus_probabilities[consensus_indexes],
                total_targets=len(consensus_indexes),
            ),
            "paired_gain": _paired_probability_gain(
                targets[consensus_indexes], baseline[consensus_indexes],
                consensus_probabilities[consensus_indexes],
            ),
            "favorite_reliability_v11": _favorite_reliability(
                targets, baseline, consensus_indexes,
            ),
        }
    result["CONSENSUS_INTERACTION_CALIBRATION"] = {
        "calibration": {
            "method": "DEVELOPMENT_ONLY_NONNEGATIVE_LOGISTIC_INTERACTION",
            "intercept": round(consensus_intercept, 8),
            "governed_logit_weight": round(float(consensus_weights[0]), 8),
            "unanimous_consensus_weight": round(float(consensus_weights[1]), 8),
            "development_targets": len(development),
        },
        "holdout": _metrics(
            targets, consensus_probabilities, total_targets=len(holdout),
        ),
        "consensus_holdout": consensus_subset,
        "paired_gain_vs_v11": _paired_probability_gain(
            targets, baseline, consensus_probabilities,
        ),
    }
    return {
        "chronology": {
            "development_through": max(
                row["event_date"]
                for row in split["train"] + split["validation"]
            ),
            "holdout_from": min(row["event_date"] for row in split["holdout"]),
            "evaluation_through": max(
                row["event_date"] for row in split["holdout"]
            ),
            "holdout_targets": len(split["holdout"]),
        },
        "policies": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument(
        "--contract", type=Path,
        default=Path("data/models/contextual-family-combination-v11.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    universes = {}
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        universes[universe] = audit_universe(
            rows, universe=universe, contract=contract,
        )
    output = {
        "schema_version": 1,
        "mode": "READ_ONLY_CHRONOLOGICAL_AUDIT",
        "source_model": contract["model_version"],
        "market_used": False,
        "production_effect": False,
        "universes": universes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            name: data["paired_gain_vs_v11"]
            for name, data in audit["policies"].items()
        }
        for universe, audit in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
