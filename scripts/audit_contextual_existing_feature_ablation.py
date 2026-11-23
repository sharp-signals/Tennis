"""Read-only ablation audit for existing contextual fair-odd inputs.

The audit removes one frozen coefficient at a time from the released family
models and evaluates the untouched chronological holdout.  It never refits a
model, reads market prices, or changes the operational release.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src import contextual_family_calibration as calibration
from src.contextual_family_calibration import _metrics, _paired_probability_gain
from src.contextual_family_combination_v18 import predict_contextual_combination_v18
from src.contextual_family_replay import _split


FEATURES = {
    "recent_opponent_quality": (
        "recent_form", "contextual_recent_win_quality_v1",
    ),
    "recent_tournament_level": (
        "recent_form", "contextual_recent_tier_win_credit_v7",
    ),
    "structural_representative_rank": (
        "structural_strength",
        "contextual_structural_representative_rank_core_v6",
    ),
    "structural_ranking_trajectory": (
        "structural_strength", "contextual_structural_trajectory_margin_v3",
    ),
}
STRUCTURAL_NO_TRAJECTORY_PROFILE = "contextual_v8_atp_no_raw_trajectory"


def _combination_contract(
    release: dict[str, Any], *, universe: str, combination: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model_version": release["components"]["family_combination"],
        "mode": "SHADOW_ONLY",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {universe: combination},
    }


def zero_frozen_feature(
    combination: dict[str, Any], *, family: str, feature: str,
) -> tuple[dict[str, Any], float | None]:
    """Return a copied combination with exactly one coefficient removed."""
    candidate = copy.deepcopy(combination)
    model = candidate["runtime_family_models"][family]
    columns = list(model["columns"])
    if feature not in columns:
        return candidate, None
    index = columns.index(feature)
    original = float(model["weights"][index])
    model["weights"][index] = 0.0
    return candidate, original


def _audit_universe(
    rows: list[dict[str, Any]], *, universe: str, release: dict[str, Any],
) -> dict[str, Any]:
    _augment_pooled_main_features(rows)
    holdout = _split(rows)["holdout"]
    combination = release["universes"][universe]["combination"]
    baseline = np.asarray(predict_contextual_combination_v18(
        holdout,
        universe=universe,
        contract=_combination_contract(
            release, universe=universe, combination=combination,
        ),
    )["probabilities"], dtype=float)
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline_metrics = _metrics(targets, baseline, total_targets=len(holdout))
    features = {}
    for label, (family, feature) in FEATURES.items():
        ablated_contract, coefficient = zero_frozen_feature(
            combination, family=family, feature=feature,
        )
        if coefficient is None:
            features[label] = {
                "status": "FEATURE_NOT_IN_RELEASE",
                "family": family,
                "feature": feature,
            }
            continue
        ablated = np.asarray(predict_contextual_combination_v18(
            holdout,
            universe=universe,
            contract=_combination_contract(
                release, universe=universe, combination=ablated_contract,
            ),
        )["probabilities"], dtype=float)
        ablated_metrics = _metrics(
            targets, ablated, total_targets=len(holdout),
        )
        paired = _paired_probability_gain(targets, baseline, ablated)
        removal_delta = round(
            float(ablated_metrics["log_loss"] - baseline_metrics["log_loss"]),
            6,
        )
        if paired["status"] == "REJECTED":
            decision = "KEEP_FEATURE_SUPPORTED"
        elif paired["status"] == "SUPPORTED":
            decision = "REMOVE_FEATURE_SUPPORTED"
        else:
            decision = "INCONCLUSIVE_KEEP_CURRENT_RELEASE"
        features[label] = {
            "status": "EVALUATED",
            "family": family,
            "feature": feature,
            "frozen_coefficient": coefficient,
            "ablated": ablated_metrics,
            "removal_log_loss_penalty": removal_delta,
            "paired_removal_test": paired,
            "decision": decision,
        }
    return {
        "rows": len(rows),
        "holdout_targets": len(holdout),
        "baseline": baseline_metrics,
        "features": features,
        "refitted_structural_without_trajectory": (
            _refit_structural_without_trajectory(
                rows, holdout=holdout, targets=targets, baseline=baseline,
                universe=universe, release=release, combination=combination,
            )
        ),
    }


def _refit_structural_without_trajectory(
    rows: list[dict[str, Any]], *, holdout: list[dict[str, Any]],
    targets: np.ndarray, baseline: np.ndarray, universe: str,
    release: dict[str, Any], combination: dict[str, Any],
) -> dict[str, Any]:
    """Refit the whole structural family after removing trajectory."""
    model = calibration.calibrate_family(
        _split(rows), family="structural_strength",
        feature_profile=STRUCTURAL_NO_TRAJECTORY_PROFILE,
        allow_missingness_vote=False,
    )
    candidate_combination = copy.deepcopy(combination)
    candidate_combination["runtime_family_models"]["structural_strength"] = (
        calibration._runtime_model(model)
    )
    candidate_combination["family_profiles"]["structural_strength"] = (
        STRUCTURAL_NO_TRAJECTORY_PROFILE
    )
    candidate = np.asarray(predict_contextual_combination_v18(
        holdout,
        universe=universe,
        contract=_combination_contract(
            release, universe=universe, combination=candidate_combination,
        ),
    )["probabilities"], dtype=float)
    candidate_metrics = _metrics(
        targets, candidate, total_targets=len(holdout),
    )
    paired = _paired_probability_gain(targets, baseline, candidate)
    return {
        "profile": STRUCTURAL_NO_TRAJECTORY_PROFILE,
        "active_coefficients": model.get("active_coefficients"),
        "candidate": candidate_metrics,
        "paired_gain": paired,
        "decision": (
            "REMOVE_TRAJECTORY_SUPPORTED"
            if paired["status"] == "SUPPORTED"
            else "REMOVE_TRAJECTORY_REJECTED"
            if paired["status"] == "REJECTED"
            else "INCONCLUSIVE_KEEP_CURRENT_RELEASE"
        ),
    }


def build_report(
    replay_dir: Path, release_path: Path,
) -> dict[str, Any]:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_FROZEN_FEATURE_ABLATION",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {
            universe: _audit_universe(
                _read_replay(replay_dir / f"{universe}.jsonl.gz"),
                universe=universe,
                release=release,
            )
            for universe in ("atp", "wta")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.replay_dir, args.release)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
