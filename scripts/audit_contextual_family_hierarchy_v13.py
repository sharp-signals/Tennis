"""Compare realised family-hierarchy policies on the chronological replay."""

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
    _fit_family_bundle,
)
from src.contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    SECONDARY_FAMILIES,
    govern_consensus_with_individual_cap,
    govern_consensus_aware_family_contributions,
    govern_realized_family_contributions,
)
from src.contextual_family_replay import _split


FAMILIES = (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
Governor = Callable[[dict[str, float]], tuple[dict[str, float], dict]]


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def _coefficient_aware_governor(
    coefficients: dict[str, float],
) -> Governor:
    """Keep realised secondary impact within its learned hierarchy share."""
    primary_coefficient_total = sum(
        abs(float(coefficients[family])) for family in PRIMARY_FAMILIES
    )
    secondary_shares = {
        family: (
            abs(float(coefficients[family])) / primary_coefficient_total
            if primary_coefficient_total > 0.0 else 0.0
        )
        for family in SECONDARY_FAMILIES
    }

    def govern(
        contributions: dict[str, float],
    ) -> tuple[dict[str, float], dict]:
        governed = {
            family: float(contributions.get(family, 0.0))
            for family in FAMILIES
        }
        primary_budget = sum(
            abs(governed[family]) for family in PRIMARY_FAMILIES
        )
        secondary_before = sum(
            abs(governed[family]) for family in SECONDARY_FAMILIES
        )
        capped_families: list[str] = []
        for family in SECONDARY_FAMILIES:
            limit = primary_budget * secondary_shares[family]
            value = governed[family]
            if abs(value) > limit:
                governed[family] = math.copysign(limit, value)
                capped_families.append(family)
        secondary_after = sum(
            abs(governed[family]) for family in SECONDARY_FAMILIES
        )
        return governed, {
            "applied": bool(capped_families),
            "policy": "COEFFICIENT_AWARE_REALISED_HIERARCHY",
            "primary_absolute_budget": primary_budget,
            "secondary_absolute_budget_before": secondary_before,
            "secondary_absolute_budget_after": secondary_after,
            "secondary_to_primary_ratio_after": (
                secondary_after / primary_budget if primary_budget > 0.0 else 0.0
            ),
            "secondary_family_shares": secondary_shares,
            "capped_families": capped_families,
        }

    return govern


def _ratio_cap_governor(secondary_total_ratio: float) -> Governor:
    """Cap each secondary by the primary average and their block by a ratio."""

    def govern(
        contributions: dict[str, float],
    ) -> tuple[dict[str, float], dict]:
        governed = {
            family: float(contributions.get(family, 0.0))
            for family in FAMILIES
        }
        primary_budget = sum(
            abs(governed[family]) for family in PRIMARY_FAMILIES
        )
        primary_average = primary_budget / len(PRIMARY_FAMILIES)
        secondary_before = sum(
            abs(governed[family]) for family in SECONDARY_FAMILIES
        )
        largest_secondary = max(
            (abs(governed[family]) for family in SECONDARY_FAMILIES),
            default=0.0,
        )
        scale = 1.0
        if secondary_before > 0.0:
            if primary_budget <= 0.0:
                scale = 0.0
            else:
                if largest_secondary > primary_average:
                    scale = min(scale, primary_average / largest_secondary)
                total_limit = secondary_total_ratio * primary_budget
                if secondary_before > total_limit:
                    scale = min(scale, total_limit / secondary_before)
        for family in SECONDARY_FAMILIES:
            governed[family] *= scale
        secondary_after = sum(
            abs(governed[family]) for family in SECONDARY_FAMILIES
        )
        return governed, {
            "applied": scale < 1.0 - 1e-12,
            "policy": "RATIO_CAPPED_REALISED_HIERARCHY",
            "secondary_total_ratio_limit": secondary_total_ratio,
            "secondary_scale": scale,
            "primary_absolute_budget": primary_budget,
            "secondary_absolute_budget_before": secondary_before,
            "secondary_absolute_budget_after": secondary_after,
        }

    return govern


def _raw_contributions(row: dict, coefficients: dict[str, float]) -> dict[str, float]:
    return {
        family: (
            float(coefficients[family])
            * _logit(row["family_probabilities"][family])
            if row["family_probabilities"].get(family) is not None else 0.0
        )
        for family in FAMILIES
    }


def _governed_logits(
    rows: list[dict], *, coefficients: dict[str, float], intercept: float,
    governor: Governor,
) -> tuple[np.ndarray, list[dict]]:
    logits: list[float] = []
    audits: list[dict] = []
    for row in rows:
        governed, audit = governor(_raw_contributions(row, coefficients))
        logits.append(float(intercept) + sum(governed.values()))
        audits.append(audit)
    return np.asarray(logits, dtype=float), audits


def _evaluate_policy(
    *, validation: list[dict], holdout: list[dict],
    coefficients: dict[str, float], intercept: float, governor: Governor,
) -> tuple[dict, np.ndarray]:
    validation_logits, validation_audits = _governed_logits(
        validation, coefficients=coefficients, intercept=intercept,
        governor=governor,
    )
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in validation
    ])
    calibration_intercept, calibration_weights, _ = _fit_logistic_elastic_net(
        validation_logits.reshape(-1, 1), validation_targets,
        l1=0.0, l2=1e-6, nonnegative_mask=np.asarray([True]),
    )
    holdout_logits, audits = _governed_logits(
        holdout, coefficients=coefficients, intercept=intercept,
        governor=governor,
    )
    probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    validation_probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in validation_logits
    ])
    return {
        "validation_metrics": _metrics(
            validation_targets, validation_probabilities,
            total_targets=len(validation_targets),
        ),
        "metrics": _metrics(targets, probabilities, total_targets=len(targets)),
        "calibration": {
            "intercept": round(float(calibration_intercept), 8),
            "slope": round(float(calibration_weights[0]), 8),
        },
        "rows_contracted": sum(bool(item.get("applied")) for item in audits),
        "rows_contracted_pct": round(
            100.0 * sum(bool(item.get("applied")) for item in audits)
            / max(1, len(audits)), 2,
        ),
        "validation_rows_contracted": sum(
            bool(item.get("applied")) for item in validation_audits
        ),
    }, probabilities


def audit_universe(rows: list[dict], *, universe: str, model: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    selected_l1 = model["family_l1_selected_inside_train"]
    profiles = model["family_profiles"]
    train_models = _fit_family_bundle(
        split["train"], universe=universe, selected_l1=selected_l1,
        profiles=profiles, allow_missingness_vote=False,
    )
    final_models = _fit_family_bundle(
        split["train"] + split["validation"], universe=universe,
        selected_l1=selected_l1, profiles=profiles,
        allow_missingness_vote=False,
    )
    validation = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    holdout = _attach_predictions(
        split["holdout"], final_models, universe=universe,
    )
    coefficients = model["family_coefficients"]
    intercept = float(model["intercept"])
    policies: dict[str, Governor] = {
        "current_consensus_aware": govern_consensus_aware_family_contributions,
        "consensus_individual_cap": govern_consensus_with_individual_cap,
        "ratio_cap_100": govern_realized_family_contributions,
        "ratio_cap_90": _ratio_cap_governor(0.9),
        "ratio_cap_80": _ratio_cap_governor(0.8),
        "ratio_cap_70": _ratio_cap_governor(0.7),
        "ratio_cap_60": _ratio_cap_governor(0.6),
        "coefficient_aware": _coefficient_aware_governor(coefficients),
    }
    results: dict[str, dict] = {}
    probabilities: dict[str, np.ndarray] = {}
    for name, governor in policies.items():
        results[name], probabilities[name] = _evaluate_policy(
            validation=validation, holdout=holdout,
            coefficients=coefficients, intercept=intercept, governor=governor,
        )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline = probabilities["current_consensus_aware"]
    for name in policies:
        if name == "current_consensus_aware":
            continue
        results[name]["paired_gain_vs_current"] = _paired_probability_gain(
            targets, baseline, probabilities[name],
        )
        results[name]["changed_favorite_side"] = int(np.sum(
            (baseline >= 0.5) != (probabilities[name] >= 0.5)
        ))
        results[name]["mean_absolute_probability_change_pp"] = round(
            100.0 * float(np.mean(np.abs(probabilities[name] - baseline))), 4,
        )
    selected_name = min(
        (name for name in policies if name != "current_consensus_aware"),
        key=lambda name: results[name]["validation_metrics"]["log_loss"],
    )
    return {
        "universe": universe,
        "holdout_targets": len(holdout),
        "family_coefficients": coefficients,
        "selected_on_validation": selected_name,
        "policies": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = {
        "schema_version": 1,
        "mode": "READ_ONLY_CHRONOLOGICAL_AUDIT",
        "market_used": False,
        "production_effect": False,
        "results": {},
    }
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        result["results"][universe] = audit_universe(
            rows, universe=universe, model=contract["universes"][universe],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["results"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
