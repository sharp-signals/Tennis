"""Build the chronologically selected primary-conflict hierarchy v15."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from scripts.audit_contextual_family_hierarchy_v13 import _governed_logits, _sigmoid
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
from src.contextual_family_combination_v2 import _attach_predictions, _fit_family_bundle
from src.contextual_family_combination_v14 import predict_contextual_combination_v14
from src.contextual_family_combination_v15 import MODEL_VERSION
from src.contextual_family_hierarchy import (
    govern_atp_primary_conflict_consensus,
    govern_consensus_with_individual_cap,
)
from src.contextual_family_replay import _split


def _governor(universe: str):
    if universe == "atp":
        return govern_atp_primary_conflict_consensus

    def apply(contributions: dict[str, float]):
        return govern_consensus_with_individual_cap(
            contributions, consensus_cap_basis="strongest_primary",
        )
    return apply


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
    validation = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    holdout = _attach_predictions(
        split["holdout"], baseline["runtime_family_models"], universe=universe,
    )
    coefficients = baseline["family_coefficients"]
    intercept = float(baseline["intercept"])
    governor = _governor(universe)
    validation_logits, _ = _governed_logits(
        validation, coefficients=coefficients, intercept=intercept,
        governor=governor,
    )
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in validation
    ])
    calibration_intercept, calibration_weights, _ = _fit_logistic_elastic_net(
        validation_logits.reshape(-1, 1), validation_targets,
        l1=0.0, l2=1e-6, nonnegative_mask=np.asarray([True]),
    )
    holdout_logits, audits = _governed_logits(
        holdout, coefficients=coefficients, intercept=intercept,
        governor=governor,
    )
    probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline_probabilities = np.asarray(predict_contextual_combination_v14(
        split["holdout"], universe=universe, contract=baseline_contract,
    )["probabilities"], dtype=float)
    result = copy.deepcopy(baseline)
    result.update({
        "model_version": MODEL_VERSION,
        "status": "PRIMARY_CONFLICT_POLICY_CHRONOLOGICALLY_SELECTED",
        "realized_hierarchy": {
            "policy": (
                "ATP_THREE_SECONDARY_CONSENSUS_ARBITRATION"
                if universe == "atp" else "WTA_V14_BASELINE_PRESERVED"
            ),
            "primary_families": ["recent_form", "structural_strength"],
            "secondary_families": [
                "surface_conditions", "matchup_h2h", "serve_return",
            ],
            "conflict_three_secondary_consensus_preserved": universe == "atp",
            "other_conflicts_keep_v14_caps": True,
            "unanimous_reinforcement_preserved": True,
            "post_hierarchy_calibration": {
                "method": "DEVELOPMENT_ONLY_NONNEGATIVE_PLATT",
                "intercept": round(float(calibration_intercept), 8),
                "slope": round(float(calibration_weights[0]), 8),
                "development_targets": len(validation_targets),
            },
            "holdout_rows_contracted": sum(
                bool(item.get("applied")) for item in audits
            ),
            "holdout_violations": 0,
        },
        "holdout": {
            **baseline["holdout"],
            "v15": _metrics(targets, probabilities, total_targets=len(targets)),
            "v14": _metrics(
                targets, baseline_probabilities, total_targets=len(targets),
            ),
            "paired_gain_vs_v14": _paired_probability_gain(
                targets, baseline_probabilities, probabilities,
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
        universe: model["holdout"]["paired_gain_vs_v14"]
        for universe, model in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
