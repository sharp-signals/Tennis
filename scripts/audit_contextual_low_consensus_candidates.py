"""Chronological A/B audit for weak unanimous contextual consensus.

The validation partition learns candidate parameters.  The frozen holdout is
used once for comparison.  No candidate is promoted and no market data is read.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.build_contextual_family_combination_v17 import (
    _fit_zero_intercept_slope,
)
from scripts.build_contextual_family_combination_v18 import _temporary_contract
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    _metrics,
    _paired_probability_gain,
)
from src.contextual_family_combination_v2 import FAMILY_ORDER, _fit_family_bundle
from src.contextual_family_combination_v18 import (
    predict_contextual_combination_v18,
)
from src.contextual_family_replay import _split
from src.contextual_probability_uncertainty_v2 import _apply_calibrator


DEFAULT_MODEL = Path("data/models/fenzobot-contextual-2026-11.json")
PRIMARY_FAMILIES = ("recent_form", "structural_strength")
SECONDARY_FAMILIES = ("surface_conditions", "matchup_h2h", "serve_return")
LOW_CONSENSUS_MAX_PROBABILITY = 0.625


def _sigmoid(value: np.ndarray | float) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    return 1.0 / (1.0 + np.exp(-np.clip(array, -35.0, 35.0)))


def _fit_nonnegative_logistic(
    features: np.ndarray, targets: np.ndarray, *, l2: float = 1e-6,
) -> np.ndarray:
    """Fit symmetric non-negative logistic weights without an intercept."""
    x = np.asarray(features, dtype=float)
    y = np.asarray(targets, dtype=float)
    weights = np.zeros(x.shape[1], dtype=float)
    weights[0] = 1.0

    def loss(candidate: np.ndarray) -> float:
        probability = np.clip(_sigmoid(x @ candidate), 1e-9, 1.0 - 1e-9)
        value = -np.mean(
            y * np.log(probability) + (1.0 - y) * np.log(1.0 - probability)
        )
        return float(value + 0.5 * l2 * (candidate @ candidate))

    for _ in range(100):
        probability = _sigmoid(x @ weights)
        gradient = x.T @ (probability - y) / max(1, len(y)) + l2 * weights
        curvature = probability * (1.0 - probability)
        hessian = (x.T * curvature) @ x / max(1, len(y))
        hessian += l2 * np.eye(x.shape[1])
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        current_loss = loss(weights)
        scale = 1.0
        updated = weights
        while scale >= 1e-6:
            candidate = np.maximum(0.0, weights - scale * step)
            if loss(candidate) <= current_loss + 1e-12:
                updated = candidate
                break
            scale *= 0.5
        if np.max(np.abs(updated - weights)) <= 1e-10:
            return updated
        weights = updated
    return weights


def _apply_vector_calibrator(
    probabilities: np.ndarray, calibrator: dict[str, Any],
) -> np.ndarray:
    return np.asarray([
        _apply_calibrator(float(value), calibrator) for value in probabilities
    ], dtype=float)


def _prediction_rows(
    rows: list[dict[str, Any]], model: dict[str, Any], *, universe: str,
) -> list[dict[str, Any]]:
    hierarchy = model["realized_hierarchy"]
    recent = hierarchy["recent_form_governance"]
    contract = _temporary_contract(
        model,
        universe=universe,
        h2h_multiplier=float(hierarchy.get("h2h_multiplier", 1.0)),
        slope=1.0,
        result_weight_floor=float(recent["result_weight_floor"]),
        opposing_modifier_cap=float(recent["opposing_modifier_cap"]),
        unanimous_policy=str(hierarchy["unanimous_policy"]),
    )
    return predict_contextual_combination_v18(
        rows, universe=universe, contract=contract,
    )["rows"]


def _candidate_features(
    prediction_rows: list[dict[str, Any]], *, baseline_slope: float,
) -> dict[str, np.ndarray]:
    base_logits = []
    bonus_features = []
    primary_floor_logits = []
    primary_dominant_bonus_features = []
    unanimous_mask = []
    low_mask = []
    primary_dominant_mask = []
    for row in prediction_rows:
        raw = row.get("pre_hierarchy_family_contributions") or {}
        realized = row.get("realized_family_contributions") or {}
        raw_directions = {
            1 if float(value) > 0 else -1
            for value in raw.values() if abs(float(value)) > 1e-12
        }
        all_families_active = all(
            abs(float(raw.get(family, 0.0))) > 1e-12
            for family in FAMILY_ORDER
        )
        unanimous = all_families_active and len(raw_directions) == 1
        base = sum(float(realized.get(family, 0.0)) for family in FAMILY_ORDER)
        baseline_probability = float(_sigmoid(baseline_slope * base))
        favorite_probability = max(
            baseline_probability, 1.0 - baseline_probability,
        )
        low = unanimous and favorite_probability <= LOW_CONSENSUS_MAX_PROBABILITY
        sign = 1.0 if base > 0 else -1.0 if base < 0 else 0.0
        primary = sum(abs(float(realized.get(family, 0.0)))
                      for family in PRIMARY_FAMILIES)
        secondary = sum(abs(float(realized.get(family, 0.0)))
                        for family in SECONDARY_FAMILIES)
        floor_adjustment = max(0.0, secondary - primary) if low else 0.0
        primary_dominant = low and primary > secondary
        base_logits.append(base)
        bonus_features.append(sign if low else 0.0)
        primary_floor_logits.append(base + sign * floor_adjustment)
        primary_dominant_bonus_features.append(
            sign if primary_dominant else 0.0
        )
        unanimous_mask.append(unanimous)
        low_mask.append(low)
        primary_dominant_mask.append(primary_dominant)
    return {
        "base_logit": np.asarray(base_logits, dtype=float),
        "bonus_feature": np.asarray(bonus_features, dtype=float),
        "primary_floor_logit": np.asarray(primary_floor_logits, dtype=float),
        "primary_dominant_bonus_feature": np.asarray(
            primary_dominant_bonus_features, dtype=float,
        ),
        "unanimous_mask": np.asarray(unanimous_mask, dtype=bool),
        "low_consensus_mask": np.asarray(low_mask, dtype=bool),
        "primary_dominant_mask": np.asarray(
            primary_dominant_mask, dtype=bool,
        ),
    }


def _favorite_segment(
    targets: np.ndarray, baseline: np.ndarray, candidate: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    selected = np.asarray(mask, dtype=bool)
    if not selected.any():
        return {"sample": 0}
    truth = targets[selected]
    old = baseline[selected]
    new = candidate[selected]
    side_a = old >= 0.5
    favorite_won = np.where(side_a, truth, 1.0 - truth)
    old_favorite = np.where(side_a, old, 1.0 - old)
    new_favorite = np.where(side_a, new, 1.0 - new)
    return {
        "sample": int(selected.sum()),
        "wins": int(favorite_won.sum()),
        "observed_pct": round(100.0 * float(favorite_won.mean()), 2),
        "baseline_predicted_pct": round(100.0 * float(old_favorite.mean()), 2),
        "candidate_predicted_pct": round(100.0 * float(new_favorite.mean()), 2),
        "baseline_mean_fair_odd": round(float(np.mean(1.0 / old_favorite)), 3),
        "candidate_mean_fair_odd": round(float(np.mean(1.0 / new_favorite)), 3),
        "paired_gain": _paired_probability_gain(truth, old, new),
    }


def _decision(overall_gain: dict[str, Any], focused: dict[str, Any]) -> str:
    focused_gain = focused.get("paired_gain") or {}
    if overall_gain["status"] == "REJECTED" or float(
        overall_gain["log_loss_gain"]
    ) < 0.0:
        return "CANDIDATE_REJECTED_GLOBAL_DEGRADATION"
    if (
        int(focused.get("sample") or 0) >= 30
        and focused_gain.get("status") == "SUPPORTED"
    ):
        return "TARGETED_CANDIDATE_SUPPORTED_NOT_PROMOTED"
    return "INCONCLUSIVE_KEEP_CURRENT_RELEASE"


def audit_universe(
    rows: list[dict[str, Any]], *, universe: str, release: dict[str, Any],
) -> dict[str, Any]:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    universe_model = release["universes"][universe]
    baseline = universe_model["combination"]
    baseline_slope = float(
        baseline["realized_hierarchy"]["post_hierarchy_calibration"]["slope"]
    )
    calibrator = universe_model["calibration"]["central_calibrator"]

    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=baseline["family_l1_selected_inside_train"],
        profiles=baseline["family_profiles"], allow_missingness_vote=False,
    )
    validation_model = copy.deepcopy(baseline)
    validation_model["runtime_family_models"] = train_models
    validation_rows = _prediction_rows(
        split["validation"], validation_model, universe=universe,
    )
    validation_features = _candidate_features(
        validation_rows, baseline_slope=baseline_slope,
    )
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["validation"]
    ], dtype=float)
    bonus_weights = _fit_nonnegative_logistic(
        np.column_stack((
            validation_features["base_logit"],
            validation_features["bonus_feature"],
        )),
        validation_targets,
    )
    primary_floor_slope = _fit_zero_intercept_slope(
        validation_features["primary_floor_logit"], validation_targets,
    )

    holdout_rows = _prediction_rows(
        split["holdout"], baseline, universe=universe,
    )
    holdout_features = _candidate_features(
        holdout_rows, baseline_slope=baseline_slope,
    )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in split["holdout"]
    ], dtype=float)
    baseline_probability = _apply_vector_calibrator(
        _sigmoid(baseline_slope * holdout_features["base_logit"]), calibrator,
    )
    bonus_probability = _apply_vector_calibrator(
        _sigmoid(np.column_stack((
            holdout_features["base_logit"],
            holdout_features["bonus_feature"],
        )) @ bonus_weights),
        calibrator,
    )
    primary_floor_probability = _apply_vector_calibrator(
        _sigmoid(
            primary_floor_slope * holdout_features["primary_floor_logit"]
        ),
        calibrator,
    )
    focused_mask = holdout_features["low_consensus_mask"]
    unanimous_mask = holdout_features["unanimous_mask"]

    def candidate_result(probability: np.ndarray) -> dict[str, Any]:
        overall_gain = _paired_probability_gain(
            targets, baseline_probability, probability,
        )
        focused = _favorite_segment(
            targets, baseline_probability, probability, focused_mask,
        )
        return {
            "overall": _metrics(
                targets, probability, total_targets=len(targets),
            ),
            "paired_gain_overall": overall_gain,
            "low_unanimous_segment": focused,
            "all_unanimous_segment": _favorite_segment(
                targets, baseline_probability, probability, unanimous_mask,
            ),
            "decision": _decision(overall_gain, focused),
        }

    return {
        "chronology": {
            "validation_from": min(row["event_date"] for row in split["validation"]),
            "validation_through": max(
                row["event_date"] for row in split["validation"]
            ),
            "holdout_from": min(row["event_date"] for row in split["holdout"]),
            "holdout_through": max(row["event_date"] for row in split["holdout"]),
            "validation_targets": len(validation_targets),
            "holdout_targets": len(targets),
        },
        "selection": {
            "partition": "validation_only",
            "baseline_slope": round(baseline_slope, 8),
            "bonus_candidate": {
                "base_slope": round(float(bonus_weights[0]), 8),
                "low_unanimous_logit_bonus": round(float(bonus_weights[1]), 8),
                "validation_low_unanimous_targets": int(
                    validation_features["low_consensus_mask"].sum()
                ),
            },
            "primary_floor_candidate": {
                "slope": round(float(primary_floor_slope), 8),
                "validation_low_unanimous_targets": int(
                    validation_features["low_consensus_mask"].sum()
                ),
            },
        },
        "baseline": {
            "overall": _metrics(
                targets, baseline_probability, total_targets=len(targets),
            ),
            "low_unanimous_segment": _favorite_segment(
                targets, baseline_probability, baseline_probability,
                focused_mask,
            ),
            "all_unanimous_segment": _favorite_segment(
                targets, baseline_probability, baseline_probability,
                unanimous_mask,
            ),
        },
        "candidates": {
            "learned_low_unanimous_bonus": candidate_result(bonus_probability),
            "primary_block_floor": candidate_result(primary_floor_probability),
        },
    }


def build_audit(
    release: dict[str, Any], replay_dir: Path,
) -> dict[str, Any]:
    universes = {
        universe: audit_universe(
            _read_replay(replay_dir / f"{universe}.jsonl.gz"),
            universe=universe,
            release=release,
        )
        for universe in ("atp", "wta")
    }
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_LOW_UNANIMOUS_CANDIDATE_A_B",
        "model_version": release["global_release_id"],
        "configuration_fingerprint": release["configuration_fingerprint"],
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "holdout_used_for_selection": False,
        "universes": universes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.model.read_text(encoding="utf-8"))
    audit = build_audit(release, args.replay_input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            name: result["decision"]
            for name, result in value["candidates"].items()
        }
        for universe, value in audit["universes"].items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
