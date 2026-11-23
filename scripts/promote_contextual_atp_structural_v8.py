"""Promote the validated ATP structural profile inside combination v18.

The combination algorithm and realised hierarchy remain v18.  Only the ATP
structural family is refitted without the raw trajectory component.  WTA is
copied byte-for-byte at the object level.  Promotion fails closed unless the
paired chronological holdout supports the candidate.
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
from src.contextual_family_calibration import _metrics, _paired_probability_gain
from src.contextual_family_combination_v2 import _fit_family_bundle
from src.contextual_family_combination_v18 import (
    MODEL_VERSION,
    predict_contextual_combination_v18,
)
from src.contextual_family_replay import _split
from src.stable_json import stabilize_floats


ATP_STRUCTURAL_PROFILE = "contextual_v8_atp_no_raw_trajectory"


def candidate_profiles(baseline: dict[str, Any]) -> dict[str, str]:
    profiles = dict(baseline["family_profiles"])
    profiles["structural_strength"] = ATP_STRUCTURAL_PROFILE
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


def build_atp_candidate(
    rows: list[dict[str, Any]], baseline: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _augment_pooled_main_features(rows)
    split = _split(rows)
    profiles = candidate_profiles(baseline)
    selected_l1 = baseline["family_l1_selected_inside_train"]
    train_models = _fit_family_bundle(
        split["train"], universe="atp", selected_l1=selected_l1,
        profiles=profiles, allow_missingness_vote=False,
    )
    validation_model = copy.deepcopy(baseline)
    validation_model["family_profiles"] = profiles
    validation_model["runtime_family_models"]["structural_strength"] = (
        train_models["structural_strength"]
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

    development = split["train"] + split["validation"]
    final_models = _fit_family_bundle(
        development, universe="atp", selected_l1=selected_l1,
        profiles=profiles, allow_missingness_vote=False,
    )
    candidate = copy.deepcopy(baseline)
    candidate["family_profiles"] = profiles
    candidate["runtime_family_models"]["structural_strength"] = (
        final_models["structural_strength"]
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
    paired = _paired_probability_gain(
        holdout_targets, baseline_probability, candidate_probability,
    )
    audit = {
        "profile": ATP_STRUCTURAL_PROFILE,
        "validation_slope": round(float(slope), 8),
        "holdout_targets": len(holdout_targets),
        "baseline": _metrics(
            holdout_targets, baseline_probability,
            total_targets=len(holdout_targets),
        ),
        "candidate": _metrics(
            holdout_targets, candidate_probability,
            total_targets=len(holdout_targets),
        ),
        "paired_gain": paired,
        "market_used": False,
    }
    if paired["status"] != "SUPPORTED":
        raise RuntimeError("ATP_STRUCTURAL_V8_PROMOTION_NOT_SUPPORTED")
    candidate["status"] = "ATP_STRUCTURAL_V8_CHRONOLOGICALLY_SUPPORTED"
    candidate["realized_hierarchy"]["atp_structural_profile_audit"] = audit
    candidate["holdout"]["atp_structural_v8"] = audit["candidate"]
    candidate["holdout"]["paired_gain_vs_previous_release"] = paired
    return candidate, audit


def build_contract(
    replay_dir: Path, baseline_path: Path, frozen_wta_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_contract = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline_contract.get("model_version") != MODEL_VERSION:
        raise ValueError("expected contextual combination v18 baseline")
    atp, audit = build_atp_candidate(
        _read_replay(replay_dir / "atp.jsonl.gz"),
        baseline_contract["universes"]["atp"],
    )
    contract = copy.deepcopy(baseline_contract)
    contract["universes"]["atp"] = atp
    frozen_wta = baseline_contract["universes"]["wta"]
    if frozen_wta_path is not None:
        frozen_contract = json.loads(frozen_wta_path.read_text(encoding="utf-8"))
        if frozen_contract.get("model_version") != MODEL_VERSION:
            raise ValueError("expected contextual combination v18 frozen WTA contract")
        frozen_wta = frozen_contract["universes"]["wta"]
    contract["universes"]["wta"] = copy.deepcopy(frozen_wta)
    if contract["universes"]["wta"] != frozen_wta:
        raise RuntimeError("WTA_CONTRACT_CHANGED_DURING_ATP_PROMOTION")
    return stabilize_floats(contract), audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--frozen-wta-contract", type=Path)
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
