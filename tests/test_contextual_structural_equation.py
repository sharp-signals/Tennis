from src.contextual_structural_equation import (
    evaluate_structural_strength,
    evaluate_structural_strength_v2,
    evaluate_structural_strength_v3,
    evaluate_structural_strength_v4,
    evaluate_structural_strength_v5,
    evaluate_structural_strength_v6,
)


def _player(rank, points=None, *, history=20, change_6m=0.0, change_12m=0.0,
            best_365=None, inactive=10, typical=None, persistence=1.0,
            dispersion=0.0, active_weeks=20):
    return {
        "current_rank": rank,
        "current_points": points,
        "historical_observation_count": history,
        "ranking_strength_change_6m": change_6m,
        "ranking_strength_change_12m": change_12m,
        "observed_best_rank_365d": best_365 or rank,
        "days_since_last_match": inactive,
        "typical_rank_365d": typical or rank,
        "current_band_persistence_365d": persistence,
        "rank_log_iqr_365d": dispersion,
        "weekly_rank_observations_365d": active_weeks,
    }


def test_40_vs_60_is_inside_structural_deadzone_without_points():
    result = evaluate_structural_strength(_player(40), _player(60))
    assert result["components"]["rank"] == 0.0
    assert result["family_signal"] == 0.0


def test_top_10_vs_200_is_material_but_bounded():
    result = evaluate_structural_strength(_player(10), _player(200))
    assert result["family_signal"] > 0.8
    assert result["family_signal"] <= 1.0


def test_rank_and_points_are_averaged_as_dependent_level_views():
    result = evaluate_structural_strength(
        _player(10, 5000), _player(100, 500),
    )
    components = result["components"]
    expected = (components["rank"] + components["points"]) / 2
    assert abs(components["current_level"] - expected) < 1e-6
    assert result["governance"]["rank_and_points_are_dependent_views"] is True


def test_former_top_player_is_not_promoted_by_peak_without_recovery():
    returning = _player(
        110, history=30, change_6m=-0.3, change_12m=-0.5,
        best_365=30, inactive=190,
    )
    stable = _player(60, history=30, change_6m=0.0, change_12m=0.0)
    result = evaluate_structural_strength(returning, stable)
    assert result["components"]["supported_recovery"] == 0.0
    assert result["direction"] == "b"


def test_supported_recent_recovery_can_only_make_a_small_adjustment():
    recovering = _player(
        80, history=30, change_6m=0.5, change_12m=0.2,
        best_365=30, inactive=15,
    )
    stable = _player(80, history=30, change_6m=0.0, change_12m=0.0)
    result = evaluate_structural_strength(recovering, stable)
    assert 0.0 < result["family_signal"] <= 0.37
    assert result["components"]["current_level"] == 0.0


def test_missing_bilateral_level_fails_without_inventing_neutrality():
    result = evaluate_structural_strength({}, {})
    assert result["status"] == "INSUFFICIENT_BILATERAL_LEVEL"
    assert result["family_signal"] is None
    assert result["market_used"] is False


def test_v2_keeps_40_vs_60_as_small_continuous_signal():
    result = evaluate_structural_strength_v2(_player(40), _player(60))
    assert 0.0 < result["family_signal"] < 0.25
    assert result["governance"]["no_hard_rank_deadzone"] is True


def test_v2_top_10_vs_200_remains_material_and_bounded():
    result = evaluate_structural_strength_v2(_player(10), _player(200))
    assert 0.85 < result["family_signal"] <= 1.0


def test_v2_inactivity_reduces_representativeness_not_direction():
    active = evaluate_structural_strength_v2(
        _player(20, inactive=10), _player(100, inactive=10),
    )
    inactive = evaluate_structural_strength_v2(
        _player(20, inactive=240), _player(100, inactive=10),
    )
    assert 0.0 < inactive["family_signal"] < active["family_signal"]
    assert inactive["direction"] == active["direction"] == "a"


def test_v2_historical_peak_never_votes_without_supported_recovery():
    former = _player(
        110, history=30, change_6m=-0.3, change_12m=-0.5,
        best_365=30, inactive=190,
    )
    stable = _player(60, history=30, change_6m=0.0, change_12m=0.0)
    result = evaluate_structural_strength_v2(former, stable)
    assert result["components"]["supported_recovery"] == 0.0
    assert result["direction"] == "b"


def test_v2_exposes_ex_ante_context_needed_for_segment_audit():
    result = evaluate_structural_strength_v2(
        _player(25, change_6m=0.3, change_12m=0.3, inactive=120),
        _player(80, inactive=15),
    )
    components = result["components"]
    assert components["trajectory_a"] == 0.3
    assert components["days_since_last_match_a"] == 120.0
    assert components["days_since_last_match_b"] == 15.0


def test_v3_preserves_full_rank_distance_without_saturation():
    gap_8x = evaluate_structural_strength_v3(_player(10), _player(80))
    gap_20x = evaluate_structural_strength_v3(_player(10), _player(200))
    key = "contextual_structural_rank_core_v3"
    assert gap_20x["candidate_features"][key] > gap_8x["candidate_features"][key]


def test_v3_inactivity_is_separate_and_does_not_change_rank_core():
    active = evaluate_structural_strength_v3(
        _player(20, inactive=10), _player(100, inactive=10),
    )
    inactive = evaluate_structural_strength_v3(
        _player(20, inactive=240), _player(100, inactive=10),
    )
    core = "contextual_structural_rank_core_v3"
    modifier = "contextual_structural_inactivity_margin_v3"
    assert active["candidate_features"][core] == inactive["candidate_features"][core]
    assert inactive["candidate_features"][modifier] < 0
    assert inactive["production_effect"] is False


def test_v4_adjacent_rank_bands_do_not_create_second_vote():
    result = evaluate_structural_strength_v4(_player(40), _player(60))
    assert result["candidate_features"][
        "contextual_structural_material_band_gap_v4"
    ] == 0.0


def test_v4_top20_vs_rank100_plus_creates_material_context():
    result = evaluate_structural_strength_v4(_player(15), _player(110))
    assert result["candidate_features"][
        "contextual_structural_material_band_gap_v4"
    ] > 0
    assert result["governance"]["rank_bands_are_residual_not_replacement"] is True


def test_v5_points_can_distinguish_similar_rankings_without_changing_rank_core():
    result = evaluate_structural_strength_v5(
        _player(20, points=2800), _player(25, points=1600),
    )
    assert result["candidate_features"]["contextual_structural_rank_core_v3"] > 0
    assert result["candidate_features"][
        "contextual_structural_points_log_ratio_v5"
    ] > 0


def test_v5_missing_points_remain_missing_and_rank_survives():
    result = evaluate_structural_strength_v5(_player(20), _player(80))
    assert result["candidate_features"][
        "contextual_structural_points_log_ratio_v5"
    ] is None
    assert result["candidate_features"]["contextual_structural_rank_core_v3"] > 0
    assert result["governance"]["missing_points_do_not_change_rank_core"] is True


def test_v6_neutralises_nearby_rankings_but_keeps_material_gap():
    nearby = evaluate_structural_strength_v6(_player(70), _player(80))
    material = evaluate_structural_strength_v6(_player(90), _player(190))
    key = "contextual_structural_material_rank_core_v6"
    assert nearby["candidate_features"][key] == 0.0
    assert material["candidate_features"][key] > 0.4


def test_v6_unrepresentative_current_rank_reduces_context_not_direction():
    stable = evaluate_structural_strength_v6(
        _player(30, typical=32, persistence=0.9, dispersion=0.05),
        _player(100, typical=105, persistence=0.9, dispersion=0.05),
    )
    unstable = evaluate_structural_strength_v6(
        _player(30, typical=80, persistence=0.1, dispersion=0.7),
        _player(100, typical=105, persistence=0.9, dispersion=0.05),
    )
    key = "contextual_structural_representative_rank_core_v6"
    assert 0 < unstable["candidate_features"][key] < stable["candidate_features"][key]
    assert unstable["governance"]["old_peak_never_restores_strength_automatically"]


def test_v6_missing_history_preserves_material_rank_but_not_fake_representativeness():
    result = evaluate_structural_strength_v6(
        _player(20, active_weeks=0), _player(100, active_weeks=0),
    )
    assert result["candidate_features"][
        "contextual_structural_material_rank_core_v6"
    ] > 0
    assert result["candidate_features"][
        "contextual_structural_representative_rank_core_v6"
    ] is None
