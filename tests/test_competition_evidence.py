from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from src import (
    calibration_store,
    competition_evidence,
    fetch_data,
    paper_trading,
    report_html,
)


ACTIVE = {
    "active": True,
    "version": competition_evidence.POLICY_VERSION,
    "config_hash": competition_evidence.CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-10T00:00:00+00:00",
}


class CompetitionClassificationTests(unittest.TestCase):
    def test_individual_reference_is_one(self):
        actual = competition_evidence.classify_match(
            {"tournament": {"id": 10, "name": "Vienna Open"}}
        )
        self.assertEqual(actual["weight"], 1.0)

    def test_laver_is_zero_by_name_or_known_id(self):
        self.assertEqual(
            competition_evidence.classify_match(
                {"tournament": {"id": 999, "name": "Laver Cup"}}
            )["weight"],
            0.0,
        )
        self.assertEqual(
            competition_evidence.classify_match({"tournamentId": 21353})["weight"],
            0.0,
        )

    def test_davis_competitive_is_half_and_symmetric(self):
        win = {
            "id": 1,
            "tournament": {"name": "Davis Cup, World Group"},
            "competition_context": {
                "davis_tie_status_before_match": "IN_DISPUTE"
            },
            "won": True,
        }
        loss = {**win, "id": 2, "won": False}
        record = competition_evidence.weighted_binary_record(
            [win, loss], lambda row: row["won"], active=True
        )
        self.assertEqual(record["wins"], 1)
        self.assertEqual(record["losses"], 1)
        self.assertEqual(record["weighted_wins"], 0.5)
        self.assertEqual(record["weighted_losses"], 0.5)
        self.assertEqual(record["weighted_matches"], 1.0)

    def test_davis_decided_and_unknown_have_no_invented_coefficient(self):
        decided = competition_evidence.classify_match({
            "tournament_name": "Davis Cup, QF, AAA-BBB 3-1",
            "davis_tie_status_before_match": "DECIDED",
        })
        unknown = competition_evidence.classify_match({
            "tournament_name": "Davis Cup, QF, AAA-BBB 3-1",
        })
        self.assertIsNone(decided["weight"])
        self.assertEqual(
            decided["reason_code"],
            "DAVIS_TIE_ALREADY_DECIDED_NO_COEFFICIENT",
        )
        self.assertIsNone(unknown["weight"])
        self.assertEqual(
            unknown["reason_code"], "DAVIS_PRE_MATCH_TIE_STATE_UNKNOWN"
        )

    def test_final_tie_score_and_individual_winner_never_infer_state(self):
        actual = competition_evidence.classify_match({
            "name": "Davis Cup, Q2, CZE-USA 3-2",
            "match_winner": 101,
        })
        self.assertIsNone(actual["weight"])
        self.assertEqual(actual["status"], "BLOCKED")

    def test_ambiguous_top_level_name_is_not_promoted_to_individual(self):
        actual = competition_evidence.classify_match({
            "name": "Davis Smith vs Player B",
            "match_winner": 101,
        })
        self.assertEqual(actual["competition"], "UNRESOLVED")
        self.assertIsNone(actual["weight"])
        self.assertEqual(
            actual["reason_code"], "COMPETITION_IDENTITY_UNRESOLVED"
        )

    def test_id_only_generic_cup_and_conflict_fail_closed(self):
        for record, reason in (
            ({"tournamentId": 999}, "COMPETITION_IDENTITY_UNRESOLVED"),
            (
                {"tournament": {"rankId": 5}},
                "COMPETITION_IDENTITY_UNRESOLVED",
            ),
            (
                {"tournament_name": "Mystery Cup"},
                "COMPETITION_CUP_IDENTITY_UNRESOLVED",
            ),
            (
                {
                    "tournamentId": 21353,
                    "tournament_name": "Davis Cup",
                    "davis_tie_status_before_match": "IN_DISPUTE",
                },
                "COMPETITION_IDENTITY_CONFLICT",
            ),
        ):
            with self.subTest(record=record):
                actual = competition_evidence.classify_match(record)
                self.assertIsNone(actual["weight"])
                self.assertEqual(actual["reason_code"], reason)

    def test_same_sample_is_selected_before_weights_and_raw_counts_remain_integer(self):
        records = [
            {"id": "individual", "tournament_name": "Vienna Open", "won": True},
            {"id": "laver", "tournament_name": "Laver Cup", "won": False},
            {
                "id": "davis",
                "tournament_name": "Davis Cup",
                "davis_tie_status_before_match": "IN_DISPUTE",
                "won": False,
            },
        ]
        actual = competition_evidence.weighted_binary_record(
            records, lambda row: row["won"], active=True
        )
        self.assertEqual((actual["wins"], actual["losses"], actual["matches"]), (1, 2, 3))
        self.assertEqual(actual["weighted_wins"], 1.0)
        self.assertEqual(actual["weighted_losses"], 0.5)
        self.assertEqual(actual["weighted_matches"], 1.5)
        self.assertEqual(actual["weighted_win_rate_pct"], 66.7)
        self.assertEqual(actual["competition_evidence"]["laver_excluded"], 1)
        self.assertEqual(actual["competition_evidence"]["davis_weighted"], 1)

    def test_unknown_davis_blocks_weighted_rate_without_erasing_raw_history(self):
        actual = competition_evidence.weighted_binary_record(
            [{"id": 7, "tournament_name": "Davis Cup", "won": True}],
            lambda row: row["won"],
            active=True,
        )
        self.assertEqual(actual["wins"], 1)
        self.assertEqual(actual["matches"], 1)
        self.assertIsNone(actual["weighted_matches"])
        self.assertIsNone(actual["weighted_win_rate_pct"])
        self.assertFalse(
            actual["competition_evidence"]["eligible_for_performance"]
        )


class CompetitionTransformParityTests(unittest.TestCase):
    def test_api_and_local_recent_form_apply_the_same_weights(self):
        rows = [
            {
                "id": 1,
                "date": "2026-10-01T00:00:00+00:00",
                "player1Id": 10,
                "player2Id": 20,
                "match_winner": 10,
                "court": "Hard",
                "tournament": {"name": "Vienna Open"},
            },
            {
                "id": 2,
                "date": "2026-10-02T00:00:00+00:00",
                "player1Id": 10,
                "player2Id": 21,
                "match_winner": 21,
                "court": "Hard",
                "tournament": {"name": "Laver Cup"},
            },
            {
                "id": 3,
                "date": "2026-10-03T00:00:00+00:00",
                "player1Id": 10,
                "player2Id": 22,
                "match_winner": 10,
                "court": "Hard",
                "tournament": {"name": "Davis Cup"},
                "davis_tie_status_before_match": "IN_DISPUTE",
            },
        ]
        api = fetch_data.compute_form_from_recent(
            rows,
            10,
            datetime(2026, 10, 11, tzinfo=timezone.utc),
            10,
            "Hard",
            competition_policy=ACTIVE,
        )["form"]
        local = pd.DataFrame([
            {
                "tourney_date": 20261001,
                "winner_name": "Player A",
                "loser_name": "Player B",
                "surface": "Hard",
                "tourney_name": "Vienna Open",
            },
            {
                "tourney_date": 20261002,
                "winner_name": "Player B",
                "loser_name": "Player A",
                "surface": "Hard",
                "tourney_name": "Laver Cup",
            },
            {
                "tourney_date": 20261003,
                "winner_name": "Player A",
                "loser_name": "Player C",
                "surface": "Hard",
                "tourney_name": "Davis Cup",
                "davis_tie_status_before_match": "IN_DISPUTE",
            },
        ])
        fallback = fetch_data.compute_recent_form(
            local, "Player A", 10, competition_policy=ACTIVE
        )
        self.assertEqual(api["weighted_wins"], fallback["weighted_wins"])
        self.assertEqual(api["weighted_losses"], fallback["weighted_losses"])
        self.assertEqual(api["weighted_matches"], fallback["weighted_matches"])
        self.assertEqual(api["weighted_win_rate_pct"], fallback["weighted_win_rate_pct"])

    def test_h2h_api_and_local_use_weighted_counts(self):
        api_rows = [
            {
                "id": 1,
                "player1Id": 10,
                "player2Id": 20,
                "match_winner": 10,
                "tournament": {"name": "Vienna Open"},
            },
            {
                "id": 2,
                "player1Id": 10,
                "player2Id": 20,
                "match_winner": 20,
                "tournament": {"name": "Laver Cup"},
            },
        ]
        api = fetch_data.compute_h2h_from_api(
            api_rows, 10, 20, competition_policy=ACTIVE
        )["overall"]
        local_rows = pd.DataFrame([
            {
                "winner_name": "A", "loser_name": "B",
                "tourney_name": "Vienna Open", "tourney_date": 20261001,
            },
            {
                "winner_name": "B", "loser_name": "A",
                "tourney_name": "Laver Cup", "tourney_date": 20261002,
            },
        ])
        local = fetch_data.compute_h2h(
            local_rows, "A", "B", competition_policy=ACTIVE
        )["overall"]
        self.assertEqual(api["weighted_a_wins"], 1.0)
        self.assertEqual(api["weighted_b_wins"], 0.0)
        self.assertEqual(api["weighted_total_matches"], 1.0)
        self.assertEqual(api["weighted_a_wins"], local["weighted_a_wins"])
        self.assertEqual(api["weighted_b_wins"], local["weighted_b_wins"])

    def test_inactive_policy_preserves_legacy_shape(self):
        frame = pd.DataFrame([
            {
                "winner_name": "A", "loser_name": "B",
                "tourney_name": "Laver Cup", "tourney_date": 20261001,
            }
        ])
        actual = fetch_data.compute_recent_form(frame, "A", 10)
        self.assertEqual(actual, {"matches": 1, "wins": 1, "losses": 0})


class CompetitionContractTests(unittest.TestCase):
    def test_activation_is_explicit_and_forward_only(self):
        self.assertFalse(
            competition_evidence.activation_from_environment({})["active"]
        )
        active = competition_evidence.activation_from_environment({
            competition_evidence.ACTIVATION_VERSION_ENV:
                competition_evidence.POLICY_VERSION,
            competition_evidence.ACTIVATION_UTC_ENV:
                "2000-01-01T00:00:00+00:00",
        })
        self.assertTrue(active["active"])
        self.assertEqual(active["application"], "PROSPECTIVE_ONLY")

    def test_unseparable_factors_remain_factual_but_are_blocked_at_consumption(self):
        guarded, blockers = competition_evidence.guard_features(
            {
                "ranking": {"lider": "A"},
                "forma_recente": {"lider": "A"},
                "servico_carreira": {"lider": "B"},
                "nivel_adversario": {"lider": "B"},
                "frescura": {"mais_fresco": "A"},
            },
            active=True,
            tour="atp",
        )
        self.assertIn("ranking", guarded)
        self.assertIn("forma_recente", guarded)
        self.assertIn("frescura", guarded)
        self.assertIn("servico_carreira", guarded)
        self.assertIn("nivel_adversario", guarded)
        blocked = {item["feature"] for item in blockers}
        self.assertTrue(
            {"forma_recente", "servico_carreira", "nivel_adversario"}.issubset(
                blocked
            )
        )
        self.assertEqual(
            {item["reason_code"] for item in blockers},
            {"COMPETITION_EVIDENCE_NOT_SEPARABLE"},
        )

    def test_wta_is_out_of_scope_and_unchanged(self):
        scoped = competition_evidence.activation_for_tour(ACTIVE, "wta")
        self.assertFalse(scoped["active"])
        features = {"servico_carreira": {"lider": "A"}}
        guarded, blockers = competition_evidence.guard_features(
            features, active=scoped["active"], tour="wta"
        )
        self.assertEqual(guarded, features)
        self.assertEqual(blockers, [])

    def test_raw_cache_key_is_reusable_and_derived_scope_is_versioned(self):
        self.assertEqual(
            competition_evidence.derived_cache_scope("raw:player:1", {"active": False}),
            "raw:player:1",
        )
        scoped = competition_evidence.derived_cache_scope(
            "derived:player:1", {"active": True}
        )
        self.assertIn(competition_evidence.POLICY_VERSION, scoped)
        self.assertIn(competition_evidence.CONFIG_HASH, scoped)

    def test_policy_propagates_to_snapshot_and_paper(self):
        policy = competition_evidence.policy_metadata(ACTIVE)
        payload = {
            "tour": "atp",
            "match_id": 99,
            "player_a": "A",
            "player_b": "B",
            "competition_evidence_policy": policy,
            "prelive_decision": {
                "paper_eligible": True,
                "paper_markets": [{
                    "market_type": "MONEYLINE", "side": "a",
                    "market": "Moneyline A", "player": "A", "odd": 2.0,
                }],
            },
            "snapshot_key": "atp:99",
        }
        snapshot = calibration_store.build_snapshot(
            payload, {}, analyzed_at_utc="2026-10-10T12:00:00+00:00"
        )
        self.assertEqual(
            snapshot["competition_evidence_policy"]["config_hash"],
            competition_evidence.CONFIG_HASH,
        )
        with patch.object(
            paper_trading.tournament_policy, "paper_block_reason", return_value=None
        ), patch.object(
            paper_trading.market_integrity,
            "is_operational_pricing_payload",
            return_value=True,
        ):
            entries = paper_trading.build_entries(payload)
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["pregame"]["competition_evidence_policy"]["version"],
            competition_evidence.POLICY_VERSION,
        )

    def test_report_exposes_version_hash_and_partial_limitation(self):
        policy = competition_evidence.policy_metadata(ACTIVE)
        policy["feature_blockers"] = [{
            "feature": "servico_carreira",
            "reason_code": "COMPETITION_EVIDENCE_NOT_SEPARABLE",
        }]
        html = report_html._pagina(
            "A", "B", report_html._mod_competition_evidence_notice(
                {"competition_evidence_policy": policy}
            ),
            identity_metadata={"competition_evidence_policy": policy},
        )
        self.assertIn(competition_evidence.POLICY_VERSION, html)
        self.assertIn(competition_evidence.CONFIG_HASH, html)
        self.assertIn("não é declarada exclusão integral da Laver", html)


if __name__ == "__main__":
    unittest.main()
