"""Rolling, market-free audit of the active-year typical-rank residual."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.audit_contextual_rolling_refit_v1 import (
    _calibrated_prediction,
    _decision,
    rolling_splits,
)
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    _metrics,
    _paired_probability_gain,
    fit_family_equation,
)
from src.contextual_family_combination_v2 import _fit_family_bundle


CANDIDATE_FEATURE = "contextual_structural_typical_rank_residual_v8"
BASELINE_PROFILES = {
    "atp": "contextual_v8_atp_no_raw_trajectory",
    "wta": "contextual_v7",
}
CANDIDATE_PROFILES = {
    "atp": "contextual_v9_atp_typical_rank_residual_audit",
    "wta": "contextual_v8_wta_typical_rank_residual_audit",
}


def _residual_segments(
    rows: list[dict], targets: np.ndarray,
    baseline: np.ndarray, candidate: np.ndarray,
) -> dict[str, Any]:
    buckets: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        features = row.get("features") or {}
        value = features.get(CANDIDATE_FEATURE)
        if value is None:
            labels = ("unavailable",)
        else:
            magnitude = abs(float(value))
            if magnitude <= 0.05:
                strength = "near_zero_le_0_05"
            elif magnitude < 0.25:
                strength = "small_0_05_to_0_25"
            elif magnitude < 0.75:
                strength = "material_0_25_to_0_75"
            else:
                strength = "large_ge_0_75"
            current = features.get(
                "contextual_structural_material_rank_core_v6"
            )
            disagreement = (
                current is not None and abs(float(current)) > 1e-12
                and float(value) * float(current) < 0.0
            )
            labels = (
                strength,
                "opposes_current_rank" if disagreement
                else "does_not_oppose_current_rank",
            )
        for label in labels:
            buckets.setdefault(label, []).append(index)

    result = {}
    for label, indexes in buckets.items():
        selected = np.asarray(indexes, dtype=int)
        result[label] = {
            "targets": len(indexes),
            "baseline": _metrics(
                targets[selected], baseline[selected], total_targets=len(indexes),
            ),
            "candidate": _metrics(
                targets[selected], candidate[selected], total_targets=len(indexes),
            ),
            "paired_gain": _paired_probability_gain(
                targets[selected], baseline[selected], candidate[selected],
            ),
        }
    return result


def audit_universe(rows: list[dict], *, universe: str, release: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    combination = release["universes"][universe]["combination"]
    baseline_profile = combination["family_profiles"]["structural_strength"]
    expected = BASELINE_PROFILES[universe]
    if baseline_profile != expected:
        raise RuntimeError(
            f"TYPICAL_RANK_BASELINE_PROFILE_MISMATCH:{universe}:"
            f"{baseline_profile}:{expected}"
        )

    fold_results = []
    aggregate_rows: list[dict] = []
    aggregate_targets: list[float] = []
    aggregate_baseline: list[float] = []
    aggregate_candidate: list[float] = []
    for fold in rolling_splits(rows):
        baseline_models = _fit_family_bundle(
            fold["train"], universe=universe,
            selected_l1=combination["family_l1_selected_inside_train"],
            profiles=combination["family_profiles"],
            allow_missingness_vote=False,
        )
        baseline_model = copy.deepcopy(combination)
        baseline_model["runtime_family_models"] = baseline_models
        baseline, baseline_slope = _calibrated_prediction(
            fold["validation"], fold["test"], baseline_model,
            universe=universe,
        )

        candidate_models = copy.deepcopy(baseline_models)
        candidate_models["structural_strength"] = fit_family_equation(
            fold["train"], family="structural_strength",
            feature_profile=CANDIDATE_PROFILES[universe],
            l1=float(combination["family_l1_selected_inside_train"][
                "structural_strength"
            ]),
            allow_missingness_vote=False,
        )
        structural_model = candidate_models["structural_strength"]
        candidate_model = copy.deepcopy(combination)
        candidate_model["runtime_family_models"] = candidate_models
        candidate, candidate_slope = _calibrated_prediction(
            fold["validation"], fold["test"], candidate_model,
            universe=universe,
        )
        targets = np.asarray([
            1.0 if row["target_a_win"] else 0.0 for row in fold["test"]
        ])
        aggregate_rows.extend(fold["test"])
        aggregate_targets.extend(targets)
        aggregate_baseline.extend(baseline)
        aggregate_candidate.extend(candidate)
        fold_results.append({
            "name": fold["name"],
            "targets": len(targets),
            "baseline_slope": round(float(baseline_slope), 8),
            "candidate_slope": round(float(candidate_slope), 8),
            "candidate_structural_model": {
                "status": structural_model.get("status"),
                "feature_available": structural_model.get(
                    "preprocessor", {}
                ).get("features", {}).get(CANDIDATE_FEATURE, {}).get(
                    "available"
                ),
                "columns": structural_model.get("columns"),
                "weights": structural_model.get("weights"),
            },
            "paired_gain": _paired_probability_gain(
                targets, baseline, candidate,
            ),
        })

    targets = np.asarray(aggregate_targets)
    baseline = np.asarray(aggregate_baseline)
    candidate = np.asarray(aggregate_candidate)
    baseline_metrics = _metrics(
        targets, baseline, total_targets=len(targets),
    )
    candidate_metrics = _metrics(
        targets, candidate, total_targets=len(targets),
    )
    paired = _paired_probability_gain(targets, baseline, candidate)
    fold_gains = [
        float(item["paired_gain"]["log_loss_gain"]) for item in fold_results
    ]
    return {
        "source_rows": len(rows),
        "rolling_test_targets": len(targets),
        "baseline_profile": baseline_profile,
        "candidate_profile": CANDIDATE_PROFILES[universe],
        "candidate_feature": CANDIDATE_FEATURE,
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "paired_gain": paired,
        "fold_log_loss_gains": fold_gains,
        "folds": fold_results,
        "diagnostics": _residual_segments(
            aggregate_rows, targets, baseline, candidate,
        ),
        "decision": _decision(
            paired, fold_gains, baseline_metrics, candidate_metrics,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.release.read_text(encoding="utf-8"))
    report = {
        "schema_version": 1,
        "mode": "READ_ONLY_TYPICAL_RANK_ROLLING_REFIT_AUDIT",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {
            universe: audit_universe(
                _read_replay(args.replay_dir / f"{universe}.jsonl.gz"),
                universe=universe, release=release,
            )
            for universe in ("atp", "wta")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: result["decision"]
        for universe, result in report["universes"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
