"""Build the isolated ATP H2H sample-reliability v11 candidate."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    _metrics,
    _paired_probability_gain,
    fit_family_equation,
)
from src.contextual_family_combination_v2 import _select_l1
from src.contextual_family_combination_v10 import predict_contextual_combination_v10
from src.contextual_family_combination_v11 import (
    MODEL_VERSION,
    predict_contextual_combination_v11,
)
from src.contextual_family_replay import _split


def build_universe(
    rows: list[dict], *, universe: str, baseline_contract: dict,
) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    baseline_model = baseline_contract["universes"][universe]
    candidate_model = copy.deepcopy(baseline_model)
    if universe == "atp":
        profile = "h2h_reliability_curve_v3"
        selected_l1 = _select_l1(
            split["train"], "matchup_h2h", profile,
        )
        candidate_model["runtime_family_models"]["matchup_h2h"] = (
            fit_family_equation(
                split["train"] + split["validation"],
                family="matchup_h2h", feature_profile=profile,
                l1=selected_l1,
            )
        )
        candidate_model["family_profiles"]["matchup_h2h"] = profile
        candidate_model["family_l1_selected_inside_train"][
            "matchup_h2h"
        ] = selected_l1

    candidate_contract = {
        "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "universes": {universe: candidate_model},
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }
    candidate = np.asarray(predict_contextual_combination_v11(
        split["holdout"], universe=universe, contract=candidate_contract,
    )["probabilities"], dtype=float)
    baseline = np.asarray(predict_contextual_combination_v10(
        split["holdout"], universe=universe, contract=baseline_contract,
    )["probabilities"], dtype=float)
    targets = np.asarray([
        float(row["target_a_win"]) for row in split["holdout"]
    ])
    material_indexes = [
        index for index, row in enumerate(split["holdout"])
        if int((row.get("samples") or {}).get("h2h") or 0) >= 5
        and abs(float((row.get("features") or {}).get(
            "h2h_win_share_margin",
        ) or 0.0)) >= 0.2
    ]
    material = None
    if material_indexes:
        material = {
            "sample": len(material_indexes),
            "paired_gain_vs_v10": _paired_probability_gain(
                targets[material_indexes], baseline[material_indexes],
                candidate[material_indexes],
            ),
        }
    candidate_model.update({
        "model_version": MODEL_VERSION,
        "status": "ATP_H2H_SAMPLE_RELIABILITY_ISOLATED",
        "h2h_reliability_policy": {
            "atp": "dominance_x_n_over_n_plus_2_x_sqrt_n",
            "wta": "unchanged_from_v10",
            "single_match_remains_strongly_shrunk": True,
            "market_used": False,
        },
        "holdout": {
            "v11": _metrics(targets, candidate, total_targets=len(targets)),
            "v10": _metrics(targets, baseline, total_targets=len(targets)),
            "paired_gain_vs_v10": _paired_probability_gain(
                targets, baseline, candidate,
            ),
            "material_h2h": material,
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
    return candidate_model


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
        universe: model["holdout"]["paired_gain_vs_v10"]
        for universe, model in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
