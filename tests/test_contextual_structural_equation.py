from src.contextual_structural_equation import (
    evaluate_structural_strength,
    evaluate_structural_strength_v2,
)


def _player(rank, points=None, *, history=20, change_6m=0.0, change_12m=0.0,
            best_365=None, inactive=10):
    return {
        "current_rank": rank,
        "current_points": points,
        "historical_observation_count": history,
        "ranking_strength_change_6m": change_6m,
        "ranking_strength_change_12m": change_12m,
        "observed_best_rank_365d": best_365 or rank,
        "days_since_last_match": inactive,
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
