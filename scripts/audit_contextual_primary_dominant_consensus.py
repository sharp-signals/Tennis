"""Rolling exploratory A/B for primary-dominant unanimous consensus.

The interaction was identified in a post-selection diagnostic, so a positive
result cannot promote production.  Parameters are still learned on validation
only and evaluated on later chronological test windows.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.audit_contextual_low_consensus_candidates import (
    _candidate_features,
    _favorite_segment,
    _fit_nonnegative_logistic,
    _prediction_rows,
    _sigmoid,
)
from scripts.audit_contextual_rolling_refit_v1 import rolling_splits
from scripts.build_contextual_family_combination_v17 import (
    _fit_zero_intercept_slope,
)
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    _metrics,
    _paired_probability_gain,
)
from src.contextual_family_combination_v2 import _fit_family_bundle


DEFAULT_MODEL = Path("data/models/fenzobot-contextual-2026-11.json")


def _exploratory_decision(
    overall_gain: dict[str, Any], focused: dict[str, Any],
    fold_focused_gains: list[float], baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    focused_gain = focused.get("paired_gain") or {}
    positive_folds = sum(value > 0.0 for value in fold_focused_gains)
    negative_folds = sum(value < 0.0 for value in fold_focused_gains)
    brier_not_worse = float(candidate["brier"]) <= float(baseline["brier"])
    calibration_not_worse = (
        float(candidate["ece_10"]) <= float(baseline["ece_10"])
    )
    if (
        focused_gain.get("status") == "SUPPORTED"
        and overall_gain.get("status") != "REJECTED"
        and float(overall_gain.get("log_loss_gain") or 0.0) >= 0.0
        and positive_folds >= 2
        and brier_not_worse
        and calibration_not_worse
    ):
        return "EXPLORATORY_SUPPORTED_REQUIRES_PROSPECTIVE_CONFIRMATION"
    if (
        focused_gain.get("status") == "REJECTED"
        or overall_gain.get("status") == "REJECTED"
        or negative_folds >= 2
    ):
        return "EXPLORATORY_CANDIDATE_REJECTED"
    return "INCONCLUSIVE_NO_PRODUCTION_CHANGE"


def _fit_fold(
    fold: dict[str, Any], *, universe: str, combination: dict[str, Any],
) -> dict[str, Any]:
    family_models = _fit_family_bundle(
        fold["train"], universe=universe,
        selected_l1=combination["family_l1_selected_inside_train"],
        profiles=combination["family_profiles"],
        allow_missingness_vote=False,
    )
    model = copy.deepcopy(combination)
    model["runtime_family_models"] = family_models

    validation_rows = _prediction_rows(
        fold["validation"], model, universe=universe,
    )
    initial_validation = _candidate_features(
        validation_rows, baseline_slope=1.0,
    )
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in fold["validation"]
    ], dtype=float)
    baseline_slope = _fit_zero_intercept_slope(
        initial_validation["base_logit"], validation_targets,
    )
    validation_features = _candidate_features(
        validation_rows, baseline_slope=baseline_slope,
    )
    candidate_weights = _fit_nonnegative_logistic(
        np.column_stack((
            validation_features["base_logit"],
            validation_features["primary_dominant_bonus_feature"],
        )),
        validation_targets,
    )

    test_rows = _prediction_rows(fold["test"], model, universe=universe)
    test_features = _candidate_features(
        test_rows, baseline_slope=baseline_slope,
    )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in fold["test"]
    ], dtype=float)
    baseline_probability = _sigmoid(
        baseline_slope * test_features["base_logit"]
    )
    candidate_probability = _sigmoid(
        np.column_stack((
            test_features["base_logit"],
            test_features["primary_dominant_bonus_feature"],
        )) @ candidate_weights
    )
    focused = _favorite_segment(
        targets, baseline_probability, candidate_probability,
        test_features["primary_dominant_mask"],
    )
    return {
        "name": fold["name"],
        "test_from": fold["test"][0]["event_date"],
        "test_through": fold["test"][-1]["event_date"],
        "test_targets": len(targets),
        "validation_primary_dominant_targets": int(
            validation_features["primary_dominant_mask"].sum()
        ),
        "test_primary_dominant_targets": int(
            test_features["primary_dominant_mask"].sum()
        ),
        "baseline_slope": round(float(baseline_slope), 8),
        "candidate_base_slope": round(float(candidate_weights[0]), 8),
        "candidate_logit_bonus": round(float(candidate_weights[1]), 8),
        "baseline": _metrics(
            targets, baseline_probability, total_targets=len(targets),
        ),
        "candidate": _metrics(
            targets, candidate_probability, total_targets=len(targets),
        ),
        "paired_gain_overall": _paired_probability_gain(
            targets, baseline_probability, candidate_probability,
        ),
        "primary_dominant_segment": focused,
        "_targets": targets,
        "_baseline_probability": baseline_probability,
        "_candidate_probability": candidate_probability,
        "_focused_mask": test_features["primary_dominant_mask"],
    }


def audit_universe(
    rows: list[dict[str, Any]], *, universe: str, release: dict[str, Any],
) -> dict[str, Any]:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    combination = release["universes"][universe]["combination"]
    internal_folds = [
        _fit_fold(fold, universe=universe, combination=combination)
        for fold in rolling_splits(rows)
    ]
    targets = np.concatenate([fold["_targets"] for fold in internal_folds])
    baseline_probability = np.concatenate([
        fold["_baseline_probability"] for fold in internal_folds
    ])
    candidate_probability = np.concatenate([
        fold["_candidate_probability"] for fold in internal_folds
    ])
    focused_mask = np.concatenate([
        fold["_focused_mask"] for fold in internal_folds
    ])
    baseline_metrics = _metrics(
        targets, baseline_probability, total_targets=len(targets),
    )
    candidate_metrics = _metrics(
        targets, candidate_probability, total_targets=len(targets),
    )
    overall_gain = _paired_probability_gain(
        targets, baseline_probability, candidate_probability,
    )
    focused = _favorite_segment(
        targets, baseline_probability, candidate_probability, focused_mask,
    )
    fold_focused_gains = [
        float(fold["primary_dominant_segment"]["paired_gain"]["log_loss_gain"])
        if int(fold["primary_dominant_segment"].get("sample") or 0) else 0.0
        for fold in internal_folds
    ]
    public_folds = [
        {key: value for key, value in fold.items() if not key.startswith("_")}
        for fold in internal_folds
    ]
    return {
        "source_rows": len(rows),
        "rolling_test_targets": len(targets),
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "paired_gain_overall": overall_gain,
        "primary_dominant_segment": focused,
        "fold_primary_dominant_log_loss_gains": fold_focused_gains,
        "folds": public_folds,
        "decision": _exploratory_decision(
            overall_gain, focused, fold_focused_gains,
            baseline_metrics, candidate_metrics,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.model.read_text(encoding="utf-8"))
    audit = {
        "schema_version": 1,
        "mode": "POST_SELECTION_EXPLORATORY_PRIMARY_DOMINANT_A_B",
        "model_version": release["global_release_id"],
        "configuration_fingerprint": release["configuration_fingerprint"],
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "post_selection_hypothesis": True,
        "prospective_confirmation_required": True,
        "candidate_parameters_fit_on_validation_only": True,
        "universes": {
            universe: audit_universe(
                _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz"),
                universe=universe, release=release,
            )
            for universe in ("atp", "wta")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: payload["decision"]
        for universe, payload in audit["universes"].items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
