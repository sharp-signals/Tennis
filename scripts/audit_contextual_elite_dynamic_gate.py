"""Chronological, market-free audit of a narrowly gated ATP elite prior."""

from __future__ import annotations

import argparse
import copy
from collections import defaultdict
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_chronological_rating import _expected, _name
from src.contextual_family_calibration import _metrics, _paired_probability_gain
from src.contextual_family_combination_v2 import _fit_family_bundle
from src.contextual_family_combination_v18 import predict_contextual_combination_v18
from src.contextual_family_replay import _split


ELO_KEY = "chronological_elo_probability_a_k64_elite_audit_v1"


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-9), 1.0 - 1e-9)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, value))))


def _attach_elo(rows: list[dict[str, Any]], *, k: int = 64) -> list[dict[str, Any]]:
    ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    grouped: defaultdict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[str(row["event_date"])].append((index, row))
    probabilities: dict[int, float] = {}
    for event_date in sorted(grouped):
        updates = []
        for index, row in grouped[event_date]:
            player_a, player_b = _name(row["player_a"]), _name(row["player_b"])
            rating_a, rating_b = ratings[player_a], ratings[player_b]
            probability_a = _expected(rating_a, rating_b)
            probabilities[index] = probability_a
            outcome = 1.0 if row["target_a_win"] else 0.0
            updates.append((player_a, player_b, k * (outcome - probability_a)))
        for player_a, player_b, delta in updates:
            ratings[player_a] += delta
            ratings[player_b] -= delta
    output = []
    for index, row in enumerate(rows):
        features = dict(row.get("features") or {})
        features[ELO_KEY] = probabilities[index]
        output.append({**row, "features": features})
    return output


def _temporary_contract(release: dict[str, Any], combination: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_version": release["components"]["family_combination"],
        "mode": "SHADOW_ONLY",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {"atp": combination},
    }


def _gate_context(row: dict[str, Any], baseline_probability_a: float) -> dict[str, Any]:
    elo_probability_a = float(row["features"][ELO_KEY])
    side = "a" if elo_probability_a >= 0.5 else "b"
    diagnostics = row.get("diagnostics") or {}
    rank = diagnostics.get("rank_a" if side == "a" else "rank_b")
    recent = (row.get("family_probabilities") or {}).get("recent_form")
    if recent is not None and side == "b":
        recent = 1.0 - float(recent)
    elif recent is not None:
        recent = float(recent)
    baseline_side = "a" if float(baseline_probability_a) >= 0.5 else "b"
    return {
        "side": side,
        "rank": None if rank is None else float(rank),
        "recent": recent,
        "elo_probability": max(elo_probability_a, 1.0 - elo_probability_a),
        "directions_agree": side == baseline_side,
    }


def _apply_candidate(
    rows: list[dict[str, Any]],
    baseline: np.ndarray,
    candidate: dict[str, Any],
) -> tuple[np.ndarray, list[bool]]:
    output = np.asarray(baseline, dtype=float).copy()
    gated = []
    alpha = float(candidate["alpha"])
    for index, (row, probability_a) in enumerate(zip(rows, baseline)):
        context = _gate_context(row, float(probability_a))
        applies = bool(
            alpha > 0.0
            and context["directions_agree"]
            and context["rank"] is not None
            and context["rank"] <= float(candidate["rank_max"])
            and context["elo_probability"] >= float(candidate["elo_min"])
            and context["recent"] is not None
            and context["recent"] >= float(candidate["recent_min"])
        )
        gated.append(applies)
        if not applies:
            continue
        side_probability = (
            float(probability_a)
            if context["side"] == "a" else 1.0 - float(probability_a)
        )
        adjusted = _sigmoid(
            (1.0 - alpha) * _logit(side_probability)
            + alpha * _logit(context["elo_probability"])
        )
        output[index] = adjusted if context["side"] == "a" else 1.0 - adjusted
    return output, gated


def _log_loss(targets: np.ndarray, probabilities: np.ndarray) -> float:
    clipped = np.clip(probabilities, 1e-9, 1.0 - 1e-9)
    return float(-np.mean(
        targets * np.log(clipped) + (1.0 - targets) * np.log(1.0 - clipped)
    ))


def _gate_summary(
    rows: list[dict[str, Any]], targets: np.ndarray,
    baseline: np.ndarray, candidate: np.ndarray, gated: list[bool],
) -> dict[str, Any]:
    indexes = np.asarray(gated, dtype=bool)
    if not bool(indexes.any()):
        return {"sample": 0}
    target = targets[indexes]
    base = baseline[indexes]
    tested = candidate[indexes]
    return {
        "sample": int(indexes.sum()),
        "observed_selected_side_win_pct": round(100.0 * float(np.mean(
            np.where(tested >= 0.5, target, 1.0 - target)
        )), 2),
        "baseline_selected_side_probability_pct": round(100.0 * float(np.mean(
            np.maximum(base, 1.0 - base)
        )), 2),
        "candidate_selected_side_probability_pct": round(100.0 * float(np.mean(
            np.maximum(tested, 1.0 - tested)
        )), 2),
        "players": sorted({
            str(
                rows[index]["player_a"]
                if candidate[index] >= 0.5 else rows[index]["player_b"]
            )
            for index in np.flatnonzero(indexes)
        }),
    }


def _candidate_passes(
    paired_gain: dict[str, Any], gate_summary: dict[str, Any],
) -> bool:
    if paired_gain.get("status") != "SUPPORTED" or gate_summary.get("sample", 0) <= 0:
        return False
    observed = float(gate_summary["observed_selected_side_win_pct"])
    baseline_gap = abs(
        float(gate_summary["baseline_selected_side_probability_pct"]) - observed
    )
    candidate_gap = abs(
        float(gate_summary["candidate_selected_side_probability_pct"]) - observed
    )
    return candidate_gap <= baseline_gap + 1e-9


def build_audit(rows: list[dict[str, Any]], release: dict[str, Any]) -> dict[str, Any]:
    _augment_pooled_main_features(rows)
    rows = _attach_elo(rows)
    split = _split(rows)
    baseline = release["universes"]["atp"]["combination"]
    train_models = _fit_family_bundle(
        split["train"], universe="atp",
        selected_l1=baseline["family_l1_selected_inside_train"],
        profiles=baseline["family_profiles"], allow_missingness_vote=False,
    )
    validation_model = copy.deepcopy(baseline)
    validation_model["runtime_family_models"] = train_models
    validation_prediction = predict_contextual_combination_v18(
        split["validation"], universe="atp",
        contract=_temporary_contract(release, validation_model),
    )
    validation_rows = validation_prediction["rows"]
    validation_baseline = np.asarray(validation_prediction["probabilities"], dtype=float)
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in validation_rows
    ])
    candidates = [{
        "rank_max": 0, "elo_min": 1.0, "recent_min": 1.0, "alpha": 0.0,
    }]
    for rank_max in (2, 3, 5):
        for elo_min in (0.75, 0.80, 0.85):
            for recent_min in (0.60, 0.65, 0.70):
                for alpha in (0.25, 0.50, 0.75, 1.0):
                    candidates.append({
                        "rank_max": rank_max,
                        "elo_min": elo_min,
                        "recent_min": recent_min,
                        "alpha": alpha,
                    })
    validation_results = []
    for candidate in candidates:
        probabilities, gated = _apply_candidate(
            validation_rows, validation_baseline, candidate,
        )
        validation_results.append({
            **candidate,
            "validation_log_loss": _log_loss(validation_targets, probabilities),
            "validation_gate_sample": sum(gated),
        })
    selected = min(validation_results, key=lambda item: (
        item["validation_log_loss"], item["alpha"], item["rank_max"],
        item["elo_min"], item["recent_min"],
    ))

    holdout_prediction = predict_contextual_combination_v18(
        split["holdout"], universe="atp",
        contract=_temporary_contract(release, baseline),
    )
    holdout_rows = holdout_prediction["rows"]
    holdout_baseline = np.asarray(holdout_prediction["probabilities"], dtype=float)
    holdout_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout_rows
    ])
    holdout_candidate, holdout_gated = _apply_candidate(
        holdout_rows, holdout_baseline, selected,
    )
    paired = _paired_probability_gain(
        holdout_targets, holdout_baseline, holdout_candidate,
    )
    gate_summary = _gate_summary(
        holdout_rows, holdout_targets, holdout_baseline,
        holdout_candidate, holdout_gated,
    )
    promoted = bool(
        selected["alpha"] > 0.0
        and _candidate_passes(paired, gate_summary)
    )
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_ELITE_DYNAMIC_GATE_AUDIT",
        "market_used": False,
        "production_effect": False,
        "selection": {
            "policy": "MINIMUM_CHRONOLOGICAL_VALIDATION_LOG_LOSS",
            "candidates": len(validation_results),
            "selected": selected,
            "no_adjustment_validation_log_loss": validation_results[0][
                "validation_log_loss"
            ],
        },
        "holdout": {
            "baseline": _metrics(
                holdout_targets, holdout_baseline,
                total_targets=len(holdout_targets),
            ),
            "candidate": _metrics(
                holdout_targets, holdout_candidate,
                total_targets=len(holdout_targets),
            ),
            "paired_gain": paired,
            "gate": gate_summary,
            "promotion_checks": {
                "paired_gain_supported": paired["status"] == "SUPPORTED",
                "gate_calibration_not_worse": (
                    gate_summary.get("sample", 0) > 0
                    and abs(
                        float(gate_summary["candidate_selected_side_probability_pct"])
                        - float(gate_summary["observed_selected_side_win_pct"])
                    ) <= abs(
                        float(gate_summary["baseline_selected_side_probability_pct"])
                        - float(gate_summary["observed_selected_side_win_pct"])
                    ) + 1e-9
                ),
            },
        },
        "decision": "CANDIDATE_PASSED" if promoted else "CANDIDATE_REJECTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_audit(
        _read_replay(args.replay),
        json.loads(args.release.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
