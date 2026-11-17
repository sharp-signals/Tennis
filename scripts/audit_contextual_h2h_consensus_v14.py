"""Chronologically audit consensus caps and dynamic H2H authority."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

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
from src.contextual_family_combination_v2 import (
    _attach_predictions,
    _fit_family_bundle,
)
from src.contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    SECONDARY_FAMILIES,
    govern_consensus_with_individual_cap,
    govern_realized_family_contributions,
)
from src.contextual_family_replay import _split


FAMILIES = (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = min(max(float(value), -35.0), 35.0)
    return 1.0 / (1.0 + math.exp(-value))


def _direction(value: float) -> int:
    return 1 if value > 0.0 else -1 if value < 0.0 else 0


def _raw_contributions(row: dict, coefficients: dict[str, float]) -> dict[str, float]:
    return {
        family: (
            float(coefficients[family])
            * _logit(row["family_probabilities"][family])
            if row["family_probabilities"].get(family) is not None else 0.0
        )
        for family in FAMILIES
    }


def _h2h_authority_score(row: dict) -> float:
    """Continuous pre-match H2H reliability using sample, dominance and surface."""
    features = row.get("features") or {}
    global_signal = features.get("contextual_h2h_reliability_curve_v3")
    surface_signal = features.get(
        "contextual_h2h_same_surface_reliability_curve_v3"
    )
    if global_signal is None:
        return 0.0
    combined = abs(float(global_signal))
    if (
        surface_signal is not None
        and _direction(float(surface_signal)) == _direction(float(global_signal))
    ):
        combined += 0.25 * abs(float(surface_signal))
    return min(combined / 2.0, 1.0)


def _govern(
    row: dict, contributions: dict[str, float], *, consensus_cap: str,
    h2h_max_multiplier: float,
) -> tuple[dict[str, float], dict]:
    governed = {family: float(contributions[family]) for family in FAMILIES}
    authority_score = _h2h_authority_score(row)
    h2h_multiplier = 1.0 + (
        float(h2h_max_multiplier) - 1.0
    ) * authority_score
    governed["matchup_h2h"] *= h2h_multiplier

    primary_values = [governed[family] for family in PRIMARY_FAMILIES]
    secondary_values = [governed[family] for family in SECONDARY_FAMILIES]
    primary_direction = _direction(sum(primary_values))
    consensus = bool(primary_direction) and all(
        _direction(value) in (0, primary_direction)
        for value in (*primary_values, *secondary_values)
    )
    if not consensus:
        strict, audit = govern_realized_family_contributions(governed)
        return strict, {
            **audit,
            "policy": "STRICT_CONFLICT_BLOCK_CAP_WITH_H2H_AUTHORITY",
            "h2h_authority_score": authority_score,
            "h2h_multiplier": h2h_multiplier,
        }

    if consensus_cap == "strongest_primary":
        individual_limit = max(abs(value) for value in primary_values)
    elif consensus_cap == "primary_block":
        individual_limit = sum(abs(value) for value in primary_values)
    else:
        raise ValueError(f"unknown consensus cap: {consensus_cap}")
    capped_families: list[str] = []
    for family in SECONDARY_FAMILIES:
        if abs(governed[family]) > individual_limit:
            governed[family] = math.copysign(individual_limit, governed[family])
            capped_families.append(family)
    return governed, {
        "applied": bool(capped_families),
        "policy": f"CONSENSUS_{consensus_cap.upper()}_CAP_WITH_H2H_AUTHORITY",
        "consensus_reinforcement": True,
        "individual_secondary_limit": individual_limit,
        "capped_families": capped_families,
        "h2h_authority_score": authority_score,
        "h2h_multiplier": h2h_multiplier,
    }


def _evaluate(
    *, validation: list[dict], holdout: list[dict], coefficients: dict[str, float],
    intercept: float, consensus_cap: str, h2h_max_multiplier: float,
) -> tuple[dict, np.ndarray]:
    def governed_logits(rows: list[dict]) -> tuple[np.ndarray, list[dict]]:
        logits: list[float] = []
        audits: list[dict] = []
        for row in rows:
            governed, audit = _govern(
                row, _raw_contributions(row, coefficients),
                consensus_cap=consensus_cap,
                h2h_max_multiplier=h2h_max_multiplier,
            )
            logits.append(float(intercept) + sum(governed.values()))
            audits.append(audit)
        return np.asarray(logits, dtype=float), audits

    validation_logits, validation_audits = governed_logits(validation)
    validation_targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in validation
    ])
    calibration_intercept, calibration_weights, _ = _fit_logistic_elastic_net(
        validation_logits.reshape(-1, 1), validation_targets,
        l1=0.0, l2=1e-6, nonnegative_mask=np.asarray([True]),
    )
    holdout_logits, holdout_audits = governed_logits(holdout)
    probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    validation_probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in validation_logits
    ])
    strong_h2h_mask = np.asarray([
        _h2h_authority_score(row) >= 0.5 for row in holdout
    ])
    result = {
        "validation_metrics": _metrics(
            validation_targets, validation_probabilities,
            total_targets=len(validation_targets),
        ),
        "metrics": _metrics(targets, probabilities, total_targets=len(targets)),
        "calibration": {
            "intercept": round(float(calibration_intercept), 8),
            "slope": round(float(calibration_weights[0]), 8),
        },
        "rows_contracted": sum(bool(item.get("applied")) for item in holdout_audits),
        "validation_rows_contracted": sum(
            bool(item.get("applied")) for item in validation_audits
        ),
        "strong_h2h_rows": int(np.sum(strong_h2h_mask)),
    }
    if np.any(strong_h2h_mask):
        result["strong_h2h_metrics"] = _metrics(
            targets[strong_h2h_mask], probabilities[strong_h2h_mask],
            total_targets=int(np.sum(strong_h2h_mask)),
        )
    return result, probabilities


def audit_universe(rows: list[dict], *, universe: str, model: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    selected_l1 = model["family_l1_selected_inside_train"]
    profiles = model["family_profiles"]
    train_models = _fit_family_bundle(
        split["train"], universe=universe, selected_l1=selected_l1,
        profiles=profiles, allow_missingness_vote=False,
    )
    final_models = _fit_family_bundle(
        split["train"] + split["validation"], universe=universe,
        selected_l1=selected_l1, profiles=profiles,
        allow_missingness_vote=False,
    )
    validation = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    holdout = _attach_predictions(
        split["holdout"], final_models, universe=universe,
    )
    coefficients = model["family_coefficients"]
    intercept = float(model["intercept"])
    candidates = [
        ("strongest_x1_00", "strongest_primary", 1.0),
        ("primary_block_x1_00", "primary_block", 1.0),
    ]
    for cap in ("strongest_primary", "primary_block"):
        for multiplier in (1.25, 1.5, 1.75, 2.0):
            candidates.append((
                f"{cap}_x{multiplier:.2f}".replace(".", "_"), cap, multiplier,
            ))
    results: dict[str, dict] = {}
    probabilities: dict[str, np.ndarray] = {}
    for name, cap, multiplier in candidates:
        results[name], probabilities[name] = _evaluate(
            validation=validation, holdout=holdout,
            coefficients=coefficients, intercept=intercept,
            consensus_cap=cap, h2h_max_multiplier=multiplier,
        )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline = probabilities["strongest_x1_00"]
    strong_h2h_mask = np.asarray([
        _h2h_authority_score(row) >= 0.5 for row in holdout
    ])
    for name, _, _ in candidates:
        if name == "strongest_x1_00":
            continue
        results[name]["paired_gain_vs_v13"] = _paired_probability_gain(
            targets, baseline, probabilities[name],
        )
        results[name]["mean_absolute_probability_change_pp"] = round(
            100.0 * float(np.mean(np.abs(probabilities[name] - baseline))), 4,
        )
        results[name]["changed_favorite_side"] = int(np.sum(
            (baseline >= 0.5) != (probabilities[name] >= 0.5)
        ))
        if np.any(strong_h2h_mask):
            results[name]["strong_h2h_paired_gain_vs_v13"] = (
                _paired_probability_gain(
                    targets[strong_h2h_mask], baseline[strong_h2h_mask],
                    probabilities[name][strong_h2h_mask],
                )
            )
    selected_name = min(
        (name for name, _, _ in candidates),
        key=lambda name: results[name]["validation_metrics"]["log_loss"],
    )
    return {
        "universe": universe,
        "holdout_targets": len(holdout),
        "strong_h2h_holdout_targets": int(np.sum(strong_h2h_mask)),
        "selected_on_validation": selected_name,
        "candidates": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    result = {
        "schema_version": 1,
        "mode": "READ_ONLY_CHRONOLOGICAL_AUDIT",
        "market_used": False,
        "production_effect": False,
        "results": {},
    }
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        result["results"][universe] = audit_universe(
            rows, universe=universe, model=contract["universes"][universe],
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            "selected": payload["selected_on_validation"],
            "holdout": payload["holdout_targets"],
            "strong_h2h": payload["strong_h2h_holdout_targets"],
        }
        for universe, payload in result["results"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
