from __future__ import annotations

import copy
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from datetime import datetime, timezone

import pandas as pd

from src import (
    competition_evidence,
    fetch_data,
    main,
    market_ledger,
    match_identity_v2,
    player_images,
    prelive_decision,
    pricing,
    report_html,
)


LAVER_ACTIVE = {
    "active": True,
    "change_id": competition_evidence.LAVER_ONLY_CHANGE_ID,
    "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
    "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-11T00:00:00+00:00",
    "tour": "atp",
}


RANKING_ACTIVE = {
    "active": True,
    "change_id": competition_evidence.RANKING_ELIGIBLE_CHANGE_ID,
    "version": competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
    "config_hash": competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-12T00:00:00+00:00",
    "tour": "atp",
}

RANKING_V2_ACTIVE = {
    "active": True,
    "change_id": competition_evidence.RANKING_ELIGIBLE_V2_CHANGE_ID,
    "version": competition_evidence.RANKING_ELIGIBLE_V2_POLICY_VERSION,
    "config_hash": competition_evidence.RANKING_ELIGIBLE_V2_CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-15T00:00:00+00:00",
    "tour": "atp",
}


def row(
    match_id: int,
    date: int,
    tournament: str,
    winner: str,
    loser: str,
    *,
    score: str = "4-6 6-4 6-2",
    round_name: str = "QF",
    loser_rank: int = 20,
    winner_rank: int = 10,
    loser_hand: str = "L",
    winner_hand: str = "R",
) -> dict:
    return {
        "id": match_id,
        "tourney_date": date,
        "tourney_name": tournament,
        "tourney_id": tournament.lower().replace(" ", "-"),
        "winner_name": winner,
        "loser_name": loser,
        "winner_rank": winner_rank,
        "loser_rank": loser_rank,
        "winner_hand": winner_hand,
        "loser_hand": loser_hand,
        "best_of": 3,
        "round": round_name,
        "surface": "Hard",
        "score": score,
    }


class LaverOnlyPolicyTests(unittest.TestCase):
    def test_activation_has_an_independent_version_and_hash_and_stays_off_by_default(self):
        inactive = competition_evidence.activation_from_environment({})
        self.assertFalse(inactive["active"])
        self.assertNotEqual(
            competition_evidence.LAVER_ONLY_CONFIG_HASH,
            competition_evidence.CONFIG_HASH,
        )
        active = competition_evidence.activation_from_environment({
            competition_evidence.ACTIVATION_VERSION_ENV:
                competition_evidence.LAVER_ONLY_POLICY_VERSION,
            competition_evidence.ACTIVATION_UTC_ENV: "2020-01-01T00:00:00Z",
        })
        self.assertTrue(active["active"])
        self.assertEqual(active["version"], competition_evidence.LAVER_ONLY_POLICY_VERSION)
        self.assertEqual(active["config_hash"], competition_evidence.LAVER_ONLY_CONFIG_HASH)
        self.assertTrue(competition_evidence.policy_is_supported(active))

    def test_oracle_excludes_laver_and_preserves_current_davis_treatment(self):
        rows = [
            {**row(1, 20260101, "Vienna Open", "Alpha", "Beta"), "won": True},
            {**row(2, 20260102, "Basel Open", "Gamma", "Alpha"), "won": False},
            {**row(3, 20260103, "Davis Cup", "Alpha", "Delta"), "won": True},
            {**row(4, 20260104, "Laver Cup", "Alpha", "Epsilon", score="6-7(4) 6-4 6-2"), "won": True},
        ]
        actual = competition_evidence.weighted_binary_record(
            rows, lambda item: item["won"], active=True, policy=LAVER_ACTIVE
        )
        self.assertEqual(actual["matches"], 4)
        self.assertEqual(actual["weighted_wins"], 2)
        self.assertEqual(actual["weighted_losses"], 1)
        self.assertEqual(actual["weighted_matches"], 3)
        self.assertEqual(actual["weighted_win_rate_pct"], 66.7)
        evidence = actual["competition_evidence"]
        self.assertEqual(evidence["laver_excluded"], 1)
        self.assertEqual(evidence["davis_preserved"], 1)
        self.assertEqual(evidence["version"], competition_evidence.LAVER_ONLY_POLICY_VERSION)

    def test_same_last_ten_sample_becomes_nine_without_n_plus_one(self):
        rows = [
            row(index, 20260100 + index, "Vienna Open", "Alpha", f"P{index}")
            for index in range(1, 12)
        ]
        rows[-5]["tourney_name"] = "Laver Cup"
        history = pd.DataFrame(rows)
        result = fetch_data.compute_recent_form(
            history,
            "Alpha",
            10,
            competition_policy=LAVER_ACTIVE,
        )
        self.assertEqual(result["matches"], 10)
        self.assertEqual(result["weighted_matches"], 9)
        self.assertEqual(result["competition_evidence"]["laver_excluded"], 1)

    def test_unknown_competition_fails_closed_but_wta_remains_out_of_scope(self):
        unknown = competition_evidence.weighted_binary_record(
            [{"id": 1, "won": True}],
            lambda item: item["won"],
            active=True,
            policy=LAVER_ACTIVE,
        )
        self.assertFalse(unknown["competition_evidence"]["eligible_for_performance"])
        wta = competition_evidence.activation_for_tour(LAVER_ACTIVE, "wta")
        self.assertFalse(wta["active"])
        self.assertEqual(wta["status"], "OUT_OF_SCOPE_TOUR")


class LaverOnlyReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame([
            row(1, 20260101, "Vienna Open", "Alpha", "Beta"),
            row(
                2, 20260102, "Vienna Open", "Gamma", "Alpha",
                score="7-6(3) 4-6 6-3", winner_hand="L", loser_hand="R",
                winner_rank=18, loser_rank=11,
            ),
            row(3, 20260103, "Davis Cup", "Alpha", "Delta"),
            row(4, 20260104, "Laver Cup", "Alpha", "Epsilon", score="6-7(4) 6-4 6-2"),
            row(5, 20250104, "Vienna Open", "Alpha", "Zeta"),
        ])

    def test_seven_previously_blocked_families_are_reconstructed(self):
        tiebreak = fetch_data.compute_tiebreak_stats(
            self.history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        deciding = fetch_data.compute_deciding_set_stats(
            self.history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        comeback = fetch_data.compute_set1_comeback_stats(
            self.history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        rounds = fetch_data.compute_round_stage_stats(
            self.history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        hands = fetch_data.compute_handedness_matchup_stats(
            self.history, "Alpha", tour="atp", competition_policy=LAVER_ACTIVE
        )
        opponent = fetch_data.compute_opponent_level_stats(
            self.history, "Alpha", 20, competition_policy=LAVER_ACTIVE
        )
        tournament = fetch_data.compute_tournament_record_from_history(
            self.history,
            "Alpha",
            "not-used",
            "Vienna Open",
            competition_policy=LAVER_ACTIVE,
        )
        sources = [
            tiebreak,
            deciding["bo3"],
            comeback["bo3"],
            rounds["late_rounds"],
            hands["vs_left_handed"],
            opponent,
            tournament,
        ]
        for source in sources:
            self.assertTrue(
                competition_evidence.evidence_is_compatible(source, LAVER_ACTIVE),
                source,
            )
        self.assertEqual(tiebreak["competition_evidence"]["laver_excluded"], 1)
        self.assertEqual(deciding["bo3"]["competition_evidence"]["laver_excluded"], 1)
        self.assertEqual(comeback["bo3"]["competition_evidence"]["laver_excluded"], 1)
        self.assertGreaterEqual(tournament["edicoes"], 2)

    def test_filtered_local_sources_win_over_unseparable_provider_aggregates(self):
        tiebreak_a = fetch_data.compute_tiebreak_stats(
            self.history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        tiebreak_b = copy.deepcopy(tiebreak_a)
        tiebreak_b["weighted_wins"] = 0.0
        tiebreak_b["weighted_losses"] = tiebreak_b["weighted_matches"]
        tiebreak_b["weighted_win_rate_pct"] = 0.0
        round_a = fetch_data.compute_round_stage_stats(
            self.history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        round_b = copy.deepcopy(round_a)
        opponent_a = fetch_data.compute_opponent_level_stats(
            self.history, "Alpha", 20, competition_policy=LAVER_ACTIVE
        )
        opponent_b = copy.deepcopy(opponent_a)
        payload = {
            "player_a": "Alpha",
            "player_b": "Beta",
            "tour": "atp",
            "match_format": "bo3",
            "competition_evidence_policy": competition_evidence.policy_metadata(
                LAVER_ACTIVE
            ),
            "tiebreak_a": tiebreak_a,
            "tiebreak_b": tiebreak_b,
            "round_stage_stats_a": round_a,
            "round_stage_stats_b": round_b,
            "opponent_level_stats_a": opponent_a,
            "opponent_level_stats_b": opponent_b,
            "ranking_a": {"rank": 10},
            "ranking_b": {"rank": 20},
            "rich_stats_a": {
                "by_round": {"QF": {"wins": 99, "losses": 0}},
                "vs_rank_level": {"top20": {"win_pct": 99, "matches": 99}},
                "scenarios": {"first_set_lose_then_win_pct": 99, "first_set_lose_count": 99},
            },
            "rich_stats_b": {
                "by_round": {"QF": {"wins": 0, "losses": 99}},
                "vs_rank_level": {"top10": {"win_pct": 1, "matches": 99}},
                "scenarios": {"first_set_lose_then_win_pct": 1, "first_set_lose_count": 99},
            },
        }
        features = main._compute_features(payload)
        self.assertEqual(
            features["pressao_ronda"]["valor_a"],
            competition_evidence.record_rate(round_a["late_rounds"])[0],
        )
        self.assertEqual(
            features["nivel_adversario"]["valor_a"],
            competition_evidence.record_rate(opponent_a)[0],
        )
        blockers = {
            item["feature"]
            for item in payload["competition_evidence_policy"]["feature_blockers"]
        }
        self.assertNotIn("tiebreak", blockers)
        self.assertNotIn("pressao_ronda", blockers)
        self.assertNotIn("nivel_adversario", blockers)

    def test_action_map_does_not_reenter_rich_scenarios(self):
        evidence = {
            "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
            "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
            "eligible_for_performance": True,
        }
        local = {
            "matches_lost_set1": 5,
            "weighted_matches_lost_set1": 5,
            "comeback_rate_pct": 40,
            "competition_evidence": evidence,
        }
        feature = {
            "lider": "Alpha",
            "competition_evidence": evidence,
        }
        payload = {
            "player_a": "Alpha",
            "player_b": "Beta",
            "match_format": "bo3",
            "competition_evidence_policy": LAVER_ACTIVE,
            "features": {"comeback_set1": feature},
            "set1_comeback_stats_a": {"bo3": local},
            "set1_comeback_stats_b": {"bo3": local},
            "rich_stats_a": {"scenarios": {"first_set_lose_then_win_pct": 99, "first_set_lose_count": 99}},
            "rich_stats_b": {"scenarios": {"first_set_lose_then_win_pct": 98, "first_set_lose_count": 99}},
            "prelive_decision": {"state": "NO_EDGE"},
            "pricing": {},
        }
        html = report_html._mod_action_map(
            payload,
            {"classificacao": {"nivel": 1}, "favorecido": "Alpha"},
            {},
        )
        self.assertNotIn("99%", html)
        self.assertNotIn("98%", html)

    def test_fatigue_is_not_filtered_or_weighted(self):
        start = datetime(2026, 1, 10, tzinfo=timezone.utc)
        before = fetch_data.compute_fatigue(self.history, "Alpha", start)
        after = fetch_data.compute_fatigue(self.history, "Alpha", start)
        self.assertEqual(before, after)
        self.assertNotIn("competition_evidence", after or {})


class LaverOnlyBrainReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for index in range(1, 13):
            winner = "Alpha" if index <= 10 else f"Opponent A{index}"
            loser = f"Opponent A{index}" if index <= 10 else "Alpha"
            rows.append(row(
                index,
                20260000 + 100 + index,
                "Vienna Open",
                winner,
                loser,
                score="4-6 6-3 6-2" if index == 1 else "6-3 6-4",
                round_name="QF" if index % 2 else "R32",
                loser_rank=40 + index,
                winner_rank=8,
            ))
        for index in range(13, 25):
            winner = f"Opponent B{index}" if index <= 22 else "Beta"
            loser = "Beta" if index <= 22 else f"Opponent B{index}"
            rows.append(row(
                index,
                20260000 + 100 + index,
                "Vienna Open",
                winner,
                loser,
                score="6-3 4-6 4-6" if index == 23 else "6-3 6-4",
                round_name="QF" if index % 2 else "R32",
                loser_rank=80,
                winner_rank=12 + index,
            ))
        rows.append(row(
            90, 20260920, "Laver Cup", "Alpha", "Laver Opponent",
            score="4-6 6-3 6-2",
        ))
        self.history = pd.DataFrame(rows).drop(
            columns=["winner_hand", "loser_hand"]
        )
        service = {
            "w_ace": 8, "w_df": 2, "w_svpt": 60, "w_1stIn": 38,
            "w_1stWon": 28, "w_2ndWon": 12, "w_bpSaved": 4,
            "w_bpFaced": 6, "l_ace": 4, "l_df": 4, "l_svpt": 58,
            "l_1stIn": 34, "l_1stWon": 18, "l_2ndWon": 8,
            "l_bpSaved": 2, "l_bpFaced": 7,
        }
        for key, value in service.items():
            self.history[key] = value

    @staticmethod
    def _match(tour="atp"):
        return {
            "id": 700,
            "_tour": tour,
            "player1Id": 1,
            "player2Id": 2,
            "player1": {"id": 1, "name": "Alpha", "countryAcr": "POR"},
            "player2": {"id": 2, "name": "Beta", "countryAcr": "ESP"},
            "tournamentId": 55,
            "tournament_name": "Vienna Open",
            "surface": "Hard",
            "tier": "ATP 500" if tour == "atp" else "WTA 500",
            "date": "2026-10-20T12:00:00Z",
            "roundId": 4,
        }

    @staticmethod
    def _blocked_recent(player_id: int) -> list[dict]:
        other = 91 if player_id == 1 else 92
        return [{
            "id": 800 + player_id,
            "player1Id": player_id,
            "player2Id": other,
            "match_winner": player_id,
            "bestOf": 3,
            "result": "4-6 6-3 6-2",
            "date": "2026-10-01T12:00:00Z",
            "tournamentId": 999999,
        }]

    def _build_payload(
        self,
        activation: dict,
        *,
        tour: str = "atp",
        blocked_provider_comeback: bool = False,
    ) -> tuple[dict, object]:
        recent = {
            1: self._blocked_recent(1) if blocked_provider_comeback else [],
            2: self._blocked_recent(2) if blocked_provider_comeback else [],
        }
        legacy_record = {
            "provider": "rapidapi_tournament_record",
            "wins": 7,
            "losses": 3,
            "matches": 10,
            "win_pct_ponderado": 70.0,
        }

        def ranking(_official, _name, player_id):
            return (
                {
                    "rank": 8 if player_id == 1 else 80,
                    "points": 4000 if player_id == 1 else 700,
                },
                "mocked_official",
            )

        def cached_hand(_tour, opponent):
            return "L" if "A" in str(opponent) else "R"

        with ExitStack() as stack:
            stack.enter_context(patch.object(
                main.competition_evidence,
                "activation_from_environment",
                return_value=copy.deepcopy(activation),
            ))
            stack.enter_context(patch.object(
                fetch_data, "get_history", return_value=self.history.copy()
            ))
            stack.enter_context(patch.object(
                fetch_data, "history_scope_summary", return_value={"mode": "mocked"}
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "get_historical_odds_history",
                return_value=pd.DataFrame(),
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_rapidapi_upcoming_operational_moneyline_with_provenance",
                return_value=(None, {}),
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_the_odds_moneyline_with_provenance",
                return_value=(
                    {"Alpha": 4.0, "Beta": 1.25},
                    {
                        "source": "mocked_bookmaker",
                        "captured_at_utc": "2026-10-11T11:00:00+00:00",
                        "event_id": "mock-event",
                        "capture_kind": "PRELIVE",
                    },
                ),
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_rapidapi_recent_moneyline_with_provenance",
                return_value=(None, {}),
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_rapidapi_embedded_moneyline_with_provenance",
                return_value=(None, {}),
            ))
            stack.enter_context(patch.object(
                fetch_data, "record_market_odds_observation", return_value=None
            ))
            stack.enter_context(patch.object(
                main.market_integrity,
                "is_operational_pricing_provenance",
                return_value=True,
            ))
            stack.enter_context(patch.object(
                pricing.market_integrity,
                "is_operational_pricing_payload",
                return_value=True,
            ))
            stack.enter_context(patch.object(
                market_ledger,
                "record_market_batch_best_effort",
                return_value={
                    "status": "RECORDED",
                    "errors": [],
                    "observation_ids": [],
                    "entry_memory_eligible": True,
                },
            ))
            stack.enter_context(patch.object(
                market_ledger, "event_key", return_value="mock:event"
            ))
            stack.enter_context(patch.object(
                match_identity_v2,
                "resolve_observation",
                return_value={
                    "identity_schema_version": match_identity_v2.SCHEMA_VERSION,
                    "identity_status": match_identity_v2.CANONICAL_STRONG,
                    "identity_persisted": True,
                    "canonical_match_instance_id": "cmiv2:laver-review",
                },
            ))
            stack.enter_context(patch.object(
                match_identity_v2,
                "event_id_is_strong_identity_evidence",
                return_value=True,
            ))
            stack.enter_context(patch.object(
                main.calibration_store, "read_snapshots_by_key", return_value={}
            ))
            stack.enter_context(patch.object(
                main.calibration_store,
                "estimate_indicative_odds",
                return_value=None,
            ))
            stack.enter_context(patch.object(
                player_images, "load_registry", return_value={}
            ))
            stack.enter_context(patch.object(
                player_images, "find_player_image", return_value="mocked.png"
            ))
            stack.enter_context(patch.object(
                fetch_data, "fetch_h2h_matches", return_value=[]
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_h2h_stats_with_coverage",
                return_value=(
                    None,
                    {
                        "status": "UNAVAILABLE",
                        "source": "mocked",
                        "endpoint_family": f"{tour}/h2h/stats",
                        "reason": "mocked_unavailable",
                    },
                ),
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_player_recent_matches",
                side_effect=lambda _tour, player_id, **_kwargs: copy.deepcopy(
                    recent[player_id]
                ),
            ))
            if blocked_provider_comeback:
                stack.enter_context(patch.object(
                    fetch_data,
                    "compute_form_from_recent",
                    return_value={"form": None, "season": None, "surface": None},
                ))
            stack.enter_context(patch.object(
                fetch_data, "fetch_recent_stats", return_value=None
            ))
            stack.enter_context(patch.object(
                fetch_data, "fetch_official_ranking", return_value=[]
            ))
            stack.enter_context(patch.object(
                fetch_data, "resolve_official_ranking", side_effect=ranking
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "fetch_player_hand",
                side_effect=lambda _tour, player_id, _name: (
                    "R" if player_id == 1 else "L"
                ),
            ))
            stack.enter_context(patch.object(
                fetch_data, "_get_cached_hand_by_name", side_effect=cached_hand
            ))
            stack.enter_context(patch.object(
                fetch_data, "rapidapi_budget_exceeded", return_value=False
            ))
            provider = stack.enter_context(patch.object(
                fetch_data,
                "fetch_tournament_record",
                return_value=copy.deepcopy(legacy_record),
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "court_pace_context",
                return_value={
                    "status": "available",
                    "bucket": "medium",
                    "cpi": 35,
                    "year_used": 2026,
                },
            ))
            stack.enter_context(patch.object(
                fetch_data,
                "lookup_court_pace",
                return_value={"bucket": "medium", "cpi": 35},
            ))
            stack.enter_context(patch.object(
                main, "_get_rich_player_data", return_value=None
            ))
            stack.enter_context(patch.object(
                main, "_get_weather_for_match", return_value=None
            ))
            payload = main._build_match_payload(self._match(tour))
        return payload, provider

    def test_r1_future_t0_and_wta_keep_legacy_tournament_provider(self):
        future = {
            **LAVER_ACTIVE,
            "active": False,
            "status": "ACTIVATION_EFFECTIVE_FROM_UTC_INVALID_OR_FUTURE",
            "tour": None,
        }
        future_payload, future_provider = self._build_payload(future)
        self.assertFalse(future_payload["competition_evidence_policy"]["active"])
        self.assertEqual(
            future_payload["tournament_record_a"]["provider"],
            "rapidapi_tournament_record",
        )
        self.assertEqual(future_provider.call_count, 2)

        wta_payload, wta_provider = self._build_payload(LAVER_ACTIVE, tour="wta")
        self.assertFalse(wta_payload["competition_evidence_policy"]["active"])
        self.assertEqual(
            wta_payload["competition_evidence_policy"]["status"],
            "OUT_OF_SCOPE_TOUR",
        )
        self.assertEqual(
            wta_payload["tournament_record_b"]["provider"],
            "rapidapi_tournament_record",
        )
        self.assertEqual(wta_provider.call_count, 2)

    def test_r2_cpi_uses_laver_only_provenance_through_motor_and_assessment(self):
        strong = competition_evidence.weighted_binary_record(
            [
                {"tournament_name": "Vienna Open", "won": index < 8}
                for index in range(10)
            ],
            lambda item: item["won"],
            active=True,
            policy=LAVER_ACTIVE,
        )
        weak = competition_evidence.weighted_binary_record(
            [
                {"tournament_name": "Vienna Open", "won": index < 3}
                for index in range(10)
            ],
            lambda item: item["won"],
            active=True,
            policy=LAVER_ACTIVE,
        )
        payload = {
            "player_a": "Alpha",
            "player_b": "Beta",
            "tour": "atp",
            "surface": "Hard",
            "competition_evidence_policy": competition_evidence.policy_metadata(
                LAVER_ACTIVE
            ),
            "court_speed_hoje": {"status": "available"},
            "court_speed_a": {**strong, "eligible_for_index": True},
            "court_speed_b": {**weak, "eligible_for_index": True},
        }
        payload["features"] = main._compute_features(payload)
        feature = payload["features"]["velocidade_piso"]
        self.assertTrue(
            feature["competition_evidence"]["eligible_for_performance"]
        )
        divergence = report_html.calcular_divergencia_publico(payload)
        assessment = prelive_decision.assess_report(payload, divergence)
        self.assertTrue(
            divergence["fatores_status"]["velocidade_piso"]["disponivel"]
        )
        self.assertIn(
            "velocidade_piso",
            {
                item["feature"]
                for item in payload["competition_evidence_policy"][
                    "factor_impact_matrix"
                ]
                if item["impact"] != "DECISION_FACTOR_BLOCKED"
            },
        )
        self.assertIn("coverage", assessment)

    def test_r3_profile_hands_reach_matchup_factor(self):
        with patch.object(
            fetch_data, "rapidapi_budget_exceeded", return_value=False
        ), patch.object(
            fetch_data,
            "_get_cached_hand_by_name",
            side_effect=lambda _tour, name: "L" if "A" in name else "R",
        ):
            stats_a = fetch_data.compute_handedness_matchup_stats(
                self.history,
                "Alpha",
                tour="atp",
                competition_policy=LAVER_ACTIVE,
            )
            stats_b = fetch_data.compute_handedness_matchup_stats(
                self.history,
                "Beta",
                tour="atp",
                competition_policy=LAVER_ACTIVE,
            )
        resolved_a = fetch_data.resolve_handedness_matchup(stats_a, "L")
        resolved_b = fetch_data.resolve_handedness_matchup(stats_b, "R")
        self.assertIsNotNone(resolved_a)
        self.assertIsNotNone(resolved_b)
        self.assertGreater(resolved_a["matches"], 0)
        self.assertIn("weighted_win_rate_pct", stats_a["vs_left_handed"])
        self.assertGreater(stats_a["profile_resolution"]["resolved_profiles"], 0)

        payload = {
            "player_a": "Alpha",
            "player_b": "Beta",
            "tour": "atp",
            "competition_evidence_policy": competition_evidence.policy_metadata(
                LAVER_ACTIVE
            ),
            "handedness_matchup_a": resolved_a,
            "handedness_matchup_b": resolved_b,
        }
        payload["features"] = main._compute_features(payload)
        divergence = report_html.calcular_divergencia_publico(payload)
        self.assertIn("matchup_maos", payload["features"])
        self.assertTrue(
            divergence["fatores_status"]["matchup_maos"]["disponivel"]
        )

    def test_r4_h2h_recency_matches_manual_laver_removal_and_keeps_davis(self):
        history = pd.DataFrame([
            row(1, 20180101, "Vienna Open", "Alpha", "Beta"),
            row(2, 20190101, "Vienna Open", "Alpha", "Beta"),
            row(3, 20200101, "Vienna Open", "Alpha", "Beta"),
            row(4, 20250101, "Davis Cup", "Beta", "Alpha"),
            row(5, 20260101, "Vienna Open", "Beta", "Alpha"),
            row(6, 20261001, "Laver Cup", "Alpha", "Beta"),
        ])
        actual = fetch_data.compute_h2h(
            history, "Alpha", "Beta", "Hard",
            competition_policy=LAVER_ACTIVE,
        )
        manual = fetch_data.compute_h2h(
            history[history["tourney_name"] != "Laver Cup"],
            "Alpha",
            "Beta",
            "Hard",
        )
        self.assertEqual(
            actual["weighted_recency"], manual["weighted_recency"]
        )
        self.assertNotEqual(
            actual["raw_weighted_recency"], actual["weighted_recency"]
        )
        self.assertEqual(actual["overall"]["weighted_a_wins"], 3)
        self.assertEqual(actual["overall"]["weighted_b_wins"], 2)
        self.assertEqual(
            actual["overall"]["competition_evidence"]["davis_preserved"], 1
        )
        self.assertEqual(actual["weighted_recency"]["lider"], "Beta")

    def test_r5_blocked_provider_does_not_replace_eligible_local_comeback(self):
        eligible = {
            "bo3": {
                "matches_lost_set1": 5,
                "weighted_matches_lost_set1": 4,
                "comeback_rate_pct": 50,
                "competition_evidence": {
                    "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
                    "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
                    "eligible_for_performance": True,
                },
            }
        }
        blocked = copy.deepcopy(eligible)
        blocked["bo3"]["competition_evidence"]["eligible_for_performance"] = False
        blocked["bo3"]["competition_evidence"]["status"] = "BLOCKED"
        selected, diagnostics = main._select_set1_comeback_source(
            eligible,
            blocked,
            expected_best_of=3,
            policy=LAVER_ACTIVE,
        )
        self.assertIs(selected, eligible)
        self.assertEqual(diagnostics["selected_source"], "local_history")
        self.assertEqual(
            diagnostics["rejected_sources"][0]["reason_code"],
            "COMPETITION_EVIDENCE_BLOCKED",
        )
        none_selected, none_diagnostics = main._select_set1_comeback_source(
            None,
            blocked,
            expected_best_of=3,
            policy=LAVER_ACTIVE,
        )
        self.assertIsNone(none_selected)
        self.assertEqual(
            none_diagnostics["reason_code"],
            "NO_USABLE_SET1_COMEBACK_SOURCE",
        )

        payload, _provider = self._build_payload(
            LAVER_ACTIVE, blocked_provider_comeback=True
        )
        self.assertEqual(
            payload["set1_comeback_source_diagnostics"]["a"][
                "selected_source"
            ],
            "local_history",
        )
        self.assertEqual(
            payload["set1_comeback_source_diagnostics"]["a"][
                "rejected_sources"
            ][0]["reason_code"],
            "COMPETITION_EVIDENCE_BLOCKED",
        )

    def test_r6_rank_validation_and_exclusion_telemetry(self):
        invalid = [0, -1, True, float("nan"), pd.NA, float("inf"), -float("inf")]
        for value in invalid:
            with self.subTest(value=value):
                parsed, reason = fetch_data._parse_positive_finite_rank(value)
                self.assertIsNone(parsed)
                self.assertIsNotNone(reason)
                self.assertIsNone(
                    fetch_data.compute_opponent_level_stats(
                        self.history,
                        "Alpha",
                        value,
                        competition_policy=LAVER_ACTIVE,
                    )
                )

        for value, bucket in (
            (10, "top10"), (20, "top20"), (50, "top50"), (100, "top100"),
            (200, "top200"), (300, "top300"),
        ):
            with self.subTest(value=value):
                result = fetch_data.compute_opponent_level_stats(
                    self.history,
                    "Alpha",
                    value,
                    competition_policy=LAVER_ACTIVE,
                )
                self.assertEqual(result["rank_bucket"], bucket)

        outside_history = pd.DataFrame([
            {
                "winner_name": "Alpha", "loser_name": "Low A",
                "winner_rank": 120, "loser_rank": 350,
                "tournament_name": "ATP Challenger Main Draw",
                "_history_competition_scope": "challenger",
            },
            {
                "winner_name": "Low B", "loser_name": "Alpha",
                "winner_rank": 410, "loser_rank": 120,
                "tournament_name": "ATP Challenger Main Draw",
                "_history_competition_scope": "challenger",
            },
            {
                "winner_name": "Alpha", "loser_name": "Top Player",
                "winner_rank": 120, "loser_rank": 80,
                "tournament_name": "ATP Challenger Main Draw",
                "_history_competition_scope": "challenger",
            },
        ])
        outside = fetch_data.compute_opponent_level_stats(
            outside_history, "Alpha", 450, competition_policy=LAVER_ACTIVE,
        )
        self.assertEqual(outside["rank_bucket"], "outside_top300")
        self.assertEqual(outside["ranking_sample_quality"]["eligible_rows"], 2)

        dirty = self.history.copy()
        dirty["loser_rank"] = dirty["loser_rank"].astype("object")
        dirty.loc[dirty.index[:7], "loser_rank"] = [
            0, -1, True, float("nan"), pd.NA, float("inf"), -float("inf")
        ]
        result = fetch_data.compute_opponent_level_stats(
            dirty,
            "Alpha",
            100,
            competition_policy=LAVER_ACTIVE,
        )
        quality = result["ranking_sample_quality"]
        self.assertEqual(quality["raw_rows"], 13)
        self.assertGreaterEqual(quality["excluded_rows"], 7)
        self.assertIn("BOOLEAN_RANK", quality["exclusion_reason_counts"])
        self.assertIn("NON_FINITE_RANK", quality["exclusion_reason_counts"])

    def test_off_and_laver_only_matrix_on_identical_mocked_inputs(self):
        off = {**LAVER_ACTIVE, "active": False, "status": "OFF"}
        off_payload, _ = self._build_payload(off)
        active_payload, _ = self._build_payload(
            LAVER_ACTIVE, blocked_provider_comeback=True
        )

        def measured(payload):
            divergence = payload["divergencia"]
            assessment = payload["report_assessment"]
            decision = payload["prelive_decision"]
            html = report_html.build_report_html(payload, {"flag": "🟢"})
            return {
                "policy_active": payload["competition_evidence_policy"]["active"],
                "coverage": assessment["coverage"]["weighted_ratio"],
                "report_null": assessment["report_null"],
                "cpi_available": divergence["fatores_status"][
                    "velocidade_piso"
                ]["disponivel"],
                "h2h_available": divergence["fatores_status"]["h2h"][
                    "disponivel"
                ],
                "hands_available": divergence["fatores_status"][
                    "matchup_maos"
                ]["disponivel"],
                "comeback_source": payload[
                    "set1_comeback_source_diagnostics"
                ]["a"]["selected_source"],
                "pricing_available": payload["pricing"].get("available") is True,
                "candidate": payload["pricing"].get("candidate") is True,
                "decision_state": decision.get("state"),
                "paper_eligible": decision.get("paper_eligible") is True,
                "html_map": "Mapa de Forças" in html,
            }

        matrix = {
            "OFF": measured(off_payload),
            "LAVER_ONLY": measured(active_payload),
        }
        print("[laver-only-matrix] " + json.dumps(matrix, sort_keys=True))
        for mode in ("OFF", "LAVER_ONLY"):
            self.assertTrue(matrix[mode]["cpi_available"])
            self.assertFalse(matrix[mode]["h2h_available"])
            self.assertTrue(matrix[mode]["hands_available"])
            self.assertTrue(matrix[mode]["pricing_available"])
            self.assertTrue(matrix[mode]["candidate"])
            self.assertTrue(matrix[mode]["html_map"])
        self.assertEqual(
            matrix["LAVER_ONLY"]["comeback_source"], "local_history"
        )
        self.assertFalse(matrix["LAVER_ONLY"]["report_null"])


    def test_change102_real_runtime_path_uses_local_sources_and_new_copy(self):
        additions = pd.DataFrame([
            row(101, 20261013, "Davis Cup", "Alpha", "Davis Opponent"),
            row(
                102, 20261014, "Next Gen ATP Finals",
                "Alpha", "Next Gen Opponent",
            ),
            row(
                103, 20261015, "Olympic Games",
                "Olympic Opponent", "Alpha",
            ),
            row(
                104, 20261016, "Vienna Open",
                "Beta", "Recent Beta Opponent",
            ),
            row(
                105, 20261017, "Laver Cup",
                "Alpha", "Post T0 Laver Opponent",
            ),
        ]).drop(columns=["winner_hand", "loser_hand"])
        for column in self.history.columns:
            if column not in additions.columns:
                additions[column] = self.history[column].iloc[0]
        self.history = pd.concat(
            [self.history, additions[self.history.columns]],
            ignore_index=True,
        )
        payload, provider = self._build_payload(
            RANKING_ACTIVE, blocked_provider_comeback=True
        )

        policy = payload["competition_evidence_policy"]
        self.assertEqual(
            policy["version"],
            competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
        )
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(
            payload["data_coverage"]["tournament_record"]["a"]["source"],
            "local_history",
        )
        self.assertEqual(
            payload["set1_comeback_source_diagnostics"]["a"][
                "selected_source"
            ],
            "local_history",
        )
        self.assertFalse(policy["feature_blockers"])
        self.assertTrue(policy["integral_laver_exclusion_claimed"])
        self.assertTrue(policy["integral_non_ranking_exclusion_claimed"])
        classifications = payload["recent_form_a"]["competition_evidence"][
            "classification_counts"
        ]
        self.assertGreaterEqual(classifications["DAVIS_EXCEPTION"], 1)
        self.assertGreaterEqual(classifications["NEXT_GEN_EXCEPTION"], 1)
        self.assertGreaterEqual(classifications["OLYMPICS_EXCEPTION"], 1)
        self.assertGreaterEqual(classifications["NON_RANKING"], 1)
        evidence = payload["recent_form_a"]["competition_evidence"]
        self.assertGreaterEqual(evidence["grandfathered_pre_t0"], 1)
        self.assertGreaterEqual(evidence["prospective_post_t0"], 1)

        divergence = payload["divergencia"]
        assessment = payload["report_assessment"]
        decision = payload["prelive_decision"]
        html = report_html.build_report_html(payload, {"flag": "🟢"})
        self.assertTrue(
            divergence["fatores_status"]["velocidade_piso"]["disponivel"]
        )
        self.assertFalse(
            divergence["fatores_status"]["h2h"]["disponivel"]
        )
        self.assertTrue(
            divergence["fatores_status"]["matchup_maos"]["disponivel"]
        )
        self.assertFalse(assessment["report_null"])
        self.assertTrue(payload["pricing"].get("available"))
        self.assertIn("state", decision)
        self.assertIn("ranking-eligible", html)
        self.assertNotIn("Davis competitiva 50%", html)

    def test_change105_integrated_runtime_downweights_only_performance(self):
        additions = pd.DataFrame([
            row(111, 20261016, "Davis Cup", "Alpha", "Davis Opponent"),
            row(
                112, 20261017, "Next Gen ATP Finals",
                "Alpha", "Next Gen Opponent",
            ),
            row(
                113, 20261018, "Olympic Games",
                "Olympic Opponent", "Alpha",
            ),
            row(
                114, 20261019, "Laver Cup",
                "Alpha", "Laver Opponent 2",
            ),
        ]).drop(columns=["winner_hand", "loser_hand"])
        for column in self.history.columns:
            if column not in additions.columns:
                additions[column] = self.history[column].iloc[0]
        self.history = pd.concat(
            [self.history, additions[self.history.columns]],
            ignore_index=True,
        )

        v1_payload, _ = self._build_payload(
            RANKING_ACTIVE, blocked_provider_comeback=True
        )
        v2_payload, provider = self._build_payload(
            RANKING_V2_ACTIVE, blocked_provider_comeback=True
        )

        policy = v2_payload["competition_evidence_policy"]
        self.assertEqual(
            policy["version"],
            competition_evidence.RANKING_ELIGIBLE_V2_POLICY_VERSION,
        )
        self.assertEqual(policy["weights"]["davis_exception"], 0.5)
        self.assertEqual(policy["weights"]["next_gen_exception"], 0.5)
        self.assertEqual(policy["weights"]["olympics_exception"], 0.5)
        self.assertEqual(provider.call_count, 0)

        v1_form = v1_payload["recent_form_a"]
        v2_form = v2_payload["recent_form_a"]
        self.assertEqual(v2_form["matches"], v1_form["matches"])
        counts = v2_form["competition_evidence"]["classification_counts"]
        special_count = sum(
            counts.get(name, 0)
            for name in (
                "DAVIS_EXCEPTION",
                "NEXT_GEN_EXCEPTION",
                "OLYMPICS_EXCEPTION",
            )
        )
        self.assertGreaterEqual(special_count, 3)
        self.assertAlmostEqual(
            v1_form["weighted_matches"] - v2_form["weighted_matches"],
            special_count * 0.5,
        )
        self.assertGreaterEqual(
            v2_form["competition_evidence"]["prospective_post_t1"], 4
        )

        divergence = v2_payload["divergencia"]
        assessment = v2_payload["report_assessment"]
        pricing_result = v2_payload["pricing"]
        decision = v2_payload["prelive_decision"]
        html = report_html.build_report_html(v2_payload, {"flag": "🟢"})
        self.assertIn("fatores_status", divergence)
        self.assertIn("coverage", assessment)
        self.assertIn("available", pricing_result)
        self.assertIn("state", decision)
        self.assertNotIn("Política de evidência por competição", html)
        self.assertNotIn("Davis, Next Gen e Olympics a 50%", html)
        self.assertIn(
            competition_evidence.RANKING_ELIGIBLE_V2_CONFIG_HASH, html
        )


    def test_change102_pre_t0_unknown_is_grandfathered_in_runtime(self):
        target = self.history.index[0]
        self.history.loc[target, "tourney_name"] = "Unknown Invitational"
        payload, provider = self._build_payload(
            RANKING_ACTIVE,
            blocked_provider_comeback=True,
        )

        self.assertEqual(provider.call_count, 0)
        policy = payload["competition_evidence_policy"]
        self.assertFalse(policy["feature_blockers"])
        evidence = payload["recent_form_a"]["competition_evidence"]
        self.assertGreaterEqual(evidence["grandfathered_pre_t0"], 1)
        self.assertEqual(evidence["prospective_post_t0"], 0)
        self.assertTrue(payload["pricing"].get("available"))
        self.assertIn("state", payload["prelive_decision"])

    def test_change102_unknown_conflict_fails_closed_without_provider_reentry(self):
        self.history["tier"] = None
        target = self.history.index[0]
        self.history.loc[target, "tourney_name"] = "Laver Cup"
        self.history.loc[target, "tourney_date"] = 20261018
        self.history.loc[target, "tier"] = "ATP 500"
        payload, provider = self._build_payload(
            RANKING_ACTIVE, blocked_provider_comeback=True
        )

        policy = payload["competition_evidence_policy"]
        self.assertEqual(provider.call_count, 0)
        self.assertTrue(policy["feature_blockers"])
        self.assertFalse(policy["integral_laver_exclusion_claimed"])
        self.assertFalse(policy["integral_non_ranking_exclusion_claimed"])
        self.assertEqual(payload["report_data_status"], "DEGRADED")
        self.assertTrue(payload["report_assessment"]["report_null"])
        self.assertFalse(
            payload["prelive_decision"].get("paper_eligible") is True
        )

    def test_change102_wta_and_laver_only_controls_remain_unchanged(self):
        wta_payload, wta_provider = self._build_payload(
            RANKING_ACTIVE, tour="wta"
        )
        self.assertFalse(wta_payload["competition_evidence_policy"]["active"])
        self.assertEqual(wta_provider.call_count, 2)
        laver_payload, laver_provider = self._build_payload(
            LAVER_ACTIVE, blocked_provider_comeback=True
        )
        self.assertEqual(
            laver_payload["competition_evidence_policy"]["version"],
            competition_evidence.LAVER_ONLY_POLICY_VERSION,
        )
        self.assertEqual(laver_provider.call_count, 0)
        self.assertTrue(
            laver_payload["competition_evidence_policy"][
                "integral_laver_exclusion_claimed"
            ]
        )
        self.assertFalse(
            laver_payload["competition_evidence_policy"].get(
                "integral_non_ranking_exclusion_claimed", False
            )
        )


class LaverOnlyR7R8RegressionTests(unittest.TestCase):
    @staticmethod
    def _weighted_record(wins: int, matches: int) -> dict:
        return competition_evidence.weighted_binary_record(
            [
                {"tournament_name": "Vienna Open", "won": index < wins}
                for index in range(matches)
            ],
            lambda item: item["won"],
            active=True,
            policy=LAVER_ACTIVE,
        )

    def test_r7_bo5_comeback_uses_effective_sample_and_matches_manual_oracle(self):
        history = pd.DataFrame([
            {**row(1, 20260101, "Vienna Open", "Alpha", "A1",
                   score="4-6 6-3 6-4 6-2"), "best_of": 5},
            {**row(2, 20260102, "Vienna Open", "Alpha", "A2",
                   score="4-6 6-2 6-4 6-3"), "best_of": 5},
            {**row(3, 20260103, "Vienna Open", "A3", "Alpha",
                   score="6-4 4-6 6-3 6-2"), "best_of": 5},
            {**row(4, 20260104, "Laver Cup", "Alpha", "A4",
                   score="4-6 6-3 6-4 6-2"), "best_of": 5},
            {**row(5, 20260105, "Vienna Open", "Beta", "B1",
                   score="4-6 6-3 6-4 6-2"), "best_of": 5},
            {**row(6, 20260106, "Vienna Open", "B2", "Beta",
                   score="6-4 4-6 6-3 6-2"), "best_of": 5},
            {**row(7, 20260107, "Vienna Open", "B3", "Beta",
                   score="6-4 4-6 6-3 6-2"), "best_of": 5},
        ])
        without_laver = history[
            history["tourney_name"].str.casefold() != "laver cup"
        ]
        actual_a = fetch_data.compute_set1_comeback_stats(
            history, "Alpha", competition_policy=LAVER_ACTIVE
        )
        actual_b = fetch_data.compute_set1_comeback_stats(
            history, "Beta", competition_policy=LAVER_ACTIVE
        )
        oracle_a = fetch_data.compute_set1_comeback_stats(
            without_laver, "Alpha", competition_policy=LAVER_ACTIVE
        )
        oracle_b = fetch_data.compute_set1_comeback_stats(
            without_laver, "Beta", competition_policy=LAVER_ACTIVE
        )

        self.assertEqual(actual_a["bo5"]["matches_lost_set1"], 4)
        self.assertEqual(actual_a["bo5"]["weighted_matches_lost_set1"], 3)
        self.assertEqual(
            actual_a["bo5"]["comeback_rate_pct"],
            oracle_a["bo5"]["comeback_rate_pct"],
        )

        def measured(stats_a, stats_b):
            payload = {
                "player_a": "Alpha",
                "player_b": "Beta",
                "tour": "atp",
                "match_format": "bo5",
                "competition_evidence_policy":
                    competition_evidence.policy_metadata(LAVER_ACTIVE),
                "set1_comeback_stats_a": stats_a,
                "set1_comeback_stats_b": stats_b,
            }
            payload["features"] = main._compute_features(payload)
            divergence = report_html.calcular_divergencia_publico(payload)
            return payload["features"]["comeback_set1"], divergence[
                "fatores_status"
            ]["comeback_set1"]

        actual_feature, actual_status = measured(actual_a, actual_b)
        oracle_feature, oracle_status = measured(oracle_a, oracle_b)
        self.assertEqual(actual_feature["valor_a"], oracle_feature["valor_a"])
        self.assertEqual(actual_feature["amostra_a"], 3)
        self.assertEqual(
            actual_feature["amostra_a"], oracle_feature["amostra_a"]
        )
        self.assertEqual(
            actual_status["confianca_amostra"],
            oracle_status["confianca_amostra"],
        )
        self.assertEqual(
            actual_status["peso_efetivo"], oracle_status["peso_efetivo"]
        )

    def test_r8_bo5_leader_is_shared_by_feature_motor_and_html_consumers(self):
        stats_a = {
            "bo3": self._weighted_record(9, 10),
            "bo5": self._weighted_record(3, 10),
        }
        stats_b = {
            "bo3": self._weighted_record(2, 10),
            "bo5": self._weighted_record(8, 10),
        }
        payload = {
            "player_a": "Alpha",
            "player_b": "Beta",
            "tour": "atp",
            "match_format": "bo5",
            "competition_evidence_policy":
                competition_evidence.policy_metadata(LAVER_ACTIVE),
            "deciding_set_stats_a": stats_a,
            "deciding_set_stats_b": stats_b,
            "rich_stats_a": {
                "scenarios": {
                    "deciding_set_win_pct": 95,
                    "deciding_set_count": 30,
                }
            },
            "rich_stats_b": {
                "scenarios": {
                    "deciding_set_win_pct": 5,
                    "deciding_set_count": 30,
                }
            },
            "prelive_decision": {"state": "NO_EDGE"},
            "pricing": {},
        }
        payload["features"] = main._compute_features(payload)
        self.assertEqual(
            payload["features"]["recuperacao_sets"]["lider"], "Beta"
        )

        divergence = report_html.calcular_divergencia_publico(payload)
        payload["divergencia"] = divergence
        motor = divergence["fatores_status"]["recuperacao_sets"]
        self.assertEqual(motor["lider"], "Beta")
        self.assertEqual(motor["valor_a"], 30.0)
        self.assertEqual(motor["valor_b"], 80.0)

        decisive = report_html._compute_fatores_decisivos(payload)
        self.assertIn("Mais forte em sets decisivos: Beta.", decisive)
        self.assertNotIn("Mais forte em sets decisivos: Alpha.", decisive)

        action_html = report_html._mod_action_map(payload, divergence, {})
        self.assertIn("Beta · se chegar ao set decisivo", action_html)
        self.assertNotIn("Alpha · se chegar ao set decisivo", action_html)

    def test_r8_policy_off_keeps_legacy_rich_stats_presentation(self):
        off = {**LAVER_ACTIVE, "active": False, "status": "OFF"}
        payload = {
            "player_a": "Alpha",
            "player_b": "Beta",
            "match_format": "bo5",
            "competition_evidence_policy": off,
            "features": {
                "recuperacao_sets": {
                    "lider": "Beta",
                    "valor_a": 30.0,
                    "valor_b": 80.0,
                }
            },
            "rich_stats_a": {
                "scenarios": {"deciding_set_win_pct": 90}
            },
            "rich_stats_b": {
                "scenarios": {"deciding_set_win_pct": 20}
            },
        }
        decisive = report_html._compute_fatores_decisivos(payload)
        self.assertIn("Mais forte em sets decisivos: Alpha.", decisive)
        self.assertNotIn("Mais forte em sets decisivos: Beta.", decisive)


class LaverOnlyGovernanceTests(unittest.TestCase):
    def test_change_id_is_unique_and_original_alias_is_preserved(self):
        self.assertEqual(
            competition_evidence.LAVER_ONLY_CHANGE_ID,
            "CHANGE-2026-10-11-101",
        )
        self.assertEqual(
            competition_evidence.LAVER_ONLY_ORIGINAL_ALIAS,
            "CHANGE-2026-10-11-100",
        )
        self.assertEqual(
            competition_evidence.LAVER_ONLY_CONFIG_HASH,
            "a9d90d11e28721421b33",
        )


if __name__ == "__main__":
    unittest.main()
