import math

from src.contextual_family_replay import (
    _exact_surface_features,
    _recent_circuit_downshift,
    _surface,
    adjust_recent_result_for_loss_context,
    build_contextual_target_row,
    build_contextual_family_replay_rows,
    evaluate_contextual_family_replay,
    replay_contextual_families,
)

import pandas as pd


def _observation(day, *, won, level, context="hard_indoor"):
    return {
        "event_date": pd.Timestamp(day).date(),
        "won": won,
        "competition_level": level,
        "surface_context": context,
    }


def test_recent_circuit_downshift_penalizes_demotion_but_not_upgrade():
    cutoff = pd.Timestamp("2026-11-11").date()
    demoted = [
        *[_observation(f"2026-0{month}-01", won=True, level="ATP 500") for month in range(1, 7)],
        *[_observation(f"2026-10-{day:02d}", won=True, level="Challenger 100") for day in range(1, 5)],
    ]
    upgraded = [
        *[_observation(f"2026-0{month}-01", won=True, level="Challenger 100") for month in range(1, 7)],
        *[_observation(f"2026-10-{day:02d}", won=True, level="ATP 500") for day in range(1, 5)],
    ]
    penalty, audit = _recent_circuit_downshift(demoted, cutoff=cutoff)
    upgrade_penalty, _ = _recent_circuit_downshift(upgraded, cutoff=cutoff)
    assert penalty is not None and penalty > 0
    assert audit["status"] == "READY"
    assert upgrade_penalty == 0.0


def test_exact_surface_tier_credit_distinguishes_equal_win_rates_by_level():
    cutoff = pd.Timestamp("2026-11-11").date()
    masters = [
        _observation(f"2026-10-{day:02d}", won=day <= 2, level="Masters 1000")
        for day in range(1, 5)
    ]
    challengers = [
        _observation(f"2026-10-{day:02d}", won=day <= 2, level="Challenger 100")
        for day in range(1, 5)
    ]
    features, audit = _exact_surface_features(
        masters, challengers, context="hard_indoor", cutoff=cutoff,
    )
    assert features["exact_surface_current_margin_shrunk"] == 0.0
    assert features["exact_surface_tier_win_credit_current_v8"] > 0
    assert audit["tier_adjusted_win_credit"]["a"]["current_season"]["sample"] == 4


def test_provider_indoor_hard_label_matches_historical_hard_surface():
    assert _surface("I.hard") == "hard"
    assert _surface("Hard") == "hard"
    assert _surface("hard_indoor") == "hard"


def _match(day, winner, loser, *, surface="Hard", winner_rank=20, loser_rank=40,
           score="6-4 6-4", service=True, indoor=None, pace=None,
           competition_scope=None, competition_level=None):
    row = {
        "tourney_date": day, "winner_name": winner, "loser_name": loser,
        "surface": surface, "winner_rank": winner_rank,
        "loser_rank": loser_rank, "score": score,
        "indoor": indoor, "court_pace_bucket": pace,
        "_history_competition_scope": competition_scope,
        "tourney_level": competition_level,
    }
    if service:
        row.update({
            "w_svpt": 100, "w_1stIn": 60, "w_1stWon": 42, "w_2ndWon": 20,
            "w_bpSaved": 5, "w_bpFaced": 8, "w_SvGms": 12,
            "l_svpt": 100, "l_1stIn": 60, "l_1stWon": 36, "l_2ndWon": 16,
            "l_bpSaved": 4, "l_bpFaced": 9, "l_SvGms": 11,
        })
    return row


def test_player_orientation_is_independent_of_winner():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Zulu", "Alpha"),
    ]), universe="atp")
    assert rows[0]["player_a"] == "alpha"
    assert rows[0]["player_b"] == "zulu"
    assert rows[0]["target_a_win"] is False


def test_same_day_results_are_not_visible_to_each_other():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Beta"),
        _match("20260101", "Alpha", "Gamma"),
    ]), universe="atp")
    assert rows[0]["samples"]["recent_a"] == 0
    assert rows[1]["samples"]["recent_a"] == 0


def test_prior_day_is_available_but_partial_history_is_not_neutral():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Beta"),
        _match("20260102", "Alpha", "Gamma"),
    ]), universe="atp")
    second = rows[1]
    assert second["samples"]["recent_a"] == 1
    assert second["features"]["recent_result_balance_90d"] is None
    assert second["family_states"]["recent_form"]["data_state"] == "INSUFFICIENT_SAMPLE"


def test_exact_match_date_takes_precedence_over_tournament_start_date():
    first = _match("20260101", "Alpha", "Beta")
    second = _match("20260101", "Alpha", "Gamma")
    first["date"] = "20260102"
    second["date"] = "20260103"
    rows = build_contextual_family_replay_rows(
        pd.DataFrame([first, second]), universe="atp",
    )
    assert rows[1]["samples"]["recent_a"] == 1
    assert rows[1]["date_source"] == "match_date"


def test_bilateral_history_produces_raw_margins_without_probability():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Other A", winner_rank=15, loser_rank=80),
        _match("20260101", "Other B", "Beta", winner_rank=25, loser_rank=45),
        _match("20260105", "Alpha", "Beta", winner_rank=14, loser_rank=44),
    ]), universe="atp")
    target = rows[-1]
    assert target["features"]["recent_result_balance_90d"] > 0
    assert target["features"]["current_rank_log_ratio"] > 0
    assert target["family_states"]["recent_form"]["data_state"] == "OBSERVED"
    assert "probability" not in target
    assert target["market_used"] is False


def test_confirmed_no_prior_h2h_is_observed_none():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Other A"),
        _match("20260101", "Beta", "Other B"),
        _match("20260102", "Alpha", "Beta"),
    ]), universe="atp")
    target = rows[-1]
    assert target["samples"]["h2h"] == 0
    assert target["family_states"]["matchup_h2h"] == {
        "data_state": "OBSERVED_NONE", "signal_state": "NONE",
    }


def test_prior_h2h_is_context_not_a_prefitted_weight():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Beta"),
        _match("20260105", "Beta", "Alpha"),
    ]), universe="atp")
    target = rows[-1]
    assert target["samples"]["h2h"] == 1
    assert target["features"]["h2h_win_share_margin"] == 1.0
    assert target["family_states"]["matchup_h2h"]["signal_state"] == "UNSCORED"


def test_service_family_degrades_without_point_aggregates():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Other A", service=False),
        _match("20260101", "Beta", "Other B", service=False),
        _match("20260102", "Alpha", "Beta", service=False),
    ]), universe="atp")
    assert rows[-1]["family_states"]["serve_return"]["data_state"] == "INSUFFICIENT_SAMPLE"
    assert rows[-1]["features"]["hold_surface_margin"] is None


def test_precomputed_surface_context_recovers_missing_raw_surface():
    first = _match("20260101", "Alpha", "Other A", surface=None)
    second = _match("20260101", "Beta", "Other B", surface=None)
    target = _match("20260102", "Alpha", "Beta", surface=None)
    for row in (first, second, target):
        row["surface_context"] = "hard_indoor"
    rows = build_contextual_family_replay_rows(
        pd.DataFrame([first, second, target]), universe="atp",
    )
    assert rows[-1]["surface"] == "hard"
    assert rows[-1]["samples"]["exact_surface_career_a"] == 1
    assert rows[-1]["samples"]["exact_surface_career_b"] == 1


def test_retirement_is_excluded_from_targets_and_future_history():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Beta", score="6-4 2-1 RET"),
        _match("20260102", "Alpha", "Gamma"),
    ]), universe="atp")
    assert len(rows) == 1
    assert rows[0]["samples"]["recent_a"] == 0


def test_evaluation_partitions_chronologically_and_fits_nothing():
    frame = pd.DataFrame([
        _match(f"2026010{day}", "Alpha" if day % 2 else "Beta",
               "Beta" if day % 2 else "Alpha", winner_rank=10, loser_rank=30)
        for day in range(1, 8)
    ])
    result = evaluate_contextual_family_replay(
        build_contextual_family_replay_rows(frame, universe="atp")
    )
    assert all(result["split_targets"][part] > 0 for part in ("train", "validation", "holdout"))
    assert result["weights_fitted"] is False
    assert result["probabilities_fitted"] is False
    assert result["market_used"] is False


def test_wrapper_is_observational_and_has_no_production_effect():
    report = replay_contextual_families(pd.DataFrame([
        _match("20260101", "Alpha", "Beta"),
    ]), universe="wta")
    assert report["production_effect"] is False
    assert report["market_used"] is False
    assert report["result"]["player_orientation"] == "alphabetical_name_order_independent_of_result"


def test_prospective_target_uses_exactly_the_replay_feature_definitions():
    frame = pd.DataFrame([
        _match("20260101", "Alpha", "Other A", winner_rank=15, loser_rank=80),
        _match("20260102", "Other B", "Beta", winner_rank=25, loser_rank=45),
        _match("20260105", "Alpha", "Beta", winner_rank=14, loser_rank=44),
    ])
    replay = build_contextual_family_replay_rows(frame, universe="atp")[-1]
    target = build_contextual_target_row(
        frame, universe="atp", player_a="Alpha", player_b="Beta",
        cutoff=pd.Timestamp("2026-01-05").date(), surface="Hard",
        rank_a=14, rank_b=44,
    )
    assert target["features"] == replay["features"]
    assert target["samples"] == replay["samples"]
    assert target["family_states"] == replay["family_states"]
    assert target["market_used"] is False


def test_main_tour_form_is_separate_from_challenger_form_and_uses_all_rows():
    frame = pd.DataFrame([
        _match("20261001", "Alpha", "Main One", winner_rank=100, loser_rank=80,
               competition_scope="main", competition_level="250"),
        _match("20261002", "Alpha", "Ch One", winner_rank=100, loser_rank=180,
               competition_scope="challenger", competition_level="Challenger"),
        _match("20261003", "Alpha", "Ch Two", winner_rank=98, loser_rank=170,
               competition_scope="challenger", competition_level="Challenger"),
        _match("20261004", "Alpha", "Ch Three", winner_rank=95, loser_rank=160,
               competition_scope="challenger", competition_level="Challenger"),
        _match("20261001", "Beta", "Main Two", winner_rank=20, loser_rank=35,
               competition_scope="main", competition_level="250"),
        _match("20261005", "Beta", "Main Three", winner_rank=18, loser_rank=30,
               competition_scope="main", competition_level="250"),
    ])
    target = build_contextual_target_row(
        frame, universe="atp", player_a="Alpha", player_b="Beta",
        cutoff=pd.Timestamp("2026-10-10").date(), surface="Hard",
        rank_a=95, rank_b=18, target_tier="250",
    )
    audit = target["candidate_equation_audit"]["recent_form_tier_reliable_v5"]
    assert target["samples"]["recent_a"] == 4
    assert audit["buckets"]["main"]["result"]["a_sample"] == 1
    assert audit["buckets"]["challenger"]["result"]["a_sample"] == 3
    assert target["features"]["contextual_recent_result_main_v7"] < 0.0
    assert target["features"]["contextual_recent_result_challenger_v5"] > 0.0
    assert target["samples"]["surface_a"] == 1


def test_recent_tier_win_credit_values_masters_run_above_challenger_run():
    rows = pd.DataFrame([
        _match("20261001", "Ruud", "A", winner_rank=10, loser_rank=40,
             competition_scope="main", competition_level="M"),
        _match("20261003", "Ruud", "B", winner_rank=10, loser_rank=30,
             competition_scope="main", competition_level="M"),
        _match("20261005", "Ruud", "C", winner_rank=10, loser_rank=20,
             competition_scope="main", competition_level="M"),
        _match("20261007", "Ruud", "D", winner_rank=10, loser_rank=15,
             competition_scope="main", competition_level="M"),
        _match("20261001", "Shevchenko", "E", winner_rank=100, loser_rank=150,
             competition_scope="challenger", competition_level="C"),
        _match("20261003", "Shevchenko", "F", winner_rank=100, loser_rank=140,
             competition_scope="challenger", competition_level="C"),
    ])
    target = build_contextual_target_row(
        rows, universe="atp", player_a="Ruud", player_b="Shevchenko",
        cutoff=pd.Timestamp("2026-10-10").date(), surface="Hard", target_tier="250",
        rank_a=10, rank_b=100,
    )
    assert target["features"]["contextual_recent_tier_win_credit_v7"] > 0.35
    audit = target["candidate_equation_audit"]["recent_form_tier_reliable_v5"]
    assert audit["tier_win_credit"]["a_credit"] > 0.45
    assert audit["tier_win_credit"]["b_credit"] < 0.06


def test_exact_surface_features_do_not_mix_indoor_and_outdoor_hard():
    frame = pd.DataFrame([
        _match("20260101", "Alpha", "Other A", indoor=True),
        _match("20260102", "Beta", "Other B", indoor=False),
        _match("20260105", "Alpha", "Beta", indoor=True),
    ])
    target = build_contextual_family_replay_rows(frame, universe="atp")[-1]
    assert target["diagnostics"]["surface_context"] == "hard_indoor"
    assert target["samples"]["exact_surface_career_a"] == 1
    assert target["samples"]["exact_surface_career_b"] == 0
    assert target["features"]["exact_surface_career_margin_shrunk"] is None


def test_replay_exposes_candidate_structural_signal_without_replacing_legacy():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Other A", winner_rank=40, loser_rank=100),
        _match("20260101", "Beta", "Other B", winner_rank=60, loser_rank=100),
        _match("20260105", "Alpha", "Beta", winner_rank=40, loser_rank=60),
    ]), universe="atp")
    target = rows[-1]
    assert target["features"]["current_rank_log_ratio"] > 0
    assert target["features"]["contextual_structural_signal_v1"] == 0.0
    assert 0.0 < target["features"]["contextual_structural_signal_v2"] < 0.25
    assert target["candidate_equation_audit"]["structural_strength"]["status"] == "READY"
    assert target["candidate_equation_audit"]["structural_strength_v2"]["status"] == "READY"
    assert target["candidate_equation_audit"]["structural_strength_v3"]["status"] == "READY"
    assert target["features"]["contextual_structural_rank_core_v3"] > 0
    assert target["candidate_equation_audit"]["structural_strength_v4"]["status"] == "READY"
    assert target["candidate_equation_audit"]["structural_strength_v5"]["status"] == "READY"
    assert target["candidate_equation_audit"]["structural_strength_v6"]["status"] == "READY"
    assert "contextual_structural_material_rank_core_v6" in target["features"]


def test_replay_surface_candidate_shrinks_small_sample_and_uses_conditions_once():
    rows = build_contextual_family_replay_rows(pd.DataFrame([
        _match("20260101", "Alpha", "Other A", indoor=True, pace="fast"),
        _match("20260102", "Other B", "Beta", indoor=True, pace="fast"),
        _match("20260105", "Alpha", "Beta", indoor=True, pace="fast"),
    ]), universe="atp")
    target = rows[-1]
    signal = target["features"]["contextual_surface_signal_v1"]
    assert signal is not None and 0.0 < signal < 0.2
    audit = target["candidate_equation_audit"]["surface_conditions"]
    assert audit["components"]["selected_specific_context"] == "pace_component"
    assert audit["governance"]["overlapping_components_are_not_summed"] is True


def test_recent_form_candidate_uses_tour_specific_decay_without_surface_vote():
    frame = pd.DataFrame([
        _match("20260101", "Alpha", "Strong", winner_rank=40, loser_rank=10),
        _match("20260102", "Weak", "Beta", winner_rank=150, loser_rank=50),
        _match("20260105", "Alpha", "Beta", winner_rank=35, loser_rank=55),
    ])
    atp = build_contextual_family_replay_rows(frame, universe="atp")[-1]
    wta = build_contextual_family_replay_rows(frame, universe="wta")[-1]

    for target in (atp, wta):
        audit = target["candidate_equation_audit"]["recent_form_v1"]
        assert audit["status"] == "READY"
        assert audit["same_surface_excluded_to_avoid_double_counting"] is True
        assert target["features"]["contextual_recent_result_core_v1"] > 0
        assert target["features"]["contextual_recent_bad_loss_penalty_v2"] > 0
        assert "probability" not in target
    assert atp["candidate_equation_audit"]["recent_form_v1"]["decay_days"] == {
        "result": 90, "competitiveness": 45,
        "win_quality": 60, "loss_context": 45,
    }
    assert wta["candidate_equation_audit"]["recent_form_v1"]["decay_days"] == {
        "result": 90, "competitiveness": 90,
        "win_quality": 60, "loss_context": 90,
    }


def test_strong_loss_relief_is_capped_at_zero_and_bad_loss_can_only_penalize():
    assert adjust_recent_result_for_loss_context(
        -0.4, bad_loss_penalty=0.0, strong_loss_relief=2.0, alpha=1.0,
    ) == 0.0
    assert adjust_recent_result_for_loss_context(
        0.3, bad_loss_penalty=0.0, strong_loss_relief=2.0, alpha=1.0,
    ) == 0.3
    assert math.isclose(adjust_recent_result_for_loss_context(
        0.3, bad_loss_penalty=0.5, strong_loss_relief=0.0, alpha=0.5,
    ), 0.05)
