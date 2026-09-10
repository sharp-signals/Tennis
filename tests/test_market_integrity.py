import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src import fetch_data, market_integrity, paper_trading, prelive_decision, pricing


class MarketIntegrityGateTests(unittest.TestCase):
    def test_exact_incident_rejects_sentinels_and_selects_pinnacle(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Bet365", "odd_a": 1.001, "odd_b": 101},
            {"bookmaker": "DraftKings", "odd_a": 1.01, "odd_b": 31},
            {"bookmaker": "MelBet", "odd_a": 1.001, "odd_b": 18},
            {"bookmaker": "Pinnacle", "odd_a": 1.543, "odd_b": 2.56},
            {"bookmaker": "Marathonbet", "odd_a": 1.53, "odd_b": 2.53},
        ])
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["selected"]["bookmaker"], "Pinnacle")
        self.assertEqual((result["selected"]["odd_a"], result["selected"]["odd_b"]), (1.543, 2.56))
        self.assertEqual(
            [item["reason_code"] for item in result["rejected_candidates"]],
            [market_integrity.MARKET_BOUNDARY_SENTINEL] * 3,
        )

    def test_only_boundary_sentinel_is_unavailable(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Bet365", "odd_a": 1.001, "odd_b": 101},
        ])
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["reason_code"], market_integrity.MARKET_BOUNDARY_SENTINEL)
        self.assertIsNone(result["selected"])

    def test_two_disagreeing_bookmakers_fail_closed(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Book A", "odd_a": 1.25, "odd_b": 4.5},
            {"bookmaker": "Book B", "odd_a": 2.2, "odd_b": 1.7},
        ])
        self.assertEqual(result["reason_code"], market_integrity.CROSS_BOOK_DISPERSION)
        self.assertIsNone(result["selected"])

    def test_two_coherent_bookmakers_allow_operational_price(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Book A", "odd_a": 1.70, "odd_b": 2.20},
            {"bookmaker": "Book B", "odd_a": 1.72, "odd_b": 2.18},
        ])
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["coherent_bookmaker_count"], 2)

    def test_three_or_more_reject_cross_book_outlier_before_selection(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Book A", "odd_a": 1.60, "odd_b": 2.45},
            {"bookmaker": "Book B", "odd_a": 1.62, "odd_b": 2.40},
            {"bookmaker": "Book C", "odd_a": 1.58, "odd_b": 2.50},
            {"bookmaker": "Outlier", "odd_a": 4.00, "odd_b": 1.30},
        ])
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertIn(
            "Outlier",
            [item["bookmaker"] for item in result["rejected_candidates"] if item["reason_code"] == "CROSS_BOOK_OUTLIER"],
        )

    def test_surviving_market_with_wide_dispersion_is_unavailable(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Book A", "odd_a": 2.7027, "odd_b": 1.5873},
            {"bookmaker": "Book B", "odd_a": 2.00, "odd_b": 2.00},
            {"bookmaker": "Book C", "odd_a": 1.5873, "odd_b": 2.7027},
        ])
        self.assertEqual(result["reason_code"], market_integrity.CROSS_BOOK_DISPERSION)
        self.assertIsNone(result["selected"])

    def test_one_bookmaker_is_observation_only(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Book A", "odd_a": 1.70, "odd_b": 2.20},
        ])
        self.assertEqual(result["reason_code"], market_integrity.INSUFFICIENT_BOOKMAKER_CONSENSUS)
        self.assertEqual(result["valid_candidates"][0]["integrity_status"], "OBSERVATION_ONLY")
        self.assertFalse(result["valid_candidates"][0]["operational_pricing_eligible"])

    def test_non_finite_incomplete_and_below_one_are_rejected(self):
        for candidate, reason in (
            ({"bookmaker": "A", "odd_a": None, "odd_b": 2}, market_integrity.MONEYLINE_INCOMPLETE),
            ({"bookmaker": "A", "odd_a": float("inf"), "odd_b": 2}, market_integrity.MONEYLINE_NON_FINITE),
            ({"bookmaker": "A", "odd_a": 1.0, "odd_b": 2}, market_integrity.MONEYLINE_ODDS_AT_OR_BELOW_ONE),
        ):
            self.assertEqual(market_integrity.validate_moneyline_candidate(candidate)["reason_code"], reason)

    def test_fetch_boundary_persists_reason_and_creates_no_operational_odds(self):
        match = {"player1": {"name": "Karen Khachanov"}, "player2": {"name": "Alexander Blockx"}}
        event = {
            "valid": True, "event_id": "3913010",
            "participant1": "Karen Khachanov", "participant2": "Alexander Blockx",
        }

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"result": {"Full Time Result": {
                    "Bet365": {"od1": "1.001", "od2": "101", "addTime": str(datetime.now(timezone.utc).timestamp())},
                }}}

        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=event), \
                patch.object(fetch_data, "_rapidapi_get", return_value=Response()), \
                patch.dict(fetch_data._RAPIDAPI_FRESH_ODDS_CACHE, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        self.assertIsNone(odds)
        self.assertEqual(provenance["unavailable_reason"], market_integrity.MARKET_BOUNDARY_SENTINEL)
        self.assertEqual(provenance["market_quotes"], [])

        payload = {
            "market_odds_decimal": odds,
            "report_assessment": {"report_null": False},
        }
        priced = pricing.estimate_market_residual_pricing(payload, None)
        priced["reason"] = provenance["unavailable_reason"]
        decision = prelive_decision.build_decision(
            payload, None, priced,
            {"report_null": False, "coverage": {"weighted_ratio": 1.0}},
        )
        self.assertFalse(priced["available"])
        self.assertEqual(decision["state"], prelive_decision.PRICING_UNAVAILABLE)
        self.assertFalse(decision["paper_eligible"])
        self.assertEqual(paper_trading.build_entries({"prelive_decision": decision}), [])

    def test_fetch_exact_incident_selects_pinnacle_deterministically(self):
        match = {"player1": {"name": "Karen Khachanov"}, "player2": {"name": "Alexander Blockx"}}
        event = {
            "valid": True, "event_id": "3913010",
            "participant1": "Karen Khachanov", "participant2": "Alexander Blockx",
        }

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"result": {"Full Time Result": {
                    "Bet365": {"od1": "1.001", "od2": "101"},
                    "DraftKings": {"od1": "1.01", "od2": "31"},
                    "MelBet": {"od1": "1.001", "od2": "18"},
                    "Pinnacle": {"od1": "1.543", "od2": "2.56"},
                    "Marathonbet": {"od1": "1.53", "od2": "2.53"},
                }}}

        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=event), \
                patch.object(fetch_data, "_rapidapi_get", return_value=Response()), \
                patch.dict(fetch_data._RAPIDAPI_FRESH_ODDS_CACHE, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Karen Khachanov": 1.543, "Alexander Blockx": 2.56})
        self.assertEqual(provenance["bookmaker"], "Pinnacle")
        self.assertEqual(provenance["market_integrity"]["coherent_bookmaker_count"], 2)
        self.assertEqual(
            [item["reason_code"] for item in provenance["market_integrity"]["rejected_candidates"]],
            [market_integrity.MARKET_BOUNDARY_SENTINEL] * 3,
        )

    def test_historical_exclusion_is_additive_and_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paper_path = root / "paper.json"
            exclusions_path = root / "exclusions.json"
            paper_path.write_text(json.dumps({
                "schema_version": 1,
                "entries": [
                    {"key": "atp:1241:moneyline:b:na", "pregame": {"market_type": "Moneyline"}},
                    {"key": "atp:2:moneyline:a:na", "pregame": {"market_type": "Moneyline"}},
                ],
            }), encoding="utf-8")
            exclusions_path.write_text(json.dumps({
                "schema_version": 1,
                "exclusions": [{
                    "paper_key": "atp:1241:moneyline:b:na", "snapshot_key": "atp:1241",
                    "reason_code": market_integrity.MARKET_BOUNDARY_SENTINEL,
                }],
            }), encoding="utf-8")
            history = paper_trading.compute_history(
                paper_path, root / "manual.json", exclusions_path,
            )
        self.assertEqual(history["PAPER"]["total_entries"], 1)
        self.assertEqual(history["excluded_data_quality_entries"], 1)
        self.assertEqual(history["data_quality_exclusions_by_reason"], {"MARKET_BOUNDARY_SENTINEL": 1})


if __name__ == "__main__":
    unittest.main()
