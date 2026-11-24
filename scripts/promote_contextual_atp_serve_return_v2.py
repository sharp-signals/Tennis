"""Promote the rolling-refit-supported ATP serve/return profile.

Only the ATP serve/return family is refitted.  The WTA contract is copied
unchanged, and promotion fails closed unless the latest chronological holdout
improves log loss, Brier score and calibration error.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.build_contextual_family_combination_v18 import (
    _fit_zero_intercept_slope,
    _predict,
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
from src.contextual_family_combination_v18 import (
    MODEL_VERSION,
    predict_contextual_combination_v18,
)
from src.contextual_family_replay import _split
from src.stable_json import stabilize_floats


ATP_SERVE_RETURN_PROFILE = "serve_return_points_recent_service_only_v2"


def candidate_profiles(baseline: dict[str, Any]) -> dict[str, str]:
    profiles = dict(baseline["family_profiles"])
    profiles["serve_return"] = ATP_SERVE_RETURN_PROFILE
    return profiles


def _baseline_contract(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "universes": {"atp": model},
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def _promotion_supported(
    paired: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any],
) -> bool:
    return (
        paired.get("status") == "SUPPORTED"
        and float(candidate["brier"]) <= float(baseline["brier"])
        and float(candidate["ece_10"]) <= float(baseline["ece_10"])
    )


def _fit_serve_return(
    rows: list[dict[str, Any]], baseline: dict[str, Any],
) -> dict[str, Any]:
    return fit_family_equation(
        rows,
        family="serve_return",
        feature_profile=ATP_SERVE_RETURN_PROFILE,
        l1=float(baseline["family_l1_selected_inside_train"]["serve_return"]),
        allow_missingness_vote=False,
    )


def build_atp_candidate(
    rows: list[dict[str, Any]], baseline: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _augment_pooled_main_features(rows)
    split = _split(rows)
    profiles = candidate_profiles(baseline)

    validation_model = copy.deepcopy(baseline)
    validation_model["family_profiles"] = profiles
    validation_model["runtime_family_models"]["serve_return"] = (
        _fit_serve_return(split["train"], baseline)
    )
    hierarchy = baseline["realized_hierarchy"]
    recent = hierarchy["recent_form_governance"]
    validation_raw = _predict(
        split["validation"], validation_model, universe="atp",
        h2h_multiplier=float(hierarchy["h2h_multiplier"]), slope=1.0,
        result_weight_floor=float(recent["result_weight_floor"]),
        opposing_modifier_cap=float(recent["opposing_modifier_cap"]),
        unanimous_policy=str(hierarchy["unanimous_policy"]),
    )
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["validation"]
    ])
    validation_logits = np.log(
        np.clip(validation_raw, 1e-9, 1.0)
        / np.clip(1.0 - validation_raw, 1e-9, 1.0)
    )
    slope = _fit_zero_intercept_slope(validation_logits, validation_targets)

    candidate = copy.deepcopy(baseline)
    candidate["family_profiles"] = profiles
    candidate["runtime_family_models"]["serve_return"] = _fit_serve_return(
        split["train"] + split["validation"], baseline,
    )
    candidate["realized_hierarchy"]["post_hierarchy_calibration"] = {
        "method": "ZERO_INTERCEPT_NONNEGATIVE_PLATT",
        "intercept": 0.0,
        "slope": round(float(slope), 8),
        "development_targets": len(validation_targets),
    }

    holdout_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["holdout"]
    ])
    baseline_probability = np.asarray(predict_contextual_combination_v18(
        split["holdout"], universe="atp", contract=_baseline_contract(baseline),
    )["probabilities"], dtype=float)
    candidate_probability = _predict(
        split["holdout"], candidate, universe="atp",
        h2h_multiplier=float(hierarchy["h2h_multiplier"]), slope=slope,
        result_weight_floor=float(recent["result_weight_floor"]),
        opposing_modifier_cap=float(recent["opposing_modifier_cap"]),
        unanimous_policy=str(hierarchy["unanimous_policy"]),
    )
    baseline_metrics = _metrics(
        holdout_targets, baseline_probability, total_targets=len(holdout_targets),
    )
    candidate_metrics = _metrics(
        holdout_targets, candidate_probability, total_targets=len(holdout_targets),
    )
    paired = _paired_probability_gain(
        holdout_targets, baseline_probability, candidate_probability,
    )
    audit = {
        "profile": ATP_SERVE_RETURN_PROFILE,
        "removed_feature": "return_points_won_recent_deviation_v1",
        "validation_slope": round(float(slope), 8),
        "holdout_targets": len(holdout_targets),
        "baseline": baseline_metrics,
        "candidate": candidate_metrics,
        "paired_gain": paired,
        "market_used": False,
    }
    if not _promotion_supported(paired, baseline_metrics, candidate_metrics):
        raise RuntimeError("ATP_SERVE_RETURN_V2_PROMOTION_NOT_SUPPORTED")
    candidate["status"] = "ATP_SERVE_RETURN_V2_CHRONOLOGICALLY_SUPPORTED"
    candidate["realized_hierarchy"]["atp_serve_return_v2_audit"] = audit
    candidate["holdout"]["atp_serve_return_v2"] = candidate_metrics
    candidate["holdout"]["serve_return_paired_gain_vs_previous"] = paired
    return candidate, audit


def build_contract(
    replay_dir: Path, baseline_path: Path, frozen_wta_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_contract = json.loads(baseline_path.read_text(encoding="utf-8"))
    frozen_contract = json.loads(frozen_wta_path.read_text(encoding="utf-8"))
    if (
        baseline_contract.get("model_version") != MODEL_VERSION
        or frozen_contract.get("model_version") != MODEL_VERSION
    ):
        raise ValueError("expected contextual combination v18 contracts")
    atp, audit = build_atp_candidate(
        _read_replay(replay_dir / "atp.jsonl.gz"),
        baseline_contract["universes"]["atp"],
    )
    contract = copy.deepcopy(baseline_contract)
    contract["universes"]["atp"] = atp
    frozen_wta = frozen_contract["universes"]["wta"]
    contract["universes"]["wta"] = copy.deepcopy(frozen_wta)
    if contract["universes"]["wta"] != frozen_wta:
        raise RuntimeError("WTA_CONTRACT_CHANGED_DURING_ATP_SERVE_PROMOTION")
    return stabilize_floats(contract), audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--frozen-wta-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract, audit = build_contract(
        args.replay_dir, args.baseline, args.frozen_wta_contract,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
