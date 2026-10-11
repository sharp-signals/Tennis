from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.competition_evidence_impact_audit import build_audit
from src import competition_evidence, competition_registry, fetch_data, report_html


ACTIVE = {
    "active": True,
    "change_id": competition_evidence.RANKING_ELIGIBLE_CHANGE_ID,
    "version": competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
    "config_hash": competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-12T00:00:00+00:00",
    "tour": "atp",
}


def row(match_id, date, tournament, winner="Alpha", loser="Beta", *,
        tier=None, score="4-6 7-6(4) 6-2"):
    result = {
        "id": match_id, "tourney_date": date, "tourney_name": tournament,
        "winner_name": winner, "loser_name": loser,
        "winner_rank": 10, "loser_rank": 30,
        "winner_hand": "R", "loser_hand": "L", "surface": "Hard",
        "round": "QF", "best_of": 3, "score": score,
    }
    if tier is not None:
        result["tier"] = tier
    return result


class RegistryClassificationTests(unittest.TestCase):
    def test_acceptance_matrix(self):
        cases = (
            ({"tournament_name": "Laver Cup", "date": "2026-09-20"},
             "NON_RANKING", 0.0),
            ({"tournament_name": "Davis Cup", "date": "2026-02-01"},
             "DAVIS_EXCEPTION", 1.0),
            ({"tournament_name": "Next Gen ATP Finals", "date": "2026-12-01"},
             "NEXT_GEN_EXCEPTION", 1.0),
            ({"tournament_name": "Olympic Games", "date": "2024-07-27"},
             "OLYMPICS_EXCEPTION", 1.0),
            ({"tournament_name": "United Cup", "date": "2026-01-01"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Nitto ATP Finals", "date": "2026-11-15"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Any ATP 250", "tier": "ATP 250"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Any ATP 500", "tier": "ATP 500"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Any Masters", "tier": "ATP Masters 1000"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Any Slam", "tier": "Grand Slam"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Any Challenger", "tier": "Challenger 125"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tournament_name": "Any ITF", "tier": "ITF M15"},
             "RANKING_ELIGIBLE", 1.0),
            ({"tourney_name": "Wimbledon", "tourney_date": 20220627},
             "NON_RANKING", 0.0),
            ({"tourney_name": "Wimbledon", "tourney_date": 20230703},
             "RANKING_ELIGIBLE", 1.0),
        )
        for record, expected_class, expected_weight in cases:
            with self.subTest(record=record):
                actual = competition_evidence.classify_match(record, ACTIVE)
                self.assertEqual(actual["classification"], expected_class)
                self.assertEqual(actual["weight"], expected_weight)

    def test_tennis_data_exact_field_names_are_supported(self):
        result = competition_evidence.classify_match(
            {
                "Tournament": "Winston Salem",
                "Date": "2026-08-22",
                "Series": "ATP250",
            },
            ACTIVE,
        )
        self.assertEqual(result["classification"], "RANKING_ELIGIBLE")
        self.assertEqual(result["weight"], 1.0)
        self.assertIn(
            "category:Series",
            {
                signal["matched_by"]
                for signal in result["identity_evidence"]
            },
        )

    def test_unknown_conflict_rank_fields_odds_and_fuzzy_names_fail_closed(self):
        cases = (
            {},
            {"tournament": {"name": "Mystery Event", "rank": 1, "rankId": 3}},
            {"tournament_name": "Mystery Event", "odd1": 1.2, "odd2": 4.0},
            {"tournament_name": "United Cupp"},
            {"tournament_name": "Laver Cup", "tier": "ATP 500"},
        )
        for record in cases:
            with self.subTest(record=record):
                result = competition_evidence.classify_match(record, ACTIVE)
                self.assertEqual(result["classification"], "UNRESOLVED")
                self.assertIsNone(result["weight"])
                self.assertEqual(result["status"], "BLOCKED")

    def test_policy_registry_and_activation_contract(self):
        self.assertEqual(
            competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
            "atp-ranking-eligible-performance-v1",
        )
        self.assertNotEqual(
            competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH,
            competition_evidence.LAVER_ONLY_CONFIG_HASH,
        )
        self.assertEqual(len(competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH), 20)
        self.assertEqual(len(competition_evidence.RANKING_REGISTRY_SHA256), 64)
        self.assertTrue(competition_evidence.policy_is_supported(ACTIVE))
        self.assertTrue(competition_evidence.is_ranking_eligible(ACTIVE))
        self.assertFalse(
            competition_evidence.activation_from_environment({})["active"]
        )
        selected = competition_evidence.activation_from_environment({
            competition_evidence.ACTIVATION_VERSION_ENV:
                competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
            competition_evidence.ACTIVATION_UTC_ENV: "2020-01-01T00:00:00Z",
        })
        self.assertTrue(selected["active"])
        self.assertEqual(
            selected["config_hash"],
            competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH,
        )
        wta = competition_evidence.activation_for_tour(selected, "wta")
        self.assertFalse(wta["active"])
        self.assertEqual(wta["status"], "OUT_OF_SCOPE_TOUR")


    def test_loader_scope_is_telemetry_only_and_exact_identity_wins(self):
        expected = {
            "Laver Cup": "NON_RANKING",
            "Davis Cup": "DAVIS_EXCEPTION",
            "Next Gen ATP Finals": "NEXT_GEN_EXCEPTION",
            "Olympic Games": "OLYMPICS_EXCEPTION",
        }
        for name, classification in expected.items():
            result = competition_evidence.classify_match(
                {
                    "tournament_name": name,
                    "_history_competition_scope": "main",
                },
                ACTIVE,
            )
            self.assertEqual(result["classification"], classification)
            self.assertEqual(result["history_competition_scope"], "main")
            self.assertFalse(result["history_scope_authoritative"])
            self.assertTrue(all(
                item["matched_by"] != "repository_history_scope"
                for item in result["identity_evidence"]
            ))
        unresolved = competition_evidence.classify_match(
            {
                "tournament_name": "Unknown Source Event",
                "_history_competition_scope": "main",
            },
            ACTIVE,
        )
        self.assertEqual(unresolved["classification"], "UNRESOLVED")
        self.assertIsNone(unresolved["weight"])

    def test_every_authorizing_signal_has_resolved_provenance(self):
        cases = (
            {"tournament_name": "Laver Cup"},
            {"tournament_name": "Davis Cup"},
            {"tournament_name": "Next Gen ATP Finals"},
            {"tournament_name": "Olympic Games"},
            {"tournament_name": "Vienna Open"},
            {"tournament_name": "Any ATP 500", "tier": "ATP 500"},
            {"tourney_name": "Wimbledon", "tourney_date": 20220627},
            {"tournamentId": 21353},
        )
        provenance = competition_registry.REGISTRY["provenance"]
        for record in cases:
            result = competition_evidence.classify_match(record, ACTIVE)
            self.assertTrue(result["identity_evidence"], record)
            for signal in result["identity_evidence"]:
                key = signal["provenance_key"]
                self.assertIn(key, provenance)
                self.assertEqual(signal["provenance"], provenance[key])
                self.assertTrue(signal["provenance"].startswith("https://"))



class RankingEligibleTransformTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame([
            row(1, 20260101, "Vienna Open"),
            row(2, 20260102, "Davis Cup", "Beta", "Alpha"),
            row(3, 20260103, "Next Gen ATP Finals"),
            row(4, 20260104, "Olympic Games", "Beta", "Alpha"),
            row(5, 20260105, "Laver Cup"),
            row(6, 20220627, "Wimbledon"),
            row(7, 20230703, "Wimbledon"),
        ])

    def test_select_first_then_classify_with_full_distribution(self):
        result = competition_evidence.weighted_binary_record(
            self.history.to_dict("records"),
            lambda item: item["winner_name"] == "Alpha",
            active=True, policy=ACTIVE,
        )
        self.assertEqual(result["matches"], 7)
        self.assertEqual(result["weighted_matches"], 5)
        counts = result["competition_evidence"]["classification_counts"]
        self.assertEqual(counts["NON_RANKING"], 2)
        self.assertEqual(counts["DAVIS_EXCEPTION"], 1)
        self.assertEqual(counts["NEXT_GEN_EXCEPTION"], 1)
        self.assertEqual(counts["OLYMPICS_EXCEPTION"], 1)

    def test_h2h_tiebreak_deciding_comeback_hands_opponent_and_confidence(self):
        h2h = fetch_data.compute_h2h(
            self.history, "Alpha", "Beta", "Hard",
            competition_policy=ACTIVE,
        )
        self.assertEqual(
            h2h["overall"]["weighted_a_wins"]
            + h2h["overall"]["weighted_b_wins"],
            5,
        )
        self.assertEqual(
            h2h["overall"]["competition_evidence"]["non_ranking_excluded"], 2
        )
        families = (
            fetch_data.compute_tiebreak_stats(
                self.history, "Alpha", competition_policy=ACTIVE
            ),
            fetch_data.compute_deciding_set_stats(
                self.history, "Alpha", competition_policy=ACTIVE
            )["bo3"],
            fetch_data.compute_set1_comeback_stats(
                self.history, "Alpha", competition_policy=ACTIVE
            )["bo3"],
            fetch_data.compute_round_stage_stats(
                self.history, "Alpha", competition_policy=ACTIVE
            )["late_rounds"],
            fetch_data.compute_handedness_matchup_stats(
                self.history, "Alpha", tour="atp",
                competition_policy=ACTIVE,
            )["vs_left_handed"],
            fetch_data.compute_opponent_level_stats(
                self.history, "Alpha", 50, competition_policy=ACTIVE
            ),
        )
        for family in families:
            self.assertTrue(
                competition_evidence.evidence_is_compatible(family, ACTIVE),
                family,
            )
            rate, sample = competition_evidence.record_rate(family)
            if sample:
                self.assertIsNotNone(rate)
            else:
                self.assertIsNone(rate)

    def test_cpi_record_uses_explicit_competition_evidence(self):
        record = competition_evidence.weighted_binary_record(
            [
                {
                    "tournament_name": "Exact Source Event",
                    "tier": "ATP 500",
                    "_history_competition_scope": "main",
                    "won": True,
                },
                {"tournament_name": "Laver Cup", "won": False},
            ],
            lambda item: item["won"], active=True, policy=ACTIVE,
        )
        self.assertEqual(record["weighted_matches"], 1)
        self.assertTrue(
            competition_evidence.evidence_is_compatible(record, ACTIVE)
        )
        blocked = competition_evidence.classify_match(
            {
                "tournament_name": "Unknown",
                "_history_competition_scope": "main",
                "tournament": {"rankId": 3},
            },
            ACTIVE,
        )
        self.assertIsNone(blocked["weight"])


    def test_fatigue_load_remains_raw_for_non_ranking_matches(self):
        start = datetime(2026, 1, 10, tzinfo=timezone.utc)
        baseline = fetch_data.compute_fatigue(self.history, "Alpha", start)
        after = fetch_data.compute_fatigue(self.history, "Alpha", start)
        self.assertEqual(after, baseline)
        self.assertNotIn("competition_evidence", after or {})

    def test_off_current_policy_parity_and_no_stacking(self):
        clean = [row(10, 20260101, "Vienna Open")]
        off = competition_evidence.weighted_binary_record(
            clean, lambda item: True, active=False, policy=ACTIVE
        )
        current_policy = {
            "active": True, "tour": "atp",
            "change_id": competition_evidence.LAVER_ONLY_CHANGE_ID,
            "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
            "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
        }
        current = competition_evidence.weighted_binary_record(
            clean, lambda item: True, active=True, policy=current_policy
        )
        self.assertEqual(off["matches"], current["matches"])
        self.assertEqual(current["weighted_matches"], 1)
        self.assertFalse(competition_evidence.is_ranking_eligible(current_policy))

    def test_incompatible_cache_or_aggregate_cannot_reenter(self):
        stale = {
            "competition_evidence": {
                "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
                "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
                "eligible_for_performance": True,
            }
        }
        self.assertFalse(
            competition_evidence.evidence_is_compatible(stale, ACTIVE)
        )
        guarded, blockers = competition_evidence.guard_features(
            {"tiebreak": {"lider": "Alpha", **stale}},
            active=True, tour="atp", policy=ACTIVE,
        )
        self.assertIn("tiebreak", guarded)
        self.assertEqual(
            blockers[0]["reason_code"],
            "COMPETITION_EVIDENCE_NOT_SEPARABLE",
        )

    def test_html_carries_new_version_and_hash(self):
        policy = competition_evidence.policy_metadata(ACTIVE)
        policy["feature_blockers"] = []
        html = report_html._pagina(
            "Alpha", "Beta",
            report_html._mod_competition_evidence_notice(
                {"competition_evidence_policy": policy}
            ),
            identity_metadata={"competition_evidence_policy": policy},
        )
        self.assertIn(
            competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION, html
        )
        self.assertIn(
            competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH, html
        )
        self.assertIn("ranking-eligible", html)
        self.assertIn("Davis, Next Gen e Olympics contam a 100%", html)
        self.assertIn("NON_RANKING", html)
        self.assertIn("UNRESOLVED", html)
        self.assertNotIn("Davis competitiva 50%", html)


class OfflineImpactAuditTests(unittest.TestCase):
    def test_real_committed_cache_impact_audit(self):
        audit = build_audit(Path("data/cache/players/atp"))
        self.assertGreater(audit["cache_files"], 0)
        self.assertGreater(audit["unique_matches"], 0)
        self.assertEqual(
            audit["row_applicability_proxy"]["fatigue_load"]["rows_removed"], 0
        )
        print(
            "[change102-impact-audit] "
            + json.dumps(audit, ensure_ascii=False, sort_keys=True)
        )

    def test_audit_deduplicates_and_reports_required_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {
                    "id": "1", "date": "2026-09-20",
                    "tournament": {
                        "id": 21353, "name": "Laver Cup", "courtId": 1
                    },
                    "player1": {"id": 1, "name": "A"},
                    "player2": {"id": 2, "name": "B"},
                    "result": "7-6(2) 6-4",
                },
                {
                    "id": "2", "date": "2026-02-01",
                    "tournament": {
                        "id": 2, "name": "Davis Cup", "courtId": 1
                    },
                    "player1": {"id": 1, "name": "A"},
                    "player2": {"id": 3, "name": "C"},
                    "result": "4-6 6-3 6-2",
                },
                {
                    "id": "3", "date": "2026-03-01",
                    "tournament": {
                        "id": 3, "name": "Unknown Open", "rankId": 3
                    },
                    "player1": {"id": 1, "name": "A"},
                    "player2": {"id": 4, "name": "D"},
                    "result": "6-4 6-4",
                },
            ]
            payload = {"entries": {"recent_matches": {"data": rows}}}
            (root / "1.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            (root / "2.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            audit = build_audit(root)
        self.assertEqual(audit["cached_rows_physical"], 6)
        self.assertEqual(audit["unique_matches"], 3)
        self.assertEqual(
            audit["classification_distribution"]["NON_RANKING"], 1
        )
        self.assertEqual(
            audit["classification_distribution"]["DAVIS_EXCEPTION"], 1
        )
        self.assertEqual(
            audit["classification_distribution"]["UNRESOLVED"], 1
        )
        self.assertEqual(
            audit["row_applicability_proxy"]["fatigue_load"]["rows_removed"], 0
        )
        self.assertEqual(
            audit["policy_comparison"]["laver_only_rows_admitted"], 2
        )
        self.assertEqual(
            audit["policy_comparison"]["laver_only_rows_excluded"], 1
        )
        self.assertEqual(
            audit["row_applicability_proxy"]["tiebreak"]["laver_only_admitted"],
            0,
        )
        self.assertEqual(
            audit["row_applicability_proxy"]["tiebreak"]["laver_only_excluded"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
