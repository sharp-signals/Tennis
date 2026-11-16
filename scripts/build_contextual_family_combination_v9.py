"""Build and audit the realized-impact hierarchy candidate chronologically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from scripts.audit_realized_family_hierarchy import (
    _projected_logits,
    _sigmoid,
)
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
from src.contextual_family_combination_v9 import MODEL_VERSION
from src.contextual_family_replay import _split


def build_universe(rows: list[dict], *, universe: str) -> dict:
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
        development_rows,
        coefficients=baseline["family_coefficients"],
        intercept=float(baseline["intercept"]),
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
    holdout_rows = diagnostics["holdout_rows"]
    holdout_logits, audits = _projected_logits(
        holdout_rows,
        coefficients=baseline["family_coefficients"],
        intercept=float(baseline["intercept"]),
    )
    candidate = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    original = np.asarray(diagnostics["holdout_probabilities"], dtype=float)
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout_rows
    ])
    baseline.update({
        "model_version": MODEL_VERSION,
        "status": "REALIZED_HIERARCHY_GOVERNED",
        "mode": "REALIZED_HIERARCHY_OUT_OF_SAMPLE_STACK",
        "realized_hierarchy": {
            "primary_families": ["recent_form", "structural_strength"],
            "secondary_families": [
                "surface_conditions", "matchup_h2h", "serve_return",
            ],
            "single_secondary_not_above_primary_average": True,
            "secondary_total_not_above_primary_total": True,
            "post_hierarchy_calibration": {
                "method": "DEVELOPMENT_ONLY_NONNEGATIVE_PLATT",
                "intercept": round(float(calibration_intercept), 8),
                "slope": round(float(calibration_weights[0]), 8),
                "development_targets": len(development_targets),
            },
            "holdout_rows_contracted": sum(
                bool(item["applied"]) for item in audits
            ),
            "holdout_violations": 0,
        },
        "holdout": {
            **baseline["holdout"],
            "v8_baseline": _metrics(
                targets, original, total_targets=len(targets),
            ),
            "realized_hierarchy_candidate": _metrics(
                targets, candidate, total_targets=len(targets),
            ),
            "paired_gain_vs_v8": _paired_probability_gain(
                targets, original, candidate,
            ),
        },
        "chronology": {
            "development_through": max(
                row["event_date"] for row in split["train"] + split["validation"]
            ),
            "holdout_from": min(row["event_date"] for row in split["holdout"]),
            "evaluation_through": max(
                row["event_date"] for row in split["holdout"]
            ),
            "holdout_targets": len(split["holdout"]),
        },
    })
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    universes = {}
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        universes[universe] = build_universe(rows, universe=universe)
    contract = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "universes": universes,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        key: value["holdout"]["paired_gain_vs_v8"]
        for key, value in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
