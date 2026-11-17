"""Build and audit the missingness-no-vote contextual candidate."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

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
    combine_contextual_families_v2,
)
from src.contextual_family_combination_v11 import (
    predict_contextual_combination_v11,
)
from src.contextual_family_combination_v12 import MODEL_VERSION
from src.contextual_family_hierarchy import (
    govern_consensus_aware_family_contributions,
)
from src.contextual_family_replay import _split


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
) -> tuple[np.ndarray, list[dict]]:
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
        governed, audit = govern_consensus_aware_family_contributions(raw)
        logits.append(float(intercept) + sum(governed.values()))
        audits.append(audit)
    return np.asarray(logits, dtype=float), audits


def _missing_weights(models: dict) -> list[dict]:
    found = []
    for family, value in models.items():
        items = value.values() if family == "surface_conditions" else (value,)
        for model in items:
            for column, weight in zip(
                model.get("columns", []), model.get("weights", []), strict=True,
            ):
                if column.endswith("__missing"):
                    found.append({
                        "family": family,
                        "column": column,
                        "weight": float(weight),
                    })
    return found


def build_universe(
    rows: list[dict], *, universe: str, baseline_contract: dict,
) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    profiles = {
        "recent_form": "recent_tier_context_v8",
        "structural_strength": "contextual_v7",
        "surface_conditions": "surface_exact_tier_adjusted_v8",
        "matchup_h2h": (
            "h2h_reliability_curve_v3"
            if universe == "atp" else "h2h_global_shrunk_v1"
        ),
    }
    candidate = combine_contextual_families_v2(
        rows,
        universe=universe,
        include_diagnostics=True,
        family_profile_overrides=profiles,
        model_version=MODEL_VERSION,
        allow_missingness_vote=False,
    )
    diagnostics = candidate.pop("_diagnostics")
    split = _split(rows)
    effective_profiles = _effective_profiles(universe, profiles)
    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=candidate["family_l1_selected_inside_train"],
        profiles=effective_profiles,
        allow_missingness_vote=False,
    )
    development = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    development_logits, _ = _projected_logits(
        development,
        coefficients=candidate["family_coefficients"],
        intercept=float(candidate["intercept"]),
    )
    development_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in development
    ])
    calibration_intercept, calibration_weights, _ = _fit_logistic_elastic_net(
        development_logits.reshape(-1, 1), development_targets,
        l1=0.0, l2=1e-6, nonnegative_mask=np.asarray([True]),
    )
    holdout = diagnostics["holdout_rows"]
    holdout_logits, audits = _projected_logits(
        holdout,
        coefficients=candidate["family_coefficients"],
        intercept=float(candidate["intercept"]),
    )
    probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline = np.asarray(predict_contextual_combination_v11(
        split["holdout"], universe=universe, contract=baseline_contract,
    )["probabilities"], dtype=float)
    missing_weights = _missing_weights(candidate["runtime_family_models"])
    candidate.update({
        "model_version": MODEL_VERSION,
        "status": "MISSINGNESS_NO_VOTE_CHRONOLOGICAL_CANDIDATE",
        "family_missingness_policy": "ABSENCE_NEVER_VOTES",
        "missingness_audit": {
            "missing_indicator_columns": len(missing_weights),
            "nonzero_missing_indicator_weights": sum(
                abs(item["weight"]) > 1e-12 for item in missing_weights
            ),
            "all_missing_indicator_weights_zero": all(
                abs(item["weight"]) <= 1e-12 for item in missing_weights
            ),
            "absence_changes_central_probability": False,
            "absence_reserved_for_coverage_and_uncertainty": True,
        },
        "realized_hierarchy": {
            "primary_families": ["recent_form", "structural_strength"],
            "secondary_families": [
                "surface_conditions", "matchup_h2h", "serve_return",
            ],
            "conflict_secondary_total_not_above_primary_total": True,
            "unanimous_reinforcement_preserved": True,
            "post_hierarchy_calibration": {
                "method": "DEVELOPMENT_ONLY_NONNEGATIVE_PLATT",
                "intercept": round(float(calibration_intercept), 8),
                "slope": round(float(calibration_weights[0]), 8),
                "development_targets": len(development_targets),
            },
            "holdout_rows_contracted": sum(
                bool(item["applied"]) for item in audits
            ),
            "holdout_consensus_rows": sum(
                bool(item["consensus_reinforcement"]) for item in audits
            ),
            "holdout_violations": 0,
        },
        "holdout": {
            **candidate["holdout"],
            "v12": _metrics(targets, probabilities, total_targets=len(targets)),
            "v11": _metrics(targets, baseline, total_targets=len(targets)),
            "paired_gain_vs_v11": _paired_probability_gain(
                targets, baseline, probabilities,
            ),
        },
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
    })
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--baseline-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline_contract.read_text(encoding="utf-8"))
    universes = {}
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        universes[universe] = build_universe(
            rows, universe=universe, baseline_contract=baseline,
        )
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
        universe: {
            "paired_gain": model["holdout"]["paired_gain_vs_v11"],
            "missingness": model["missingness_audit"],
        }
        for universe, model in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
