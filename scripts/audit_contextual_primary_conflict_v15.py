"""Chronological audit of primary-conflict secondary consensus policies."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Callable

import numpy as np

from scripts.audit_contextual_family_hierarchy_v13 import (
    _governed_logits,
    _raw_contributions,
    _sigmoid,
)
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
from src.contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    SECONDARY_FAMILIES,
    govern_consensus_with_individual_cap,
)
from src.contextual_family_replay import _split


FAMILIES = (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
Governor = Callable[[dict[str, float]], tuple[dict[str, float], dict]]


def _direction(value: float) -> int:
    return 1 if value > 0.0 else -1 if value < 0.0 else 0


def _secondary_conflict_consensus(contributions: dict[str, float]) -> bool:
    primary = [_direction(contributions[family]) for family in PRIMARY_FAMILIES]
    secondary = [
        _direction(contributions[family]) for family in SECONDARY_FAMILIES
    ]
    active_secondary = [value for value in secondary if value]
    return (
        primary[0] * primary[1] < 0
        and len(active_secondary) == len(SECONDARY_FAMILIES)
        and len(set(active_secondary)) == 1
    )


def _conflict_consensus_governor(cap_basis: str) -> Governor:
    """Let three aligned secondary families arbitrate a primary conflict.

    Every secondary remains individually bounded by primary evidence unless
    ``uncapped`` is selected. No rule depends on player identity or market.
    """

    def govern(contributions: dict[str, float]) -> tuple[dict[str, float], dict]:
        if not _secondary_conflict_consensus(contributions):
            return govern_consensus_with_individual_cap(
                contributions, consensus_cap_basis="aligned_primary_total",
            )
        governed = {
            family: float(contributions.get(family, 0.0)) for family in FAMILIES
        }
        primary_values = [governed[family] for family in PRIMARY_FAMILIES]
        if cap_basis == "strongest_primary":
            cap = max(abs(value) for value in primary_values)
        elif cap_basis == "primary_total":
            cap = sum(abs(value) for value in primary_values)
        elif cap_basis == "uncapped":
            cap = math.inf
        else:
            raise ValueError(f"unsupported cap basis: {cap_basis}")
        capped = []
        for family in SECONDARY_FAMILIES:
            if abs(governed[family]) > cap:
                governed[family] = math.copysign(cap, governed[family])
                capped.append(family)
        return governed, {
            "applied": bool(capped),
            "policy": "SECONDARY_CONSENSUS_ARBITRATES_PRIMARY_CONFLICT",
            "cap_basis": cap_basis,
            "individual_secondary_cap": None if math.isinf(cap) else cap,
            "capped_families": capped,
        }

    return govern


def _segment_metrics(
    rows: list[dict], targets: np.ndarray, probabilities: np.ndarray,
    *, coefficients: dict[str, float],
) -> dict:
    mask = np.asarray([
        _secondary_conflict_consensus(_raw_contributions(row, coefficients))
        for row in rows
    ])
    if not np.any(mask):
        return {"sample": 0}
    return _metrics(
        targets[mask], probabilities[mask], total_targets=int(np.sum(mask)),
    )


def _evaluate(
    *, validation: list[dict], holdout: list[dict],
    coefficients: dict[str, float], intercept: float, governor: Governor,
) -> tuple[dict, np.ndarray]:
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
    holdout_logits, _ = _governed_logits(
        holdout, coefficients=coefficients, intercept=intercept,
        governor=governor,
    )
    validation_probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in validation_logits
    ])
    probabilities = np.asarray([
        _sigmoid(calibration_intercept + calibration_weights[0] * value)
        for value in holdout_logits
    ])
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    return {
        "validation": _metrics(
            validation_targets, validation_probabilities,
            total_targets=len(validation_targets),
        ),
        "holdout": _metrics(targets, probabilities, total_targets=len(targets)),
        "conflict_segment": _segment_metrics(
            holdout, targets, probabilities, coefficients=coefficients,
        ),
        "post_hierarchy_calibration": {
            "intercept": round(float(calibration_intercept), 8),
            "slope": round(float(calibration_weights[0]), 8),
        },
    }, probabilities


def audit_universe(rows: list[dict], *, universe: str, model: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=model["family_l1_selected_inside_train"],
        profiles=model["family_profiles"], allow_missingness_vote=False,
    )
    validation = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    holdout = _attach_predictions(
        split["holdout"], model["runtime_family_models"], universe=universe,
    )
    coefficients = model["family_coefficients"]
    intercept = float(model["intercept"])
    policies: dict[str, Governor] = {
        "v14_baseline": lambda values: govern_consensus_with_individual_cap(
            values, consensus_cap_basis=model["realized_hierarchy"][
                "consensus_cap_basis"
            ],
        ),
        "conflict_strongest_primary_cap": _conflict_consensus_governor(
            "strongest_primary"
        ),
        "conflict_primary_total_cap": _conflict_consensus_governor(
            "primary_total"
        ),
        "conflict_uncapped": _conflict_consensus_governor("uncapped"),
    }
    results, probabilities = {}, {}
    for name, governor in policies.items():
        results[name], probabilities[name] = _evaluate(
            validation=validation, holdout=holdout,
            coefficients=coefficients, intercept=intercept, governor=governor,
        )
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    baseline = probabilities["v14_baseline"]
    for name in policies:
        if name == "v14_baseline":
            continue
        results[name]["paired_gain_vs_v14"] = _paired_probability_gain(
            targets, baseline, probabilities[name],
        )
        results[name]["mean_absolute_probability_change_pp"] = round(
            100.0 * float(np.mean(np.abs(probabilities[name] - baseline))), 4,
        )
    selected = min(
        policies, key=lambda name: results[name]["validation"]["log_loss"],
    )
    return {
        "universe": universe,
        "holdout_targets": len(holdout),
        "selected_on_validation": selected,
        "policies": results,
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
        "results": {
            universe: audit_universe(
                _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz"),
                universe=universe, model=contract["universes"][universe],
            )
            for universe in ("atp", "wta")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            "selected": payload["selected_on_validation"],
            "holdout": payload["holdout_targets"],
        }
        for universe, payload in result["results"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

