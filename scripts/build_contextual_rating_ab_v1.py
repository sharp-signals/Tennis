"""Freeze isolated ATP/WTA chronological-rating candidates for prospective A/B."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_contextual_family_hierarchy_v13 import _governed_logits
from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.build_contextual_family_combination_v14 import _governor
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_chronological_rating import augment_replay_rows_with_ratings
from src.contextual_family_calibration import (
    _fit_logistic_elastic_net,
    calibrate_family,
)
from src.contextual_family_combination_v2 import (
    _attach_predictions,
    _fit_family_bundle,
    combine_contextual_families_v2,
)
from src.contextual_family_replay import _split
from src.stable_json import stabilize_floats


PROFILES = {
    "atp-rating-refit-v1": "contextual_v7_global_elo_atp_ab_v1",
    "wta-rating-global-v1": "contextual_v7_global_elo_wta_ab_v1",
    "wta-rating-global-surface-v1": (
        "contextual_v7_global_surface_elo_wta_ab_v1"
    ),
}


def _calibrate_hierarchy(
    split: dict, *, universe: str, coefficients: dict, intercept: float,
    train_models: dict, cap_basis: str,
) -> dict:
    validation = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    logits, _ = _governed_logits(
        validation, coefficients=coefficients, intercept=intercept,
        governor=_governor(cap_basis),
    )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in validation
    ])
    calibration_intercept, weights, _ = _fit_logistic_elastic_net(
        logits.reshape(-1, 1), targets, l1=0.0, l2=1e-6,
        nonnegative_mask=np.asarray([True]),
    )
    return {
        "method": "DEVELOPMENT_ONLY_NONNEGATIVE_PLATT",
        "intercept": round(float(calibration_intercept), 8),
        "slope": round(float(weights[0]), 8),
        "development_targets": len(targets),
    }


def _candidate(
    rows: list[dict], *, universe: str, candidate_id: str,
    baseline: dict, refit_combination: bool,
) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    rows = augment_replay_rows_with_ratings(rows, universe=universe)
    split = _split(rows)
    profile = PROFILES[candidate_id]
    profiles = {**baseline["family_profiles"], "structural_strength": profile}

    if refit_combination:
        refit = combine_contextual_families_v2(
            rows, universe=universe, family_profile_overrides=profiles,
            model_version=candidate_id, allow_missingness_vote=False,
        )
        coefficients = refit["family_coefficients"]
        intercept = float(refit["intercept"])
        selected_l1 = refit["family_l1_selected_inside_train"]
        runtime_models = refit["runtime_family_models"]
    else:
        structural = calibrate_family(
            split, family="structural_strength", feature_profile=profile,
            allow_missingness_vote=False,
        )
        coefficients = copy.deepcopy(baseline["family_coefficients"])
        intercept = float(baseline["intercept"])
        selected_l1 = copy.deepcopy(
            baseline["family_l1_selected_inside_train"]
        )
        selected_l1["structural_strength"] = structural[
            "selected_l1_on_validation"
        ]
        runtime_models = _fit_family_bundle(
            split["train"] + split["validation"], universe=universe,
            selected_l1=selected_l1, profiles=profiles,
            allow_missingness_vote=False,
        )
    cap_basis = "aligned_primary_total" if universe == "atp" else "strongest_primary"
    train_models = _fit_family_bundle(
        split["train"], universe=universe, selected_l1=selected_l1,
        profiles=profiles, allow_missingness_vote=False,
    )
    calibration = _calibrate_hierarchy(
        split, universe=universe, coefficients=coefficients,
        intercept=intercept, train_models=train_models, cap_basis=cap_basis,
    )
    return {
        "candidate_id": candidate_id,
        "feature_profile": profile,
        "combination": {
            **copy.deepcopy(baseline),
            "family_profiles": profiles,
            "family_l1_selected_inside_train": selected_l1,
            "family_coefficients": coefficients,
            "intercept": intercept,
            "runtime_family_models": runtime_models,
            "realized_hierarchy": {
                **copy.deepcopy(baseline["realized_hierarchy"]),
                "consensus_cap_basis": cap_basis,
                "post_hierarchy_calibration": calibration,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--release-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.release_contract.read_text(encoding="utf-8"))
    replay = {
        universe: _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        for universe in ("atp", "wta")
    }
    candidates = {
        "atp": [_candidate(
            replay["atp"], universe="atp", candidate_id="atp-rating-refit-v1",
            baseline=release["universes"]["atp"]["combination"],
            refit_combination=True,
        )],
        "wta": [
            _candidate(
                replay["wta"], universe="wta", candidate_id=candidate_id,
                baseline=release["universes"]["wta"]["combination"],
                refit_combination=False,
            ) for candidate_id in (
                "wta-rating-global-v1", "wta-rating-global-surface-v1",
            )
        ],
    }
    contract = stabilize_floats({
        "schema_version": 1,
        "experiment_id": "contextual-rating-ab-v1",
        "mode": "PROSPECTIVE_SHADOW_AB_ONLY",
        "baseline_release_id": release["global_release_id"],
        "baseline_configuration_fingerprint": release[
            "configuration_fingerprint"
        ],
        "candidates": candidates,
        "market_used": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
        "promotion_authorized": False,
    })
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    contract["configuration_fingerprint"] = hashlib.sha256(
        canonical.encode()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "experiment_id": contract["experiment_id"],
        "candidates": {
            key: [item["candidate_id"] for item in value]
            for key, value in candidates.items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
