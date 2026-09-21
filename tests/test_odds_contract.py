import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import (
    calibration_store,
    fetch_data,
    main,
    market_integrity,
    market_ledger,
    paper_trading,
    pricing,
)


class OperationalOddsContractTests(unittest.TestCase):
    def match(self):
        return {
            "id": 501,
            "_tour": "atp",
            "date": "2026-09-22T15:00:00+00:00",
            "player1Id": 1,
            "player2Id": 2,
            "player1": {"id": 1, "name": "Alpha One"},
            "player2": {"id": 2, "name": "Beta Two"},
        }

    def provenance(self):
        captured = "2026-09-22T10:00:00+00:00"
        value = {
            "source": "RapidAPI Tennis API / recent-odds",
            "endpoint": "https://provider.test/event/recent-odds/get/501",
            "event_id": "501",
            "captured_at_utc": captured,
            "capture_kind": "rapidapi_response_observed_at_capture",
            "provider_timestamp": "2026-09-22T09:59:00+00:00",
            "provider_timestamp_status": "unreliable_for_freshness",
            "bookmaker": "Book A",
            "freshness_status": "OBSERVED_AT_CAPTURE_UNVERIFIED_AGE",
            "identity_mapping_status": "VERIFIED",
            "operational_pricing_eligible": True,
            "market_integrity": {
                "policy_version": market_integrity.POLICY_VERSION,
                "status": "AVAILABLE",
                "pricing_basis": "single_bookmaker",
            },
        }
        value.update(market_integrity.operational_contract_metadata(captured))
        return value

    def payload(self):
        provenance = self.provenance()
        contract = provenance["odds_source_contract"]
        return {
            "match_id": 501,
            "tour": "atp",
            "player_a": "Alpha One",
            "player_b": "Beta Two",
            "player_a_id": 1,
            "player_b_id": 2,
            "commence_time_utc": "2026-09-22T15:00:00+00:00",
            "market_odds_decimal": {"Alpha One": 2.1, "Beta Two": 1.8},
            "odds_operational_pricing_eligible": True,
            "odds_source_contract_version": provenance["odds_source_contract_version"],
            "odds_source_contract_fingerprint": provenance["odds_source_contract_fingerprint"],
            "odds_source_contract": contract,
            "odds_contract_activation": provenance["odds_contract_activation"],
            "odds_source": provenance["source"],
            "odds_endpoint": provenance["endpoint"],
            "odds_event_id": provenance["event_id"],
            "odds_captured_at_utc": provenance["captured_at_utc"],
            "odds_capture_kind": provenance["capture_kind"],
            "odds_provider_timestamp": provenance["provider_timestamp"],
            "odds_provider_timestamp_status": provenance["provider_timestamp_status"],
            "odds_freshness_status": provenance["freshness_status"],
            "odds_bookmaker": provenance["bookmaker"],
            "odds_market_integrity": provenance["market_integrity"],
            "report_assessment": {"report_null": False},
            "snapshot_key": "atp:501",
            "report_id": "report-501",
            "analyzed_at_utc": provenance["captured_at_utc"],
        }

    def divergence(self):
        return {
            "indice_evidencia_a": 100,
            "indice_evidencia_b": 0,
            "n_fatores": 4,
            "intensidade_nivel": 3,
            "fatores_status": {
                f"factor-{index}": {"peso_efetivo": 5}
                for index in range(4)
            },
        }

    def test_main_uses_safe_recent_path_and_keeps_embedded_shadow_only(self):
        source = inspect.getsource(main._build_match_payload)
        self.assertIn("fetch_rapidapi_recent_moneyline_with_provenance(match)", source)
        self.assertNotIn("fetch_rapidapi_moneyline_with_provenance(match)", source)
        self.assertIn("role=\"SHADOW_MONITOR\"", source)

    def test_embedded_is_observable_but_cannot_price_or_create_paper(self):
        match = self.match()
        key = fetch_data._odds_names_key("Alpha One", "Beta Two")
        embedded = {
            f"atp:{key}": {
                "n1": "Alpha One",
                "n2": "Beta Two",
                "p1_id": 1,
                "p2_id": 2,
                "o1": 2.1,
                "o2": 1.8,
                "captured_at_utc": "2026-09-22T10:00:00+00:00",
                "endpoint": "upcoming",
            }
        }
        with patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, embedded, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_embedded_moneyline_with_provenance(match)
        self.assertIs(provenance["operational_pricing_eligible"], False)
        payload = self.payload()
        payload.update({
            "market_odds_decimal": odds,
            "odds_operational_pricing_eligible": False,
            "odds_source_contract_version": None,
            "odds_source_contract_fingerprint": None,
        })
        result = pricing.estimate_market_residual_pricing(payload, self.divergence())
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "operational_market_quote_ineligible")
        payload["prelive_decision"] = {
            "paper_eligible": True,
            "paper_markets": [{"market_type": "Moneyline", "side": "a"}],
        }
        self.assertEqual(paper_trading.build_entries(payload), [])
        with tempfile.TemporaryDirectory() as tmp:
            recorded = market_ledger.record_market_batch_best_effort(
                match,
                odds,
                provenance,
                role="SHADOW_MONITOR",
                pipeline="PRELIVE_EMBEDDED_OBSERVATION",
                root=Path(tmp),
            )
            observation = market_ledger.read_observations(root=Path(tmp))[0]
        self.assertEqual(recorded["status"], "RECORDED")
        self.assertEqual(observation["source"]["role"], "SHADOW_MONITOR")
        self.assertFalse(observation["market_integrity"]["operational_pricing_eligible"])

    def test_missing_false_and_true_eligibility_are_fail_closed_then_open(self):
        payload = self.payload()
        payload.pop("odds_operational_pricing_eligible")
        self.assertFalse(pricing.estimate_market_residual_pricing(payload, self.divergence())["available"])
        payload["odds_operational_pricing_eligible"] = False
        self.assertFalse(pricing.estimate_market_residual_pricing(payload, self.divergence())["available"])
        payload["odds_operational_pricing_eligible"] = True
        self.assertTrue(pricing.estimate_market_residual_pricing(payload, self.divergence())["available"])

    def test_contract_version_matches_pricing_snapshot_paper_and_ledger(self):
        payload = self.payload()
        payload["pricing"] = pricing.estimate_market_residual_pricing(payload, self.divergence())
        payload["prelive_decision"] = {
            "paper_eligible": True,
            "paper_markets": [{
                "market_type": "Moneyline",
                "market": "Moneyline Alpha One",
                "side": "a",
                "player": "Alpha One",
                "odd": 2.1,
            }],
        }
        snapshot = calibration_store.build_snapshot(payload, {})
        paper = paper_trading.build_entries(payload)[0]
        observation = market_ledger.build_observation(
            self.match(),
            payload["market_odds_decimal"],
            self.provenance(),
            role="OPERATIONAL_PRICING",
            pipeline="PRELIVE",
        )
        versions = {
            payload["pricing"]["odds_source_contract_version"],
            snapshot["odds_provenance"]["odds_source_contract_version"],
            paper["pregame"]["odds_source_contract_version"],
            observation["source_contract"]["version"],
        }
        fingerprints = {
            payload["pricing"]["odds_source_contract_fingerprint"],
            snapshot["odds_provenance"]["odds_source_contract_fingerprint"],
            paper["pregame"]["odds_source_contract_fingerprint"],
            observation["source_contract"]["fingerprint"],
        }
        self.assertEqual(versions, {market_integrity.ODDS_SOURCE_CONTRACT_VERSION})
        self.assertEqual(fingerprints, {market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT})

    def test_cross_book_partial_sides_do_not_form_operational_moneyline(self):
        result = market_integrity.evaluate_moneyline_market([
            {"bookmaker": "Book A", "odd_a": 2.1, "odd_b": None},
            {"bookmaker": "Book B", "odd_a": None, "odd_b": 1.8},
        ])
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIsNone(result["selected"])

    def test_historical_payload_without_fingerprint_is_not_reclassified(self):
        historical = {
            "market_odds_decimal": {"Alpha One": 2.1, "Beta Two": 1.8},
            "odds_operational_pricing_eligible": True,
        }
        self.assertFalse(market_integrity.is_operational_pricing_payload(historical))


if __name__ == "__main__":
    unittest.main()
