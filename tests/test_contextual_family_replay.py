from src.contextual_family_replay import (
    build_contextual_target_row,
    build_contextual_family_replay_rows,
    evaluate_contextual_family_replay,
    replay_contextual_families,
)

import pandas as pd


def _match(day, winner, loser, *, surface="Hard", winner_rank=20, loser_rank=40,
           score="6-4 6-4", service=True, indoor=None, pace=None):
    row = {
        "tourney_date": day, "winner_name": winner, "loser_name": loser,
        "surface": surface, "winner_rank": winner_rank,
        "loser_rank": loser_rank, "score": score,
        "indoor": indoor, "court_pace_bucket": pace,
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
