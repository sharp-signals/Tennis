"""Rolling, market-free refit audit for flagged and correlated feature groups."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.audit_serve_return_exact_context_v2 import _paired_diagnostics
from scripts.build_contextual_family_combination_v18 import (
    _fit_zero_intercept_slope,
    _predict,
)
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    CALIBRATION_FEATURE_PROFILES,
    _metrics,
    _paired_probability_gain,
    fit_family_equation,
)
from src.contextual_family_combination_v2 import (
    _fit_family_bundle,
    _surface_context,
    _surface_vote_enabled,
)


FOLDS = (
    ("early", 0.40, 0.50, 0.65),
    ("middle", 0.55, 0.65, 0.80),
    ("late", 0.70, 0.80, 1.00),
)

CANDIDATES = {
    "without_recent_return_deviation": {
        "serve_return_points_recent_deviation_v1": (
            "return_points_won_recent_deviation_v1",
        ),
    },
    "without_current_surface_margin": {
        "surface_exact_tier_adjusted_v8": (
            "exact_surface_current_margin_shrunk",
        ),
    },
    "without_current_surface_tier_credit": {
        "surface_exact_tier_adjusted_v8": (
            "exact_surface_tier_win_credit_current_v8",
        ),
    },
    "without_both_current_surface_inputs": {
        "surface_exact_tier_adjusted_v8": (
            "exact_surface_current_margin_shrunk",
            "exact_surface_tier_win_credit_current_v8",
        ),
    },
    "without_all_three_flagged_inputs": {
        "serve_return_points_recent_deviation_v1": (
            "return_points_won_recent_deviation_v1",
        ),
        "surface_exact_tier_adjusted_v8": (
            "exact_surface_current_margin_shrunk",
            "exact_surface_tier_win_credit_current_v8",
        ),
    },
    "recent_without_raw_results": {
        "recent_tier_context_v8": (
            "contextual_recent_result_main_v7",
            "contextual_recent_result_lower_main_v5",
            "contextual_recent_result_challenger_v5",
        ),
    },
    "recent_without_competitiveness": {
        "recent_tier_context_v8": (
            "contextual_recent_competitiveness_main_v7",
            "contextual_recent_competitiveness_lower_main_v5",
            "contextual_recent_competitiveness_challenger_v5",
        ),
    },
    "recent_without_quality_and_tier": {
        "recent_tier_context_v8": (
            "contextual_recent_win_quality_v1",
            "contextual_recent_tier_win_credit_v7",
        ),
    },
    "recent_compact_main_quality_tier": {
        "recent_tier_context_v8": (
            "contextual_recent_result_lower_main_v5",
            "contextual_recent_competitiveness_lower_main_v5",
            "contextual_recent_result_challenger_v5",
            "contextual_recent_competitiveness_challenger_v5",
        ),
    },
}


def rolling_splits(rows: list[dict]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (
        row["event_date"], str(row.get("player_a")), str(row.get("player_b")),
    ))
    size = len(ordered)

    def boundary(fraction: float) -> int:
        index = min(size, max(0, int(size * fraction)))
        if 0 < index < size:
            day = ordered[index - 1]["event_date"]
            while index < size and ordered[index]["event_date"] == day:
                index += 1
        return index

    result = []
    for name, train_end, validation_end, test_end in FOLDS:
        train_index = boundary(train_end)
        validation_index = boundary(validation_end)
        test_index = boundary(test_end)
        result.append({
            "name": name,
            "train": ordered[:train_index],
            "validation": ordered[train_index:validation_index],
            "test": ordered[validation_index:test_index],
        })
    return result


@contextmanager
def _temporary_removals(removals: dict[str, tuple[str, ...]]):
    originals = {}
    try:
        for profile, removed in removals.items():
            if profile not in CALIBRATION_FEATURE_PROFILES:
                continue
            originals[profile] = copy.deepcopy(
                CALIBRATION_FEATURE_PROFILES[profile]
            )
            for family, features in originals[profile].items():
                CALIBRATION_FEATURE_PROFILES[profile][family] = tuple(
                    feature for feature in features if feature not in removed
                )
        yield
    finally:
        for profile, value in originals.items():
            CALIBRATION_FEATURE_PROFILES[profile] = value


def _changed_families(profiles: dict[str, str], removals: dict) -> list[str]:
    return [
        family for family, profile in profiles.items()
        if profile in removals
        and any(
            feature in CALIBRATION_FEATURE_PROFILES[profile].get(family, ())
            for feature in removals[profile]
        )
    ]


def _refit_changed_models(
    train: list[dict], baseline_models: dict[str, Any], *, universe: str,
    combination: dict[str, Any], removals: dict[str, tuple[str, ...]],
) -> tuple[dict[str, Any], list[str]]:
    profiles = combination["family_profiles"]
    changed = _changed_families(profiles, removals)
    models = copy.deepcopy(baseline_models)
    with _temporary_removals(removals):
        for family in changed:
            profile = profiles[family]
            selected = combination["family_l1_selected_inside_train"][family]
            if family == "surface_conditions":
                models[family] = {
                    context: fit_family_equation(
                        [row for row in train if _surface_context(row) == context],
                        family=family,
                        feature_profile=profile,
                        l1=float(selected.get(context, 0.1)),
                        allow_missingness_vote=False,
                    )
                    for context in ("hard_outdoor", "hard_indoor", "clay", "grass")
                    if _surface_vote_enabled(universe, context)
                }
            else:
                models[family] = fit_family_equation(
                    train,
                    family=family,
                    feature_profile=profile,
                    l1=float(selected),
                    allow_missingness_vote=False,
                )
    return models, changed


def _calibrated_prediction(
    validation: list[dict], test: list[dict], model: dict[str, Any],
    *, universe: str,
) -> tuple[np.ndarray, float]:
    hierarchy = model["realized_hierarchy"]
    recent = hierarchy["recent_form_governance"]
    raw = _predict(
        validation, model, universe=universe,
        h2h_multiplier=float(hierarchy.get("h2h_multiplier", 1.0)),
        slope=1.0,
        result_weight_floor=float(recent["result_weight_floor"]),
        opposing_modifier_cap=float(recent["opposing_modifier_cap"]),
        unanimous_policy=hierarchy["unanimous_policy"],
    )
    logits = np.log(np.clip(raw, 1e-9, 1.0) / np.clip(1.0 - raw, 1e-9, 1.0))
    targets = np.asarray([
        1.0 if row["target_a_win"] else 0.0 for row in validation
    ])
    slope = _fit_zero_intercept_slope(logits, targets)
    return _predict(
        test, model, universe=universe,
        h2h_multiplier=float(hierarchy.get("h2h_multiplier", 1.0)),
        slope=slope,
        result_weight_floor=float(recent["result_weight_floor"]),
        opposing_modifier_cap=float(recent["opposing_modifier_cap"]),
        unanimous_policy=hierarchy["unanimous_policy"],
    ), slope


def _decision(paired: dict, fold_gains: list[float], base: dict, tested: dict) -> str:
    positive = sum(value > 0 for value in fold_gains)
    negative = sum(value < 0 for value in fold_gains)
    calibration_not_worse = float(tested["ece_10"]) <= float(base["ece_10"])
    brier_not_worse = float(tested["brier"]) <= float(base["brier"])
    if (
        paired["status"] == "SUPPORTED" and positive >= 2
        and brier_not_worse and calibration_not_worse
    ):
        return "CANDIDATE_SUPPORTED"
    if paired["status"] == "REJECTED" or (negative >= 2 and not brier_not_worse):
        return "CANDIDATE_REJECTED"
    return "INCONCLUSIVE_KEEP_CURRENT_RELEASE"


def audit_universe(rows: list[dict], *, universe: str, release: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    combination = release["universes"][universe]["combination"]
    fold_results = []
    aggregate_targets = []
    aggregate_baseline = []
    aggregate_candidates = {name: [] for name in CANDIDATES}
    applicable = {name: False for name in CANDIDATES}
    for fold in rolling_splits(rows):
        baseline_models = _fit_family_bundle(
            fold["train"], universe=universe,
            selected_l1=combination["family_l1_selected_inside_train"],
            profiles=combination["family_profiles"],
            allow_missingness_vote=False,
        )
        baseline_model = copy.deepcopy(combination)
        baseline_model["runtime_family_models"] = baseline_models
        baseline, baseline_slope = _calibrated_prediction(
            fold["validation"], fold["test"], baseline_model,
            universe=universe,
        )
        targets = np.asarray([
            1.0 if row["target_a_win"] else 0.0 for row in fold["test"]
        ])
        aggregate_targets.extend(targets)
        aggregate_baseline.extend(baseline)
        candidates = {}
        for name, removals in CANDIDATES.items():
            models, changed = _refit_changed_models(
                fold["train"], baseline_models,
                universe=universe, combination=combination, removals=removals,
            )
            if not changed:
                continue
            applicable[name] = True
            candidate_model = copy.deepcopy(combination)
            candidate_model["runtime_family_models"] = models
            probability, slope = _calibrated_prediction(
                fold["validation"], fold["test"], candidate_model,
                universe=universe,
            )
            aggregate_candidates[name].extend(probability)
            candidates[name] = {
                "changed_families": changed,
                "slope": round(float(slope), 8),
                "metrics": _metrics(
                    targets, probability, total_targets=len(targets),
                ),
                "paired_gain": _paired_probability_gain(
                    targets, baseline, probability,
                ),
            }
        fold_results.append({
            "name": fold["name"],
            "train_through": fold["train"][-1]["event_date"],
            "test_from": fold["test"][0]["event_date"],
            "test_through": fold["test"][-1]["event_date"],
            "targets": len(targets),
            "baseline_slope": round(float(baseline_slope), 8),
            "baseline": _metrics(targets, baseline, total_targets=len(targets)),
            "candidates": candidates,
        })
    targets = np.asarray(aggregate_targets)
    baseline = np.asarray(aggregate_baseline)
    baseline_metrics = _metrics(targets, baseline, total_targets=len(targets))
    candidates = {}
    test_rows = [row for fold in rolling_splits(rows) for row in fold["test"]]
    for name in CANDIDATES:
        if not applicable[name]:
            candidates[name] = {"status": "NOT_APPLICABLE_TO_RELEASE"}
            continue
        tested = np.asarray(aggregate_candidates[name])
        tested_metrics = _metrics(targets, tested, total_targets=len(targets))
        paired = _paired_probability_gain(targets, baseline, tested)
        fold_gains = [
            float(fold["candidates"][name]["paired_gain"]["log_loss_gain"])
            for fold in fold_results if name in fold["candidates"]
        ]
        candidates[name] = {
            "status": "EVALUATED",
            "removed_features": CANDIDATES[name],
            "candidate": tested_metrics,
            "paired_gain": paired,
            "fold_log_loss_gains": fold_gains,
            "diagnostics": _paired_diagnostics(
                test_rows, list(range(len(test_rows))),
                targets, baseline, tested,
            ),
            "decision": _decision(
                paired, fold_gains, baseline_metrics, tested_metrics,
            ),
        }
    return {
        "source_rows": len(rows),
        "rolling_test_targets": len(targets),
        "baseline": baseline_metrics,
        "folds": fold_results,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.release.read_text(encoding="utf-8"))
    report = {
        "schema_version": 1,
        "mode": "READ_ONLY_ROLLING_REFIT_AUDIT",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {
            universe: audit_universe(
                _read_replay(args.replay_dir / f"{universe}.jsonl.gz"),
                universe=universe, release=release,
            )
            for universe in ("atp", "wta")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            name: result.get("decision", result.get("status"))
            for name, result in value["candidates"].items()
        }
        for universe, value in report["universes"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
