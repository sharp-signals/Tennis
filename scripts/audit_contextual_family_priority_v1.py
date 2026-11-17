"""Read-only audit of recent-form, H2H and realised family priority.

The audit reuses frozen replay rows, never reads market prices and never
changes the operational release.  Candidate selection uses validation only;
the chronological holdout is evaluated once.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    CALIBRATION_FEATURE_PROFILES,
    DEFAULT_L1_GRID,
    DEFAULT_L2,
    _covered_rows,
    _directional_mask,
    _fit_logistic_elastic_net,
    _fit_preprocessor,
    _metrics,
    _paired_probability_gain,
    _predict,
    _runtime_model,
    _transform,
    calibrate_family,
    predict_family_equation,
)
from src.contextual_family_combination_v2 import _attach_predictions
from src.contextual_family_combination_v2 import (
    _effective_profiles,
    _fit_family_bundle,
    _meta_matrix,
    hierarchy_projector,
)
from src.contextual_family_combination_v10 import (
    MODEL_VERSION as COMBINATION_V10_MODEL_VERSION,
    predict_contextual_combination_v10,
)
from src.contextual_family_replay import _split


RECENT_PROFILE = "recent_tier_context_v8"
RECENT_RESULT = "contextual_recent_result_main_v7"
H2H_BASELINE = "h2h_global_shrunk_v1"
H2H_CANDIDATE = "h2h_strong_context_v2"
H2H_STRONG = "contextual_h2h_strong_five_v2"
H2H_STRONG_SURFACE = "contextual_h2h_strong_same_surface_five_v2"
FAMILIES = (
    "recent_form", "structural_strength", "surface_conditions",
    "matchup_h2h", "serve_return",
)


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _augment_h2h_candidates(rows: list[dict]) -> None:
    for row in rows:
        features = row.setdefault("features", {})
        samples = row.get("samples") or {}
        count = int(samples.get("h2h") or 0)
        margin = features.get("h2h_win_share_margin")
        features[H2H_STRONG] = (
            float(margin)
            if count >= 5 and margin is not None and abs(float(margin)) >= 0.6
            else 0.0
        )
        surface_count = int(samples.get("same_surface_h2h") or 0)
        surface_margin = features.get("same_surface_h2h_win_share_margin")
        features[H2H_STRONG_SURFACE] = (
            float(surface_margin)
            if surface_count >= 5 and surface_margin is not None
            and abs(float(surface_margin)) >= 0.6 else 0.0
        )


def _recent_result_floor_audit(split: dict[str, list[dict]]) -> dict:
    features = tuple(CALIBRATION_FEATURE_PROFILES[RECENT_PROFILE]["recent_form"])
    covered = {name: _covered_rows(rows, features) for name, rows in split.items()}
    train_preprocessor = _fit_preprocessor(covered["train"], features)
    x_train, y_train, columns = _transform(
        covered["train"], features, train_preprocessor,
    )
    x_validation, y_validation, _ = _transform(
        covered["validation"], features, train_preprocessor,
    )
    result_index = columns.index(RECENT_RESULT)
    anchor_intercept, anchor_weight, _ = _fit_logistic_elastic_net(
        x_train[:, [result_index]], y_train, l1=0.0,
        nonnegative_mask=np.asarray([True]),
    )
    del anchor_intercept
    learned_anchor = float(anchor_weight[0])
    fractions = (0.25, 0.5, 0.75, 1.0)
    candidates = []
    for fraction in fractions:
        floor = learned_anchor * fraction

        def projector(weights: np.ndarray, *, minimum: float = floor) -> np.ndarray:
            projected = np.asarray(weights, dtype=float).copy()
            projected[result_index] = max(projected[result_index], minimum)
            return projected

        intercept, weights, _ = _fit_logistic_elastic_net(
            x_train, y_train, l1=0.0, l2=DEFAULT_L2,
            nonnegative_mask=_directional_mask(columns, RECENT_PROFILE),
            weight_projector=projector,
        )
        metrics = _metrics(
            y_validation, _predict(x_validation, intercept, weights),
            total_targets=len(split["validation"]),
        )
        candidates.append({
            "fraction_of_result_only_coefficient": fraction,
            "minimum_result_coefficient": floor,
            "validation_log_loss": metrics["log_loss"],
        })
    selected = min(candidates, key=lambda item: item["validation_log_loss"])

    development = covered["train"] + covered["validation"]
    preprocessor = _fit_preprocessor(development, features)
    x_development, y_development, final_columns = _transform(
        development, features, preprocessor,
    )
    x_holdout, y_holdout, _ = _transform(
        covered["holdout"], features, preprocessor,
    )
    final_result_index = final_columns.index(RECENT_RESULT)
    _, development_anchor, _ = _fit_logistic_elastic_net(
        x_development[:, [final_result_index]], y_development, l1=0.0,
        nonnegative_mask=np.asarray([True]),
    )
    final_floor = float(development_anchor[0]) * float(
        selected["fraction_of_result_only_coefficient"]
    )

    def final_projector(weights: np.ndarray) -> np.ndarray:
        projected = np.asarray(weights, dtype=float).copy()
        projected[final_result_index] = max(
            projected[final_result_index], final_floor,
        )
        return projected

    base_intercept, base_weights, _ = _fit_logistic_elastic_net(
        x_development, y_development, l1=0.0, l2=DEFAULT_L2,
        nonnegative_mask=_directional_mask(final_columns, RECENT_PROFILE),
    )
    candidate_intercept, candidate_weights, _ = _fit_logistic_elastic_net(
        x_development, y_development, l1=0.0, l2=DEFAULT_L2,
        nonnegative_mask=_directional_mask(final_columns, RECENT_PROFILE),
        weight_projector=final_projector,
    )
    baseline = _predict(x_holdout, base_intercept, base_weights)
    candidate = _predict(x_holdout, candidate_intercept, candidate_weights)
    return {
        "result_only_train_coefficient": learned_anchor,
        "selection_partition": "validation",
        "candidates": candidates,
        "selected_fraction": selected["fraction_of_result_only_coefficient"],
        "final_minimum_result_coefficient": final_floor,
        "baseline_result_coefficient": float(base_weights[final_result_index]),
        "candidate_result_coefficient": float(candidate_weights[final_result_index]),
        "holdout_targets": len(y_holdout),
        "baseline": _metrics(y_holdout, baseline, total_targets=len(split["holdout"])),
        "candidate": _metrics(y_holdout, candidate, total_targets=len(split["holdout"])),
        "paired_gain": _paired_probability_gain(y_holdout, baseline, candidate),
    }


def _h2h_audit(split: dict[str, list[dict]]) -> dict:
    CALIBRATION_FEATURE_PROFILES[H2H_CANDIDATE] = {
        "matchup_h2h": (
            "contextual_h2h_global_shrunk_v1", H2H_STRONG, H2H_STRONG_SURFACE,
        ),
    }
    baseline_model = calibrate_family(
        split, family="matchup_h2h", feature_profile=H2H_BASELINE,
    )
    candidate_model = calibrate_family(
        split, family="matchup_h2h", feature_profile=H2H_CANDIDATE,
    )
    holdout = split["holdout"]
    baseline = predict_family_equation(holdout, _runtime_model(baseline_model))
    candidate = predict_family_equation(holdout, _runtime_model(candidate_model))
    wanted = [
        index for index in range(len(holdout))
        if baseline[index] is not None and candidate[index] is not None
    ]
    targets = np.asarray([
        float(holdout[index]["target_a_win"]) for index in wanted
    ])
    baseline_values = np.asarray([baseline[index] for index in wanted])
    candidate_values = np.asarray([candidate[index] for index in wanted])
    strong = [
        row for row in holdout
        if abs(float((row.get("features") or {}).get(H2H_STRONG) or 0.0)) > 0.0
    ]
    strong_correct = sum(
        (((row.get("features") or {})[H2H_STRONG] > 0.0)
         == bool(row["target_a_win"]))
        for row in strong
    )
    return {
        "strong_rule": "at_least_5_and_direction_consistency_at_least_80pct",
        "strong_holdout_sample": len(strong),
        "strong_direction_accuracy_pct": (
            round(100.0 * strong_correct / len(strong), 2) if strong else None
        ),
        "paired_holdout_targets": len(wanted),
        "baseline": _metrics(targets, baseline_values, total_targets=len(holdout)),
        "candidate": _metrics(targets, candidate_values, total_targets=len(holdout)),
        "paired_gain": _paired_probability_gain(
            targets, baseline_values, candidate_values,
        ),
        "candidate_coefficients": candidate_model.get("coefficients"),
    }


def _realised_priority_audit(
    split: dict[str, list[dict]], combination: dict, *, universe: str,
) -> dict:
    model = combination["runtime_family_models"]
    attached = _attach_predictions(split["holdout"], model, universe=universe)
    coefficients = combination["family_coefficients"]
    counts = {
        "usable": 0,
        "serve_above_surface": 0,
        "serve_above_recent": 0,
        "serve_above_structural": 0,
        "serve_above_primary_block": 0,
    }
    for row in attached:
        probabilities = row.get("family_probabilities") or {}
        if any(probabilities.get(family) is None for family in FAMILIES):
            continue
        impact = {
            family: abs(float(coefficients[family]) * _logit(probabilities[family]))
            for family in FAMILIES
        }
        counts["usable"] += 1
        counts["serve_above_surface"] += impact["serve_return"] > impact["surface_conditions"]
        counts["serve_above_recent"] += impact["serve_return"] > impact["recent_form"]
        counts["serve_above_structural"] += impact["serve_return"] > impact["structural_strength"]
        counts["serve_above_primary_block"] += impact["serve_return"] > (
            impact["recent_form"] + impact["structural_strength"]
        )
    usable = max(1, counts["usable"])
    return {
        **counts,
        "percentages": {
            key: round(100.0 * value / usable, 2)
            for key, value in counts.items() if key != "usable"
        },
    }


def _standardize_meta(
    x: np.ndarray, columns: list[str], means: np.ndarray, scales: np.ndarray,
) -> np.ndarray:
    result = np.asarray(x, dtype=float).copy()
    signal = np.asarray([name.endswith("__logit") for name in columns])
    result[:, signal] = (result[:, signal] - means[signal]) / scales[signal]
    return result


def _meta_scaler(x: np.ndarray, columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    means = np.zeros(x.shape[1], dtype=float)
    scales = np.ones(x.shape[1], dtype=float)
    signal = np.asarray([name.endswith("__logit") for name in columns])
    means[signal] = np.mean(x[:, signal], axis=0)
    standard = np.std(x[:, signal], axis=0)
    scales[signal] = np.where(standard > 1e-9, standard, 1.0)
    return means, scales


def _standardized_hierarchy_audit(
    split: dict[str, list[dict]], *, universe: str,
    release: dict, combination: dict,
) -> dict:
    profiles = _effective_profiles(universe, combination["family_profiles"])
    train_models = _fit_family_bundle(
        split["train"], universe=universe,
        selected_l1=combination["family_l1_selected_inside_train"],
        profiles=profiles,
    )
    development = _attach_predictions(
        split["validation"], train_models, universe=universe,
    )
    meta_split = _split(development)
    meta_train = meta_split["train"]
    meta_validation = meta_split["validation"] + meta_split["holdout"]
    x_train, y_train, columns, nonnegative = _meta_matrix(meta_train)
    x_validation, y_validation, validation_columns, _ = _meta_matrix(
        meta_validation,
    )
    if columns != validation_columns:
        raise ValueError("standardized meta columns mismatch")
    means, scales = _meta_scaler(x_train, columns)
    x_train = _standardize_meta(x_train, columns, means, scales)
    x_validation = _standardize_meta(
        x_validation, columns, means, scales,
    )
    projector = hierarchy_projector(columns)
    candidates = []
    for l1 in DEFAULT_L1_GRID:
        intercept, weights, _ = _fit_logistic_elastic_net(
            x_train, y_train, l1=float(l1), nonnegative_mask=nonnegative,
            weight_projector=projector,
        )
        metrics = _metrics(
            y_validation, _predict(x_validation, intercept, weights),
            total_targets=len(meta_validation),
        )
        candidates.append({"l1": float(l1), "log_loss": metrics["log_loss"]})
    selected_l1 = min(candidates, key=lambda item: item["log_loss"])["l1"]

    x_development, y_development, columns, nonnegative = _meta_matrix(development)
    means, scales = _meta_scaler(x_development, columns)
    x_development = _standardize_meta(
        x_development, columns, means, scales,
    )
    intercept, weights, _ = _fit_logistic_elastic_net(
        x_development, y_development, l1=selected_l1,
        nonnegative_mask=nonnegative,
        weight_projector=hierarchy_projector(columns),
    )
    holdout = _attach_predictions(
        split["holdout"], combination["runtime_family_models"],
        universe=universe,
    )
    x_holdout, targets, holdout_columns, _ = _meta_matrix(holdout)
    if columns != holdout_columns:
        raise ValueError("standardized holdout meta columns mismatch")
    x_holdout = _standardize_meta(x_holdout, columns, means, scales)
    candidate = _predict(x_holdout, intercept, weights)
    baseline = np.asarray(
        predict_contextual_combination_v10(
            split["holdout"], universe=universe, contract={
                "model_version": COMBINATION_V10_MODEL_VERSION,
                "mode": "SHADOW_ONLY",
                "universes": {universe: combination},
                "market_used": False,
                "production_effect": False,
                "promotion_authorized": False,
            },
        )["probabilities"],
        dtype=float,
    )
    return {
        "selected_l1_on_inner_validation": selected_l1,
        "validation_candidates": candidates,
        "signal_scales": {
            name.removesuffix("__logit"): round(float(scales[index]), 8)
            for index, name in enumerate(columns) if name.endswith("__logit")
        },
        "standardized_coefficients": {
            name.removesuffix("__logit"): round(float(weights[index]), 8)
            for index, name in enumerate(columns) if name.endswith("__logit")
        },
        "baseline": _metrics(targets, baseline, total_targets=len(targets)),
        "candidate": _metrics(targets, candidate, total_targets=len(targets)),
        "paired_gain": _paired_probability_gain(targets, baseline, candidate),
    }


def audit_universe(rows: list[dict], *, universe: str, release: dict) -> dict:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    split = _split(rows)
    result = {
        "split_targets": {key: len(value) for key, value in split.items()},
        "recent_result_floor": _recent_result_floor_audit(split),
        "h2h_strong": _h2h_audit(split),
        "standardized_hierarchy": _standardized_hierarchy_audit(
            split, universe=universe, release=release,
            combination=release["universes"][universe]["combination"],
        ),
    }
    result["realised_priority"] = _realised_priority_audit(
        split, release["universes"][universe]["combination"],
        universe=universe,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument(
        "--release", type=Path,
        default=Path("data/models/fenzobot-contextual-2026-11.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.release.read_text(encoding="utf-8"))
    result = {
        "schema_version": 1,
        "mode": "READ_ONLY_CHRONOLOGICAL_AUDIT",
        "market_used": False,
        "production_effect": False,
        "universes": {},
        "limitations": {
            "serve_return_indoor_outdoor": (
                "REQUIRES_REPLAY_REBUILD_WITH_EXACT_VENUE_CONTEXT"
            ),
        },
    }
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        result["universes"][universe] = audit_universe(
            rows, universe=universe, release=release,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
