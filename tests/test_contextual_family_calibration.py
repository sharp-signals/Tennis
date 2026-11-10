import math

from src.contextual_family_calibration import (
    _fit_logistic_elastic_net,
    _directional_mask,
    _build_guarded_recent_split,
    _paired_segment_diagnostics,
    _structural_segment_labels,
    _surface_segment_labels,
    calibrate_contextual_families,
    calibrate_family,
    compare_family_feature_profiles,
    compare_recent_form_feature_profiles,
)
from src.contextual_family_replay import FEATURE_FAMILIES

import numpy as np


def test_exact_surface_margins_are_directionally_constrained():
    columns = [
        "exact_surface_career_margin_shrunk",
        "exact_surface_career_margin_shrunk__missing",
    ]
    mask = _directional_mask(
        columns, "surface_exact_career_seasons_shrunk",
    )
    assert mask.tolist() == [True, False]


def test_h2h_candidate_signal_is_directionally_constrained():
    columns = ["contextual_h2h_global_shrunk_v1"]
    mask = _directional_mask(columns, "h2h_global_shrunk_v1")
    assert mask.tolist() == [True]


def test_serve_return_candidate_components_are_directionally_constrained():
    columns = [
        "service_points_won_surface_margin_shrunk_v1",
        "return_points_won_recent_deviation_v1",
    ]
    mask = _directional_mask(
        columns, "serve_return_points_recent_deviation_v1",
    )
    assert mask.tolist() == [True, True]


def test_incremental_serve_return_profile_keeps_all_directions_nonnegative():
    columns = [
        "contextual_recent_result_core_v1",
        "current_rank_log_ratio",
        "exact_surface_career_margin_shrunk",
        "service_points_won_surface_margin_shrunk_v1",
    ]
    mask = _directional_mask(columns, "primary_plus_serve_v1")
    assert mask.tolist() == [True, True, True, True]


def test_surface_only_incremental_serve_profile_is_directional():
    columns = [
        "current_rank_log_ratio",
        "service_points_won_surface_margin_shrunk_v1",
        "return_points_won_surface_margin_shrunk_v1",
    ]
    mask = _directional_mask(columns, "primary_plus_serve_surface_v1")
    assert mask.tolist() == [True, True, True]


def _row(index, *, signal=None, won=None, missing=False):
    features = {key: None for key in FEATURE_FAMILIES}
    if not missing:
        features["current_rank_log_ratio"] = float(signal)
        features["rank_change_from_last_observation"] = float((index % 5) - 2)
    return {
        "event_date": f"2026-01-{(index % 28) + 1:02d}",
        "target_a_win": bool(signal > 0) if won is None else bool(won),
        "features": features,
    }


def _split_rows():
    return {
        "train": [_row(i, signal=(-2.0 if i % 2 else 2.0)) for i in range(120)],
        "validation": [_row(i, signal=(-1.5 if i % 2 else 1.5)) for i in range(60)],
        "holdout": [_row(i, signal=(-1.0 if i % 2 else 1.0)) for i in range(60)],
    }


def test_elastic_net_learns_positive_direction():
    x = np.array([[-2.0], [-1.0], [1.0], [2.0]] * 20)
    y = np.array([0.0, 0.0, 1.0, 1.0] * 20)
    _, weights, _ = _fit_logistic_elastic_net(x, y, l1=0.001)
    assert weights[0] > 0


def test_family_equation_is_selected_on_validation_and_supported_on_holdout():
    result = calibrate_family(_split_rows(), family="structural_strength")
    assert result["status"] == "HOLDOUT_SUPPORTED"
    assert result["coefficients"]["current_rank_log_ratio"] > 0
    assert "rank_change_from_last_observation" not in result["coefficients"]
    assert result["holdout"]["model"]["log_loss"] < result["holdout"]["intercept_only_baseline"]["log_loss"]


def test_missing_values_have_explicit_indicators():
    split = _split_rows()
    split["train"][0] = _row(0, signal=1.0, missing=True)
    result = calibrate_family(split, family="structural_strength")
    assert result["preprocessor"]["missing_policy"] == "median_imputation_plus_explicit_missing_indicator"
    assert "current_rank_log_ratio__missing" in result["coefficients"]


def test_holdout_extreme_does_not_enter_preprocessor():
    split = _split_rows()
    split["holdout"][0]["features"]["current_rank_log_ratio"] = 1_000_000.0
    result = calibrate_family(split, family="structural_strength")
    assert result["preprocessor"]["features"]["current_rank_log_ratio"]["upper"] < 100.0


def test_insufficient_family_is_not_fitted():
    empty = {"train": [], "validation": [], "holdout": []}
    result = calibrate_family(empty, family="matchup_h2h")
    assert result["status"] == "INSUFFICIENT_COVERAGE"


def test_all_families_remain_separate_and_overall_probability_is_absent():
    rows = _split_rows()["train"] + _split_rows()["validation"] + _split_rows()["holdout"]
    # Give each group distinct dates so the chronological splitter has material.
    for i, row in enumerate(rows):
        row["event_date"] = f"{2020 + i // 100:04d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
    result = calibrate_contextual_families(rows, universe="atp")
    assert set(result["families"]) == set(FEATURE_FAMILIES.values())
    assert result["families_combined"] is False
    assert result["overall_probability_fitted"] is False
    assert result["fair_odd_fitted"] is False


def test_calibration_never_uses_market_or_changes_production():
    rows = _split_rows()["train"] + _split_rows()["validation"] + _split_rows()["holdout"]
    for i, row in enumerate(rows):
        row["event_date"] = f"{2020 + i // 100:04d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
    result = calibrate_contextual_families(rows, universe="wta")
    assert result["market_used"] is False
    assert result["production_effect"] is False
    assert result["universe"] == "wta"


def test_coefficients_and_metrics_are_finite():
    result = calibrate_family(_split_rows(), family="structural_strength")
    assert math.isfinite(result["intercept"])
    assert all(math.isfinite(value) for value in result["coefficients"].values())
    assert math.isfinite(result["holdout"]["model"]["brier"])


def test_contextual_profile_uses_engineered_structural_signal_only():
    split = _split_rows()
    for part in split.values():
        for row in part:
            row["features"]["contextual_structural_signal_v1"] = (
                1.0 if row["target_a_win"] else -1.0
            )
    result = calibrate_family(
        split, family="structural_strength", feature_profile="contextual_v1",
    )
    assert result["features"] == ["contextual_structural_signal_v1"]
    assert result["coefficients"]["contextual_structural_signal_v1"] >= 0
    assert result["feature_profile"] == "contextual_v1"


def test_profile_comparison_uses_same_holdout_targets_and_stays_market_free():
    rows = _split_rows()["train"] + _split_rows()["validation"] + _split_rows()["holdout"]
    for i, row in enumerate(rows):
        row["event_date"] = f"{2020 + i // 60:04d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
        direction = 1.0 if row["target_a_win"] else -1.0
        row["features"]["contextual_structural_signal_v1"] = direction
        row["features"]["contextual_surface_signal_v1"] = direction
        row["features"]["same_surface_result_balance_90d"] = -direction
        row["features"]["career_surface_win_rate_margin"] = -direction
    result = compare_family_feature_profiles(rows, universe="atp")
    assert result["comparisons"]["structural_strength"]["paired_holdout_targets"] > 0
    assert result["comparisons"]["surface_conditions"]["paired_holdout_targets"] > 0
    assert result["market_used"] is False
    assert result["production_effect"] is False


def test_v2_profile_selects_continuous_structural_feature():
    split = _split_rows()
    for part in split.values():
        for row in part:
            row["features"]["contextual_structural_signal_v2"] = (
                0.5 if row["target_a_win"] else -0.5
            )
    result = calibrate_family(
        split, family="structural_strength", feature_profile="contextual_v2",
    )
    assert result["features"] == ["contextual_structural_signal_v2"]
    assert result["coefficients"]["contextual_structural_signal_v2"] >= 0


def test_v3_profile_keeps_rank_anchor_and_separate_modifiers():
    split = _split_rows()
    names = (
        "contextual_structural_rank_core_v3",
        "contextual_structural_trajectory_margin_v3",
        "contextual_structural_inactivity_margin_v3",
        "contextual_structural_recovery_margin_v3",
    )
    for part in split.values():
        for row in part:
            direction = 1.0 if row["target_a_win"] else -1.0
            for index, name in enumerate(names, start=1):
                row["features"][name] = direction / index
    result = calibrate_family(
        split, family="structural_strength", feature_profile="contextual_v3",
    )
    assert result["features"] == list(names)
    assert all(result["coefficients"][name] >= 0 for name in names)


def test_v4_profile_adds_material_rank_band_as_residual():
    split = _split_rows()
    names = (
        "contextual_structural_rank_core_v3",
        "contextual_structural_trajectory_margin_v3",
        "contextual_structural_inactivity_margin_v3",
        "contextual_structural_recovery_margin_v3",
        "contextual_structural_material_band_gap_v4",
    )
    for part in split.values():
        for row in part:
            direction = 1.0 if row["target_a_win"] else -1.0
            for index, name in enumerate(names, start=1):
                row["features"][name] = direction / index
    result = calibrate_family(
        split, family="structural_strength", feature_profile="contextual_v4",
    )
    assert result["features"] == list(names)
    assert result["coefficients"]["contextual_structural_material_band_gap_v4"] >= 0


def test_v5_profile_tests_points_beyond_rank_anchor():
    split = _split_rows()
    names = (
        "contextual_structural_rank_core_v3",
        "contextual_structural_trajectory_margin_v3",
        "contextual_structural_inactivity_margin_v3",
        "contextual_structural_recovery_margin_v3",
        "contextual_structural_points_log_ratio_v5",
    )
    for part in split.values():
        for row in part:
            direction = 1.0 if row["target_a_win"] else -1.0
            for index, name in enumerate(names, start=1):
                row["features"][name] = direction / index
    result = calibrate_family(
        split, family="structural_strength", feature_profile="contextual_v5",
    )
    assert result["features"] == list(names)
    assert result["coefficients"]["contextual_structural_points_log_ratio_v5"] >= 0


def test_v6_profile_keeps_level_context_and_friction_in_one_family():
    split = _split_rows()
    names = (
        "contextual_structural_material_rank_core_v6",
        "contextual_structural_representative_rank_core_v6",
        "contextual_structural_points_log_ratio_v6",
        "contextual_structural_trajectory_margin_v3",
        "contextual_structural_inactivity_margin_v3",
        "contextual_structural_recovery_margin_v3",
    )
    for part in split.values():
        for row in part:
            direction = 1.0 if row["target_a_win"] else -1.0
            for index, name in enumerate(names, start=1):
                row["features"][name] = direction / index
    result = calibrate_family(
        split, family="structural_strength", feature_profile="contextual_v6",
    )
    assert result["features"] == list(names)
    assert all(result["coefficients"][name] >= 0 for name in names)


def test_structural_segments_are_ex_ante_and_can_overlap():
    row = {
        "diagnostics": {"rank_a": 10, "rank_b": 120},
        "candidate_equation_audit": {
            "structural_strength_v2": {"components": {
                "days_since_last_match_a": 12,
                "days_since_last_match_b": 120,
                "trajectory_a": 0.3,
                "trajectory_b": 0.0,
                "supported_recovery": 0.2,
            }}
        },
    }
    labels = _structural_segment_labels(row)
    assert "rank_gap_extreme_ge_8x" in labels
    assert "elite_top20_vs_rank100_plus" in labels
    assert "inactivity_over_90d" in labels
    assert "ranking_trajectory_material" in labels
    assert "supported_ranking_recovery" in labels


def test_v6_structural_segments_expose_materiality_and_representativeness():
    row = {
        "diagnostics": {"rank_a": 70, "rank_b": 80},
        "candidate_equation_audit": {
            "structural_strength_v6": {"components": {
                "material_rank_core": 0.0,
                "bilateral_representativeness": 0.42,
                "supported_recovery": 0.0,
            }}
        },
    }
    labels = _structural_segment_labels(row)
    assert "ranking_material_gap_neutral" in labels
    assert "ranking_representativeness_low" in labels


def test_surface_segments_are_ex_ante_and_include_sample_transition_and_context():
    row = {
        "surface": "hard",
        "diagnostics": {"venue": "indoor", "pace": "fast"},
        "samples": {"surface_a": 12, "surface_b": 20},
        "candidate_equation_audit": {
            "surface_conditions": {"components": {
                "transition_signal": -1.0,
                "selected_specific_context": "pace_component",
            }}
        },
    }

    labels = _surface_segment_labels(row)

    assert "surface_hard" in labels
    assert "venue_indoor" in labels
    assert "pace_fast" in labels
    assert "bilateral_surface_sample_5_14" in labels
    assert "surface_transition_present" in labels
    assert "specific_context_available" in labels


def test_segment_diagnostics_report_paired_gain_and_confidence():
    rows = [
        ({"target_a_win": True}, 0.6, 0.8),
        ({"target_a_win": False}, 0.4, 0.2),
    ]
    result = _paired_segment_diagnostics(rows)["all"]
    assert result["paired_targets"] == 2
    assert result["contextual_log_loss_gain"] > 0
    assert result["verdict"] == "CONTEXTUAL_BETTER"


def test_recent_form_profiles_follow_human_order_and_remain_shadow_only():
    rows = _split_rows()["train"] + _split_rows()["validation"] + _split_rows()["holdout"]
    names = (
        "contextual_recent_result_core_v1",
        "contextual_recent_competitiveness_v1",
        "contextual_recent_win_quality_v1",
        "contextual_recent_loss_context_v1",
    )
    for i, row in enumerate(rows):
        row["event_date"] = f"{2020 + i // 60:04d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"
        direction = 1.0 if row["target_a_win"] else -1.0
        for index, name in enumerate(names, start=1):
            row["features"][name] = direction / index
        row["features"]["contextual_recent_bad_loss_penalty_v2"] = direction / 5

    result = compare_recent_form_feature_profiles(rows, universe="atp")

    assert result["status"] == "OBSERVATIONAL_ONLY"
    assert result["paired_holdout_targets"] > 0
    assert result["profiles"]["recent_v0"]["features"] == [names[0]]
    assert result["profiles"]["recent_v3"]["features"] == list(names)
    assert result["profiles"]["recent_guarded_v4"]["features"] == [
        "contextual_recent_result_core_v1",
        "contextual_recent_competitiveness_residual_v2",
        "contextual_recent_win_quality_v1",
        "contextual_recent_bad_loss_penalty_v2",
    ]
    assert all(
        result["profiles"]["recent_v3"]["coefficients"][name] >= 0
        for name in names
    )
    assert result["loss_context_promotion_blocked"] is True
    assert all(
        item["gain_95pct_ci"] is not None
        for item in result["incremental_comparisons"].values()
    )
    assert result["market_used"] is False
    assert result["production_effect"] is False


def test_guarded_competitiveness_removes_train_fitted_result_component():
    split = {"train": [], "validation": [], "holdout": []}
    for part in split:
        for result in (-1.0, -0.5, 0.5, 1.0):
            split[part].append({
                "target_a_win": result > 0,
                "features": {
                    "contextual_recent_result_core_v1": result,
                    "contextual_recent_competitiveness_v1": 4.0 * result + 0.25,
                },
            })

    guarded, audit = _build_guarded_recent_split(split)

    assert audit["fit_partition"] == "train_only"
    assert audit["intercept_forced_to_zero_for_antisymmetry"] is True
    assert math.isclose(audit["result_to_margin_slope"], 4.0)
    # The common result-driven part is removed; only the small residual stays.
    assert all(
        abs(row["features"]["contextual_recent_competitiveness_residual_v2"]) < 0.5
        for row in guarded["holdout"]
    )
