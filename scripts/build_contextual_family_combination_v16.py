"""Build the order-invariant, realised-hierarchy combination v16."""

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
from src.contextual_family_calibration import _metrics, _paired_probability_gain
from src.contextual_family_combination_v2 import _fit_family_bundle
from src.contextual_family_combination_v15 import predict_contextual_combination_v15
from src.contextual_family_combination_v16 import (
    MODEL_VERSION,
    predict_contextual_combination_v16,
)
from src.contextual_family_replay import _split


H2H_MULTIPLIER_CANDIDATES = (1.0, 1.5, 2.0)


def _log_loss(targets: np.ndarray, probabilities: np.ndarray) -> float:
    values = np.clip(probabilities, 1e-9, 1.0 - 1e-9)
    return float(np.mean(-targets * np.log(values) - (1.0 - targets) * np.log(1.0 - values)))


def _fit_zero_intercept_slope(
    logits: np.ndarray, targets: np.ndarray, *, l2: float = 1e-6,
) -> float:
    """Fit a non-negative Platt slope while fixing neutral evidence at 50%."""
    slope = 1.0
    for _ in range(100):
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(slope * logits, -35.0, 35.0)))
        gradient = float(np.mean(logits * (probabilities - targets)) + l2 * slope)
        hessian = float(
            np.mean(logits * logits * probabilities * (1.0 - probabilities)) + l2
        )
        updated = max(0.0, slope - gradient / max(hessian, 1e-12))
        if abs(updated - slope) <= 1e-10:
            return updated
        slope = updated
    return slope


def _temporary_contract(
    model: dict, *, universe: str, h2h_multiplier: float, slope: float,
) -> dict:
    candidate = copy.deepcopy(model)
    candidate["model_version"] = MODEL_VERSION
    candidate["realized_hierarchy"] = {
        "policy": "ORDER_INVARIANT_REALIZED_HIERARCHY",
        "h2h_multiplier": h2h_multiplier,
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
    h2h_multiplier: float, slope: float,
) -> np.ndarray:
    contract = _temporary_contract(
        model, universe=universe, h2h_multiplier=h2h_multiplier, slope=slope,
    )
    result = predict_contextual_combination_v16(
        rows, universe=universe, contract=contract,
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
        raw = _predict(
            split["validation"], validation_model, universe=universe,
            h2h_multiplier=multiplier, slope=1.0,
        )
        logits = np.log(np.clip(raw, 1e-9, 1.0) / np.clip(1.0 - raw, 1e-9, 1.0))
        slope = _fit_zero_intercept_slope(logits, validation_targets)
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(slope * logits, -35.0, 35.0)))
        candidates.append({
            "h2h_multiplier": multiplier,
            "slope": slope,
            "validation_log_loss": _log_loss(validation_targets, probabilities),
        })
    selected = min(
        candidates,
        key=lambda item: (item["validation_log_loss"], item["h2h_multiplier"]),
    )
    holdout_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["holdout"]
    ])
    probabilities = _predict(
        split["holdout"], baseline, universe=universe,
        h2h_multiplier=selected["h2h_multiplier"], slope=selected["slope"],
    )
    baseline_probabilities = np.asarray(predict_contextual_combination_v15(
        split["holdout"], universe=universe, contract=baseline_contract,
    )["probabilities"], dtype=float)
    result = copy.deepcopy(baseline)
    result.update({
        "model_version": MODEL_VERSION,
        "status": "SYMMETRIC_HIERARCHY_CHRONOLOGICALLY_SELECTED",
        "intercept": 0.0,
        "realized_hierarchy": {
            "policy": "ORDER_INVARIANT_REALIZED_HIERARCHY",
            "primary_families": ["recent_form", "structural_strength"],
            "secondary_families": [
                "surface_conditions", "matchup_h2h", "serve_return",
            ],
            "secondary_total_not_above_primary_total": True,
            "surface_not_above_primary_average": True,
            "h2h_not_above_primary_average": True,
            "serve_return_not_above_half_primary_average": True,
            "absence_never_votes": True,
            "orientation_policy": "PAIRED_DIRECTIONAL_ANTISYMMETRY",
            "h2h_multiplier": selected["h2h_multiplier"],
            "h2h_candidates": candidates,
            "post_hierarchy_calibration": {
                "method": "ZERO_INTERCEPT_NONNEGATIVE_PLATT",
                "intercept": 0.0,
                "slope": round(float(selected["slope"]), 8),
                "development_targets": len(validation_targets),
            },
        },
        "holdout": {
            **baseline["holdout"],
            "v16": _metrics(
                holdout_targets, probabilities, total_targets=len(holdout_targets),
            ),
            "v15": _metrics(
                holdout_targets, baseline_probabilities,
                total_targets=len(holdout_targets),
            ),
            "paired_gain_vs_v15": _paired_probability_gain(
                holdout_targets, baseline_probabilities, probabilities,
            ),
        },
        "chronology": {
            "development_through": max(
                row["event_date"] for row in split["train"] + split["validation"]
            ),
            "holdout_from": min(row["event_date"] for row in split["holdout"]),
            "evaluation_through": max(row["event_date"] for row in split["holdout"]),
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
            "paired_gain_vs_v15": model["holdout"]["paired_gain_vs_v15"],
        }
        for universe, model in universes.items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
