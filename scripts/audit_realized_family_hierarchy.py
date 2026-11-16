"""Read-only chronological audit of per-match realized family hierarchy."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

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
    combine_contextual_families_v2,
)
from src.contextual_family_replay import _split
from src.contextual_family_hierarchy import (
    govern_realized_family_contributions,
)


FAMILIES = (
    "recent_form", "structural_strength", "surface_conditions",
    "matchup_h2h", "serve_return",
)


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def _projected_logits(
    rows: list[dict], *, coefficients: dict[str, float], intercept: float,
) -> tuple[np.ndarray, list[dict[str, float | bool]]]:
    logits, audits = [], []
    for row in rows:
        raw = {
            family: (
                float(coefficients[family])
                * _logit(row["family_probabilities"][family])
                if row["family_probabilities"].get(family) is not None else 0.0
            )
            for family in FAMILIES
        }
        governed, audit = govern_realized_family_contributions(raw)
        logits.append(float(intercept) + sum(governed.values()))
        audits.append(audit)
    return np.asarray(logits, dtype=float), audits


def audit_universe(rows: list[dict], *, universe: str) -> dict:
    _augment_pooled_main_features(rows)
    baseline = combine_contextual_families_v2(
        rows,
        universe=universe,
        include_diagnostics=True,
        family_profile_overrides={
            "recent_form": "recent_tier_context_v8",
            "structural_strength": "contextual_v7",
            "surface_conditions": "surface_exact_tier_adjusted_v8",
        },
        model_version="contextual-family-combination-v8-tier-context",
    )
    diagnostics = baseline.pop("_diagnostics")
    holdout_rows = diagnostics["holdout_rows"]
    baseline_probabilities = np.asarray(
        diagnostics["holdout_probabilities"], dtype=float,
    )
    coefficients = baseline["family_coefficients"]
    intercept = float(baseline["intercept"])
    split = _split(rows)
    profiles = _effective_profiles(universe, {
        "recent_form": "recent_tier_context_v8",
        "structural_strength": "contextual_v7",
        "surface_conditions": "surface_exact_tier_adjusted_v8",
    })
    train_models = _fit_family_bundle(
        split["train"],
        universe=universe,
        selected_l1=baseline["family_l1_selected_inside_train"],
        profiles=profiles,
    )
    development_rows = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    development_logits, _ = _projected_logits(
        development_rows, coefficients=coefficients, intercept=intercept,
    )
    development_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in development_rows
    ])
    calibration_intercept, calibration_weights, _ = _fit_logistic_elastic_net(
        development_logits.reshape(-1, 1),
        development_targets,
        l1=0.0,
        l2=1e-6,
        nonnegative_mask=np.asarray([True]),
    )
    holdout_logits, audits = _projected_logits(
        holdout_rows, coefficients=coefficients, intercept=intercept,
    )
    candidate_probabilities = np.asarray([
        _sigmoid(value) for value in holdout_logits
    ])
    calibrated_probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    violations = 0
    for audit in audits:
        if (
            float(audit["secondary_absolute_budget_after"])
            > float(audit["primary_absolute_budget"]) + 1e-9
            or float(audit["largest_secondary_absolute_impact_after"])
            > float(audit["primary_average_absolute_impact"]) + 1e-9
        ):
            violations += 1
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout_rows
    ])
    changed_side = int(np.sum(
        (baseline_probabilities >= 0.5) != (candidate_probabilities >= 0.5)
    ))
    return {
        "universe": universe,
        "holdout_targets": len(holdout_rows),
        "baseline": _metrics(targets, baseline_probabilities, total_targets=len(targets)),
        "candidate": _metrics(targets, candidate_probabilities, total_targets=len(targets)),
        "candidate_affine_calibrated_on_development": _metrics(
            targets, calibrated_probabilities, total_targets=len(targets),
        ),
        "paired_gain_candidate_vs_baseline": _paired_probability_gain(
            targets, baseline_probabilities, candidate_probabilities,
        ),
        "paired_gain_calibrated_candidate_vs_baseline": _paired_probability_gain(
            targets, baseline_probabilities, calibrated_probabilities,
        ),
        "post_hierarchy_calibration": {
            "intercept": round(float(calibration_intercept), 8),
            "slope": round(float(calibration_weights[0]), 8),
            "fitted_on_development_targets": len(development_targets),
        },
        "hierarchy": {
            "rows_contracted": sum(bool(item["applied"]) for item in audits),
            "rows_contracted_pct": round(
                100.0 * sum(bool(item["applied"]) for item in audits)
                / max(1, len(audits)), 2,
            ),
            "violations_after_projection": violations,
            "mean_secondary_scale": round(float(np.mean([
                item["secondary_scale"] for item in audits
            ])), 6),
            "changed_favorite_side": changed_side,
        },
        "market_used": False,
        "production_effect": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "schema_version": 1,
        "change_id": "CHANGE-2026-11-16-211",
        "mode": "READ_ONLY_CHRONOLOGICAL_AUDIT",
        "results": {},
        "market_used": False,
        "production_effect": False,
    }
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        result["results"][universe] = audit_universe(rows, universe=universe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["results"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
