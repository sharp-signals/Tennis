from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone

import pandas as pd

from src import competition_evidence, fetch_data, main, report_html


LAVER_ACTIVE = {
    "active": True,
    "change_id": competition_evidence.LAVER_ONLY_CHANGE_ID,
    "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
    "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-11T00:00:00+00:00",
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
            {**row(4, 20260104, "Laver Cup", "Alpha", "Epsilon", score="7-6(4) 4-6 6-2"), "won": True},
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
            row(4, 20260104, "Laver Cup", "Alpha", "Epsilon"),
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


if __name__ == "__main__":
    unittest.main()
