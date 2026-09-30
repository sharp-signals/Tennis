"""Regressões do CHANGE-052 para cobertura global ATP/WTA 250."""

import unittest
from unittest.mock import patch

from src import config, fetch_data, main, market_integrity, paper_trading, pricing


class Tournament250CoverageTests(unittest.TestCase):
    def test_main_tour_250_tiers_are_allowed_and_winston_needs_no_override(self):
        self.assertIn("ATP 250", config.ALLOWED_TOURNAMENT_TIERS)
        self.assertIn("WTA 250", config.ALLOWED_TOURNAMENT_TIERS)
        self.assertNotIn(21348, config.FORCED_TOURNAMENT_IDS)
        self.assertEqual(config.FORCED_TOURNAMENT_IDS, {})

    def test_chengdu_and_hangzhou_are_discovered_without_override(self):
        events = [
            {"type": "atp", "tournament": {"id": 21351, "name": "Chengdu Open"}},
            {"type": "atp", "tournament": {"id": 21352, "name": "Hangzhou Open"}},
        ]
        info = {
            21351: {"name": "Chengdu Open", "tier": "ATP 250"},
            21352: {"name": "Hangzhou Open", "tier": "ATP 250"},
        }
        with patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=events), \
                patch.object(fetch_data, "FORCED_TOURNAMENT_IDS", {}), \
                patch.object(fetch_data, "TRACKED_TOURNAMENT_IDS", {}), \
                patch.object(
                    fetch_data,
                    "get_tournament_info",
                    side_effect=lambda tournament_id, _tour: info[tournament_id],
                ):
            actual = fetch_data.discover_tracked_tournaments()

        self.assertEqual(actual, {21351: "atp", 21352: "atp"})

    def test_winston_salem_is_accepted_by_tier_without_override(self):
        matches = [{"id": 1, "tournamentId": 21348, "_tour": "atp"}]
        info = {
            "name": "Winston-Salem Open",
            "surface": "Hard",
            "tier": "ATP 250",
        }
        with patch.object(main, "FORCED_TOURNAMENT_IDS", {}), patch.object(
            main.fetch_data, "get_tournament_info", return_value=info
        ):
            actual = main._filter_and_enrich_with_tournament_info(matches)

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["tier"], "ATP 250")

    def test_lower_circuits_and_unknown_tiers_remain_fail_closed(self):
        matches = [
            {"id": 1, "tournamentId": 1, "_tour": "atp"},
            {"id": 2, "tournamentId": 2, "_tour": "atp"},
            {"id": 3, "tournamentId": 3, "_tour": "wta"},
            {"id": 4, "tournamentId": 4, "_tour": "wta"},
        ]
        info = {
            1: {"name": "Challenger", "tier": "Challenger"},
            2: {"name": "Future", "tier": "Future"},
            3: {"name": "ITF", "tier": "ITF"},
            4: {"name": "Unknown", "tier": "Tier desconhecido"},
        }
        with patch.object(main, "FORCED_TOURNAMENT_IDS", {}), patch.object(
            main.fetch_data,
            "get_tournament_info",
            side_effect=lambda tournament_id, _tour: info[tournament_id],
        ):
            actual = main._filter_and_enrich_with_tournament_info(matches)

        self.assertEqual(actual, [])

    def test_generic_forced_tournament_mechanism_still_works(self):
        matches = [{"id": 1, "tournamentId": 99999, "_tour": "wta"}]
        info = {"name": "Exceção sintética", "tier": "Tier Experimental"}
        with patch.object(main, "FORCED_TOURNAMENT_IDS", {99999: "wta"}), patch.object(
            main.fetch_data, "get_tournament_info", return_value=info
        ):
            actual = main._filter_and_enrich_with_tournament_info(matches)

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["tournament_name"], "Exceção sintética")

    @staticmethod
    def _divergence():
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

    @staticmethod
    def _base_payload(tier: str):
        return {
            "match_id": 501,
            "tour": "atp" if tier.startswith("ATP") else "wta",
            "tier": tier,
            "tournament_id": 21351 if tier.startswith("ATP") else 16751,
            "player_a": "Alpha One",
            "player_b": "Beta Two",
            "player_a_id": 1,
            "player_b_id": 2,
            "commence_time_utc": "2026-09-24T15:00:00+00:00",
            "snapshot_key": "test:501",
            "report_id": "report-501",
            "analyzed_at_utc": "2026-09-24T10:00:00+00:00",
            "report_assessment": {"report_null": False},
        }

    def test_250_without_operational_quote_cannot_create_pricing_or_paper(self):
        for tier in ("ATP 250", "WTA 250"):
            with self.subTest(tier=tier):
                payload = self._base_payload(tier)
                payload.update({
                    "market_odds_decimal": {"Alpha One": 2.1, "Beta Two": 1.8},
                    "odds_operational_pricing_eligible": False,
                })
                priced = pricing.estimate_market_residual_pricing(
                    payload, self._divergence()
                )
                self.assertFalse(priced["available"])
                self.assertEqual(
                    priced["reason"], "operational_market_quote_ineligible"
                )
                payload["pricing"] = priced
                payload["prelive_decision"] = {
                    "paper_eligible": True,
                    "paper_markets": [{"market_type": "Moneyline", "side": "a"}],
                }
                self.assertEqual(paper_trading.build_entries(payload), [])

    def test_250_operational_quote_remains_bound_to_change_050_contract(self):
        payload = self._base_payload("ATP 250")
        contract = market_integrity.operational_contract_metadata(
            payload["analyzed_at_utc"]
        )
        payload.update({
            "market_odds_decimal": {"Alpha One": 2.1, "Beta Two": 1.8},
            "odds_operational_pricing_eligible": True,
            "odds_source_contract_version": contract["odds_source_contract_version"],
            "odds_source_contract_fingerprint": contract[
                "odds_source_contract_fingerprint"
            ],
            "odds_source_contract": contract["odds_source_contract"],
            "odds_contract_activation": contract["odds_contract_activation"],
        })
        payload["pricing"] = pricing.estimate_market_residual_pricing(
            payload, self._divergence()
        )
        self.assertTrue(payload["pricing"]["available"])
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
        self.assertEqual(len(paper_trading.build_entries(payload)), 1)

        payload["pricing"]["odds_source_contract_fingerprint"] = "wrong"
        self.assertEqual(paper_trading.build_entries(payload), [])


if __name__ == "__main__":
    unittest.main()
