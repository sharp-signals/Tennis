import copy
import tempfile
import unittest
from pathlib import Path

from src import calibration_store, paper_trading
from src.telegram_summary import decision_row as _telegram_decision_row, state_counts as telegram_state_counts
from src.prelive_decision import (
    EDGE_NEGATIVE,
    EDGE_POSITIVE,
    EDGE_POSITIVE_COVERAGE_INSUFFICIENT,
    EDGE_ZERO,
    REPORT_NULL,
    PRICING_UNAVAILABLE,
    _action_block_available,
    _service_block_available,
    assess_report,
    build_decision,
    weighted_coverage,
)


class PreliveOperationalContractTests(unittest.TestCase):
    def payload(self):
        return {
            "match_id": 77,
            "tour": "atp",
            "player_a": "Alpha One",
            "player_b": "Beta Two",
            "player_a_id": 1,
            "player_b_id": 2,
            "ranking_a": {"rank": 10},
            "ranking_b": {"rank": 20},
            "pressure_profile_a": {"matches": 6, "first_serve_won_pct": 65},
            "pressure_profile_b": {"matches": 6, "first_serve_won_pct": 62},
            "fatigue_signal_a": {"matches_last_7d": 1},
            "fatigue_signal_b": {"matches_last_7d": 1},
            "market_odds_decimal": {"player_a": 2.0, "player_b": 1.9},
            "snapshot_key": "atp:77",
            "report_id": "report-77",
            "analyzed_at_utc": "2026-08-28T10:00:00+00:00",
        }

    def divergence(self, available=True):
        return {
            "indice_evidencia_a": 70,
            "indice_evidencia_b": 30,
            "fatores_status": {
                "ranking": {"disponivel": available, "peso_base_configurado": 10},
                "forma": {"disponivel": True, "peso_base_configurado": 5},
            },
        }

    def assessment(self):
        return {
            "report_null": False,
            "coverage": {"weighted_pct": 75.0, "status": "reduzida"},
        }

    def pricing(self, edge):
        return {
            "available": True,
            "players": {
                "a": {"expected_edge_pct": edge, "market_odd": 2.0, "fair_odd": 1.95, "sharp_estimate_pct": 51.3},
                "b": {"expected_edge_pct": -abs(edge or 0.1), "market_odd": 1.9, "fair_odd": 2.05, "sharp_estimate_pct": 48.7},
            },
        }

    def decision(self, edge):
        return build_decision(self.payload(), self.divergence(), self.pricing(edge), self.assessment())

    def test_edge_plus_point_one_enters_paper(self):
        decision = self.decision(0.1)
        self.assertEqual(decision["state"], EDGE_POSITIVE)
        self.assertTrue(decision["paper_eligible"])

    def test_positive_edge_below_paper_coverage_gate_is_visible_but_excluded(self):
        assessment = {"report_null": False, "coverage": {"weighted_pct": 46.5, "status": "reduzida"}}
        decision = build_decision(self.payload(), self.divergence(), self.pricing(1.0), assessment)
        self.assertEqual(decision["state"], EDGE_POSITIVE_COVERAGE_INSUFFICIENT)
        self.assertFalse(decision["paper_eligible"])
        self.assertEqual(decision["paper_markets"], [])
        self.assertIn("46.5%", decision["reason"])
        payload = self.payload(); payload["prelive_decision"] = decision
        self.assertEqual(_telegram_decision_row(payload)[1], "🟡")
        self.assertIn("insuficiente para PAPER", _telegram_decision_row(payload)[2])

    def test_edge_zero_is_excluded(self):
        decision = self.decision(0.0)
        self.assertEqual(decision["state"], EDGE_ZERO)
        self.assertFalse(decision["paper_eligible"])

    def test_edge_minus_point_one_is_excluded(self):
        decision = self.decision(-0.1)
        self.assertEqual(decision["state"], EDGE_NEGATIVE)
        self.assertFalse(decision["paper_eligible"])

    def test_both_positive_edges_are_blocked_as_anomaly(self):
        pricing = self.pricing(0.1)
        pricing["players"]["b"]["expected_edge_pct"] = 0.2
        decision = build_decision(
            self.payload(), self.divergence(), pricing, self.assessment()
        )
        self.assertEqual(decision["state"], REPORT_NULL)
        self.assertEqual(decision["conflict"], "both_sides_positive_edge")
        self.assertFalse(decision["paper_eligible"])

    def test_missing_ranking_makes_report_null(self):
        payload = self.payload()
        payload["ranking_b"] = None
        assessment = assess_report(payload, self.divergence())
        self.assertTrue(assessment["report_null"])
        self.assertIn("ranking", assessment["primary_reason"])

    def test_service_zero_with_zero_sample_is_missing(self):
        payload = self.payload()
        payload["pressure_profile_a"] = {"matches": 0, "first_serve_won_pct": 0}
        self.assertFalse(_service_block_available(payload))

    def test_recovery_zero_with_zero_sample_is_missing(self):
        payload = self.payload()
        payload["fatigue_signal_a"] = {}
        payload["fatigue_signal_b"] = {}
        payload["rich_stats_a"] = {"scenarios": {"first_set_lose_then_win_pct": 0, "first_set_lose_count": 0}}
        payload["rich_stats_b"] = {"scenarios": {"first_set_lose_then_win_pct": 50, "first_set_lose_count": 5}}
        self.assertFalse(_action_block_available(payload))

    def test_missing_factor_is_not_scored_as_zero(self):
        coverage = weighted_coverage(self.divergence(available=False))
        self.assertEqual(coverage["available_weight"], 5)
        self.assertEqual(coverage["configured_weight"], 15)

    def test_valid_factors_are_renormalized_over_available_mass(self):
        coverage = weighted_coverage(self.divergence(available=False))
        self.assertAlmostEqual(coverage["weighted_ratio"], 1 / 3, places=5)
        # A massa em falta é explicitamente separada; nunca vira contribuição
        # para Alpha nem Beta.
        self.assertEqual(coverage["available_factors"], 1)

    def test_reduced_coverage_is_visible(self):
        assessment = assess_report(self.payload(), self.divergence())
        self.assertIn("weighted_pct", assessment["coverage"])
        self.assertIn(assessment["coverage"]["status"], {"reduzida", "suficiente", "insuficiente"})

    def test_insufficient_coverage_makes_report_null(self):
        divergence = self.divergence(False)
        divergence["fatores_status"]["forma"]["disponivel"] = False
        self.assertTrue(assess_report(self.payload(), divergence)["report_null"])

    def test_null_report_never_enters_paper(self):
        assessment = {"report_null": True, "primary_reason": "sem ranking", "coverage": {"weighted_pct": 0}}
        decision = build_decision(self.payload(), self.divergence(), self.pricing(20), assessment)
        self.assertEqual(decision["state"], REPORT_NULL)
        self.assertFalse(decision["paper_eligible"])

    def test_missing_price_is_not_a_factual_report_null(self):
        unavailable = {"available": False, "reason": "missing_or_invalid_two_way_moneyline"}
        decision = build_decision(self.payload(), self.divergence(), unavailable, self.assessment())
        self.assertEqual(decision["state"], PRICING_UNAVAILABLE)
        self.assertFalse(decision["paper_eligible"])

    def test_snapshot_pregame_is_immutable_after_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.json"
            payload = self.payload()
            snapshot = calibration_store.build_snapshot(payload, {})
            calibration_store.upsert_snapshots([snapshot], path)
            before = copy.deepcopy(calibration_store._read(path)["snapshots"][0])
            calibration_store.settle_from_matches([{
                "id": 77, "match_winner": 1, "result_type": "completed", "result": "6-4 6-4",
            }], path)
            after = calibration_store._read(path)["snapshots"][0]
            self.assertEqual(before["metrics"], after["metrics"])
            self.assertIsNotNone(after["outcome"])

    def test_snapshot_and_paper_freeze_odds_provenance(self):
        payload = self.payload()
        payload.update({
            "odds_source": "RapidAPI Moneyline",
            "odds_endpoint": "https://example.test/odds",
            "odds_event_id": "123",
            "odds_captured_at_utc": "2026-08-28T09:59:00+00:00",
            "odds_capture_kind": "current_at_capture",
            "odds_bookmaker": "Book A",
            "event_key": "atp:77",
            "entry_market_observation_id": "observation-77",
            "market_memory_status": "RECORDED",
            "market_memory_eligible": True,
        })
        snapshot = calibration_store.build_snapshot(payload, {})
        self.assertEqual(snapshot["odds_provenance"]["captured_at_utc"], payload["odds_captured_at_utc"])
        self.assertEqual(snapshot["odds_provenance"]["endpoint"], payload["odds_endpoint"])
        payload["prelive_decision"] = self.decision(0.1)
        entry = paper_trading.build_entries(payload)[0]
        self.assertEqual(entry["pregame"]["odds_provenance"]["capture_kind"], "current_at_capture")
        self.assertEqual(entry["pregame"]["odds_provenance"]["bookmaker"], "Book A")
        self.assertEqual(entry["pregame"]["event_key"], "atp:77")
        self.assertEqual(entry["pregame"]["entry_market_observation_id"], "observation-77")
        self.assertTrue(entry["pregame"]["market_memory_eligible"])

    def test_later_data_does_not_mutate_original_paper_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.json"
            payload = self.payload()
            payload["prelive_decision"] = self.decision(0.1)
            entries = paper_trading.build_entries(payload)
            paper_trading.append_entries(entries, path)
            changed = copy.deepcopy(entries[0])
            changed["pregame"]["odd"] = 9.99
            paper_trading.append_entries([changed], path)
            self.assertEqual(paper_trading.read_entries(path)[0]["pregame"]["odd"], 2.0)

    def test_moneyline_settlement_adds_result_and_pnl_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.json"
            payload = self.payload(); payload["prelive_decision"] = self.decision(0.1)
            entry = paper_trading.build_entries(payload)[0]
            original_pregame = copy.deepcopy(entry["pregame"])
            paper_trading.append_entries([entry], path)
            settled = paper_trading.settle_from_matches([{
                "id": 77, "match_winner": 1, "result_type": "completed", "result": "6-4 6-4",
            }], path)
            saved = paper_trading.read_entries(path)[0]
            self.assertEqual(settled, 1)
            self.assertEqual(saved["pregame"], original_pregame)
            self.assertEqual(saved["settlement"]["result"], "WIN")
            self.assertEqual(saved["settlement"]["pnl_units"], 1.0)

    def test_paper_history_appends_instead_of_replacing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.json"
            payload = self.payload(); payload["prelive_decision"] = self.decision(0.1)
            first = paper_trading.build_entries(payload)
            paper_trading.append_entries(first, path)
            second = copy.deepcopy(first[0]); second["key"] = "atp:88:moneyline:a:na"
            second["pregame"]["match_id"] = 88
            paper_trading.append_entries([second], path)
            self.assertEqual(len(paper_trading.read_entries(path)), 2)

    def test_moneyline_and_handicap_are_separate_entries(self):
        payload = self.payload()
        decision = self.decision(0.1)
        handicap = copy.deepcopy(decision["market"])
        handicap.update({"market_type": "Handicap", "market": "Handicap Alpha -2.5", "line": -2.5})
        decision["paper_markets"].append(handicap)
        payload["prelive_decision"] = decision
        entries = paper_trading.build_entries(payload)
        self.assertEqual({entry["pregame"]["market_type"] for entry in entries}, {"Moneyline", "Handicap"})
        self.assertEqual(len({entry["key"] for entry in entries}), 2)

    def test_telegram_states_colours_and_counts(self):
        payloads = []
        for state, edge in ((EDGE_POSITIVE, 0.1), (EDGE_NEGATIVE, -0.1), (EDGE_ZERO, 0.0)):
            payload = self.payload(); payload["prelive_decision"] = self.decision(edge)
            self.assertEqual(payload["prelive_decision"]["state"], state)
            payloads.append(payload)
        null_payload = self.payload()
        null_payload["prelive_decision"] = {"state": REPORT_NULL, "reason": "sem dados"}
        payloads.append(null_payload)
        unavailable = self.payload()
        unavailable["prelive_decision"] = {"state": PRICING_UNAVAILABLE, "reason": "sem preço fresco"}
        payloads.append(unavailable)
        self.assertEqual([_telegram_decision_row(item)[1] for item in payloads], ["🟢", "🔴", "⚪", "⚫", "🟡"])
        self.assertEqual(telegram_state_counts(payloads), {
            EDGE_POSITIVE: 1, EDGE_POSITIVE_COVERAGE_INSUFFICIENT: 0,
            EDGE_NEGATIVE: 1, EDGE_ZERO: 1, PRICING_UNAVAILABLE: 1, REPORT_NULL: 1,
        })


if __name__ == "__main__":
    unittest.main()
