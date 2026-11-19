"""Build the unanimous-consensus contextual combination v18."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.build_contextual_family_combination_v17 import (
    H2H_MULTIPLIER_CANDIDATES,
    OPPOSING_MODIFIER_CAP_CANDIDATES,
    RESULT_WEIGHT_FLOOR_CANDIDATES,
    _fit_zero_intercept_slope,
    _log_loss,
)
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import _metrics, _paired_probability_gain
from src.contextual_family_combination_v2 import _fit_family_bundle
from src.contextual_family_combination_v17 import predict_contextual_combination_v17
from src.contextual_family_combination_v18 import (
    MODEL_VERSION,
    UNCLIPPED_CONSENSUS_POLICY,
    V17_CONSENSUS_POLICY,
    predict_contextual_combination_v18,
)
from src.contextual_family_replay import _split


def _temporary_contract(
    model: dict, *, universe: str, h2h_multiplier: float, slope: float,
    result_weight_floor: float, opposing_modifier_cap: float,
    unanimous_policy: str = UNCLIPPED_CONSENSUS_POLICY,
) -> dict:
    candidate = copy.deepcopy(model)
    candidate["model_version"] = MODEL_VERSION
    candidate["realized_hierarchy"] = {
        "policy": "ORDER_INVARIANT_REALIZED_HIERARCHY",
        "unanimous_policy": unanimous_policy,
        "h2h_multiplier": h2h_multiplier,
        "recent_form_governance": {
            "policy": "RESULTS_AND_COMPETITIVENESS_BASE_CONTEXT_AS_MODIFIER",
            "result_weight_floor": result_weight_floor,
            "opposing_modifier_cap": opposing_modifier_cap,
        },
        "post_hierarchy_calibration": {
            "method": "ZERO_INTERCEPT_NONNEGATIVE_PLATT",
            "intercept": 0.0,
            "slope": slope,
        },
    }
    return {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "universes": {universe: candidate},
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def _predict(
    rows: list[dict], model: dict, *, universe: str,
    h2h_multiplier: float, slope: float, result_weight_floor: float,
    opposing_modifier_cap: float,
    unanimous_policy: str = UNCLIPPED_CONSENSUS_POLICY,
) -> np.ndarray:
    result = predict_contextual_combination_v18(
        rows, universe=universe, contract=_temporary_contract(
            model, universe=universe, h2h_multiplier=h2h_multiplier,
            slope=slope, result_weight_floor=result_weight_floor,
            opposing_modifier_cap=opposing_modifier_cap,
            unanimous_policy=unanimous_policy,
        ),
    )
    return np.asarray(result["probabilities"], dtype=float)


def build_universe(
    rows: list[dict], *, universe: str, baseline_contract: dict,
) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    baseline = baseline_contract["universes"][universe]
    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=baseline["family_l1_selected_inside_train"],
        profiles=baseline["family_profiles"], allow_missingness_vote=False,
    )
    validation_model = copy.deepcopy(baseline)
    validation_model["runtime_family_models"] = train_models
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["validation"]
    ])
    candidates = []
    for multiplier in H2H_MULTIPLIER_CANDIDATES:
        for result_floor in RESULT_WEIGHT_FLOOR_CANDIDATES:
            for modifier_cap in OPPOSING_MODIFIER_CAP_CANDIDATES:
                raw = _predict(
                    split["validation"], validation_model, universe=universe,
                    h2h_multiplier=multiplier, slope=1.0,
                    result_weight_floor=result_floor,
                    opposing_modifier_cap=modifier_cap,
                )
                logits = np.log(
                    np.clip(raw, 1e-9, 1.0)
                    / np.clip(1.0 - raw, 1e-9, 1.0)
                )
                slope = _fit_zero_intercept_slope(logits, validation_targets)
                probability = 1.0 / (
                    1.0 + np.exp(-np.clip(slope * logits, -35.0, 35.0))
                )
                candidates.append({
                    "h2h_multiplier": multiplier,
                    "result_weight_floor": result_floor,
                    "opposing_modifier_cap": modifier_cap,
                    "slope": slope,
                    "validation_log_loss": _log_loss(
                        validation_targets, probability,
                    ),
                })
    selected = min(candidates, key=lambda item: (
        item["validation_log_loss"], item["result_weight_floor"],
        item["opposing_modifier_cap"], item["h2h_multiplier"],
    ))
    holdout_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["holdout"]
    ])
    probability = _predict(
        split["holdout"], baseline, universe=universe,
        h2h_multiplier=selected["h2h_multiplier"],
        slope=selected["slope"],
        result_weight_floor=selected["result_weight_floor"],
        opposing_modifier_cap=selected["opposing_modifier_cap"],
    )
    baseline_probability = np.asarray(predict_contextual_combination_v17(
        split["holdout"], universe=universe, contract=baseline_contract,
    )["probabilities"], dtype=float)
    candidate_gain = _paired_probability_gain(
        holdout_targets, baseline_probability, probability,
    )
    candidate_audit = {
        "policy": UNCLIPPED_CONSENSUS_POLICY,
        "selected_hyperparameters": dict(selected),
        "paired_gain_vs_v17": candidate_gain,
    }
    unanimous_policy = UNCLIPPED_CONSENSUS_POLICY
    promotion_gate = "PASSED_NOT_REJECTED_WITH_NONNEGATIVE_POINT_ESTIMATE"
    if (
        candidate_gain["status"] == "REJECTED"
        or float(candidate_gain["log_loss_gain"]) < 0.0
    ):
        baseline_hierarchy = baseline["realized_hierarchy"]
        baseline_recent = baseline_hierarchy["recent_form_governance"]
        baseline_calibration = baseline_hierarchy["post_hierarchy_calibration"]
        selected = {
            "h2h_multiplier": float(
                baseline_hierarchy.get("h2h_multiplier", 1.0)
            ),
            "result_weight_floor": float(
                baseline_recent["result_weight_floor"]
            ),
            "opposing_modifier_cap": float(
                baseline_recent["opposing_modifier_cap"]
            ),
            "slope": float(baseline_calibration["slope"]),
            "validation_log_loss": None,
        }
        unanimous_policy = V17_CONSENSUS_POLICY
        promotion_gate = "REJECTED_FALLBACK_TO_V17"
        probability = _predict(
            split["holdout"], baseline, universe=universe,
            h2h_multiplier=selected["h2h_multiplier"],
            slope=selected["slope"],
            result_weight_floor=selected["result_weight_floor"],
            opposing_modifier_cap=selected["opposing_modifier_cap"],
            unanimous_policy=unanimous_policy,
        )
    paired_gain = _paired_probability_gain(
        holdout_targets, baseline_probability, probability,
    )
    result = copy.deepcopy(baseline)
    result.update({
        "model_version": MODEL_VERSION,
        "status": "UNANIMOUS_CONSENSUS_CHRONOLOGICALLY_CALIBRATED",
        "intercept": 0.0,
        "realized_hierarchy": {
            "policy": "ORDER_INVARIANT_REALIZED_HIERARCHY",
            "primary_families": ["recent_form", "structural_strength"],
            "secondary_families": [
                "surface_conditions", "matchup_h2h", "serve_return",
            ],
            "family_coefficients_preserve_primary_priority": True,
            "unanimous_policy": unanimous_policy,
            "unanimous_secondary_clipping": (
                unanimous_policy == V17_CONSENSUS_POLICY
            ),
            "candidate_policy_audit": candidate_audit,
            "promotion_gate": promotion_gate,
            "conflicting_evidence_keeps_strict_ordered_caps": True,
            "secondary_only_prediction_forbidden": True,
            "absence_never_votes": True,
            "orientation_policy": "PAIRED_DIRECTIONAL_ANTISYMMETRY",
            "h2h_multiplier": selected["h2h_multiplier"],
            "h2h_candidates": candidates,
            "recent_form_governance": {
                "policy": "RESULTS_AND_COMPETITIVENESS_BASE_CONTEXT_AS_MODIFIER",
                "result_weight_floor": selected["result_weight_floor"],
                "opposing_modifier_cap": selected["opposing_modifier_cap"],
                "selection_policy": "CHRONOLOGICAL_VALIDATION_LOG_LOSS",
            },
            "post_hierarchy_calibration": {
                "method": "ZERO_INTERCEPT_NONNEGATIVE_PLATT",
                "intercept": 0.0,
                "slope": round(float(selected["slope"]), 8),
                "development_targets": len(validation_targets),
            },
        },
        "holdout": {
            **baseline["holdout"],
            "v18": _metrics(
                holdout_targets, probability, total_targets=len(holdout_targets),
            ),
            "v17": _metrics(
                holdout_targets, baseline_probability,
                total_targets=len(holdout_targets),
            ),
            "paired_gain_vs_v17": paired_gain,
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
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--baseline-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline_contract.read_text(encoding="utf-8"))
    universes = {
        universe: build_universe(
            _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz"),
            universe=universe, baseline_contract=baseline,
        )
        for universe in ("atp", "wta")
    }
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
            "h2h_multiplier": model["realized_hierarchy"]["h2h_multiplier"],
            "unanimous_policy": model["realized_hierarchy"][
                "unanimous_policy"
            ],
            "promotion_gate": model["realized_hierarchy"]["promotion_gate"],
            "recent_form_governance": model["realized_hierarchy"][
                "recent_form_governance"
            ],
            "paired_gain_vs_v17": model["holdout"]["paired_gain_vs_v17"],
        }
        for universe, model in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
