"""Read-only ablation of every active factual input in the released model."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_contextual_existing_feature_ablation import (
    _combination_contract,
)
from scripts.audit_serve_return_exact_context_v2 import _paired_diagnostics
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import _metrics, _paired_probability_gain
from src.contextual_family_combination_v18 import predict_contextual_combination_v18
from src.contextual_family_replay import _split


def frozen_feature_inventory(combination: dict[str, Any]) -> dict[str, list[dict]]:
    """List active and zero-weight factual inputs, grouping surface contexts."""
    active: dict[tuple[str, str], dict[str, float]] = {}
    inactive: dict[tuple[str, str], dict[str, float]] = {}
    for family, model in combination["runtime_family_models"].items():
        models = (
            model.items()
            if family == "surface_conditions"
            else (("global", model),)
        )
        for context, context_model in models:
            columns = list(context_model.get("columns") or [])
            weights = list(context_model.get("weights") or [])
            for feature, weight in zip(columns, weights):
                if feature.endswith("__missing"):
                    continue
                target = active if abs(float(weight)) > 1e-12 else inactive
                target.setdefault((family, feature), {})[context] = float(weight)
    return {
        "active": [
            {"family": family, "feature": feature, "weights": weights}
            for (family, feature), weights in sorted(active.items())
        ],
        "inactive_zero_weight": [
            {"family": family, "feature": feature, "weights": weights}
            for (family, feature), weights in sorted(inactive.items())
            if (family, feature) not in active
        ],
    }


def zero_frozen_feature_everywhere(
    combination: dict[str, Any], *, family: str, feature: str,
) -> tuple[dict[str, Any], dict[str, float] | None]:
    """Zero one factual input globally or across every exact surface model."""
    candidate = copy.deepcopy(combination)
    model = candidate["runtime_family_models"][family]
    models = (
        model.items()
        if family == "surface_conditions"
        else (("global", model),)
    )
    originals = {}
    for context, context_model in models:
        columns = list(context_model.get("columns") or [])
        if feature not in columns:
            continue
        index = columns.index(feature)
        originals[context] = float(context_model["weights"][index])
        context_model["weights"][index] = 0.0
    return candidate, originals or None


def _evaluate(
    holdout: list[dict[str, Any]], targets: np.ndarray,
    baseline: np.ndarray, *, universe: str, release: dict[str, Any],
    combination: dict[str, Any], family: str, feature: str,
) -> dict[str, Any]:
    ablated_contract, coefficients = zero_frozen_feature_everywhere(
        combination, family=family, feature=feature,
    )
    if coefficients is None:
        return {"status": "FEATURE_NOT_IN_RELEASE"}
    ablated = np.asarray(predict_contextual_combination_v18(
        holdout,
        universe=universe,
        contract=_combination_contract(
            release, universe=universe, combination=ablated_contract,
        ),
    )["probabilities"], dtype=float)
    baseline_metrics = _metrics(targets, baseline, total_targets=len(holdout))
    ablated_metrics = _metrics(targets, ablated, total_targets=len(holdout))
    paired = _paired_probability_gain(targets, baseline, ablated)
    if paired["status"] == "REJECTED":
        decision = "KEEP_FEATURE_SUPPORTED"
    elif paired["status"] == "SUPPORTED":
        decision = "REMOVE_FEATURE_SUPPORTED"
    else:
        decision = "INCONCLUSIVE_KEEP_CURRENT_RELEASE"
    return {
        "status": "EVALUATED",
        "family": family,
        "feature": feature,
        "frozen_coefficients": coefficients,
        "ablated": ablated_metrics,
        "removal_log_loss_penalty": round(
            float(ablated_metrics["log_loss"] - baseline_metrics["log_loss"]),
            6,
        ),
        "paired_removal_test": paired,
        "diagnostics": _paired_diagnostics(
            holdout, list(range(len(holdout))), targets, baseline, ablated,
        ),
        "decision": decision,
    }


def _audit_universe(
    rows: list[dict[str, Any]], *, universe: str, release: dict[str, Any],
) -> dict[str, Any]:
    _augment_pooled_main_features(rows)
    holdout = _split(rows)["holdout"]
    combination = release["universes"][universe]["combination"]
    baseline = np.asarray(predict_contextual_combination_v18(
        holdout,
        universe=universe,
        contract=_combination_contract(
            release, universe=universe, combination=combination,
        ),
    )["probabilities"], dtype=float)
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in holdout
    ])
    inventory = frozen_feature_inventory(combination)
    ablations = {}
    for item in inventory["active"]:
        key = f'{item["family"]}::{item["feature"]}'
        ablations[key] = _evaluate(
            holdout, targets, baseline,
            universe=universe, release=release, combination=combination,
            family=item["family"], feature=item["feature"],
        )
    counts = {}
    for result in ablations.values():
        decision = result["decision"]
        counts[decision] = counts.get(decision, 0) + 1
    return {
        "rows": len(rows),
        "holdout_targets": len(holdout),
        "baseline": _metrics(targets, baseline, total_targets=len(holdout)),
        "inventory": inventory,
        "decision_counts": counts,
        "active_feature_ablations": ablations,
    }


def build_report(replay_dir: Path, release_path: Path) -> dict[str, Any]:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    return {
        "schema_version": 2,
        "mode": "READ_ONLY_ALL_ACTIVE_FEATURE_ABLATION",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {
            universe: _audit_universe(
                _read_replay(replay_dir / f"{universe}.jsonl.gz"),
                universe=universe,
                release=release,
            )
            for universe in ("atp", "wta")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.replay_dir, args.release)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            "holdout_targets": value["holdout_targets"],
            "decision_counts": value["decision_counts"],
        }
        for universe, value in report["universes"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
