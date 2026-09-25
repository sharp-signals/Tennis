"""Regressões do CHANGE-053 para Challenger 125 em modo EXPERIMENT."""

from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src import (
    config,
    fetch_data,
    green_strong_validation,
    main,
    market_integrity,
    paper_trading,
    pricing,
    report_html,
    tournament_policy,
)
from src.prelive_decision import build_decision


class Challenger125ExperimentTests(unittest.TestCase):
    @staticmethod
    def _divergence():
        return {
            "indice_evidencia_a": 100,
            "indice_evidencia_b": 0,
            "indice_favorece": "Alpha One",
            "tipo": "direcao",
            "classificacao": {"nivel": 3},
            "n_fatores": 4,
            "intensidade_nivel": 3,
            "fatores_status": {
                f"factor-{index}": {
                    "disponivel": True,
                    "peso_efetivo": 5,
                    "peso_base_configurado": 5,
                }
                for index in range(4)
            },
        }

    @staticmethod
    def _base_payload(tier="Challenger 125"):
        tour = "atp"
        payload = {
            "match_id": 701,
            "tour": tour,
            "tier": tier,
            "tournament_id": 99001,
            "tournament": "Porto Open",
            "surface": "Hard",
            "player_a": "Alpha One",
            "player_b": "Beta Two",
            "player_a_id": 1,
            "player_b_id": 2,
            "commence_time_utc": "2026-09-25T15:00:00+00:00",
            "snapshot_key": "test:701",
            "report_id": "report-701",
            "analyzed_at_utc": "2026-09-25T10:00:00+00:00",
            "report_assessment": {
                "report_null": False,
                "coverage": {
                    "weighted_ratio": 1.0,
                    "weighted_pct": 100.0,
                    "status": "suficiente",
                },
            },
            "market_odds_decimal": {"Alpha One": 2.1, "Beta Two": 1.8},
        }
        payload.update(market_integrity.operational_contract_metadata(payload["analyzed_at_utc"]))
        payload["odds_operational_pricing_eligible"] = True
        return payload

    def _priced_payload(self, tier="Challenger 125"):
        payload = self._base_payload(tier)
        divergence = self._divergence()
        payload["divergencia"] = divergence
        payload["pricing"] = pricing.estimate_market_residual_pricing(payload, divergence)
        self.assertTrue(payload["pricing"]["available"])
        payload["prelive_decision"] = build_decision(
            payload,
            divergence,
            payload["pricing"],
            payload["report_assessment"],
        )
        return payload

    def test_only_challenger_125_enters_coverage(self):
        self.assertIn("Challenger 125", config.ALLOWED_TOURNAMENT_TIERS)
        self.assertEqual(
            config.EXPERIMENTAL_REPORT_ONLY_TIERS,
            frozenset({"Challenger 125"}),
        )
        for tier in (
            "Challenger 100", "Challenger 75", "Challenger 50",
            "Future", "ITF", "Tier desconhecido",
        ):
            with self.subTest(tier=tier):
                self.assertNotIn(tier, config.ALLOWED_TOURNAMENT_TIERS)

    def test_filter_accepts_challenger_125_and_rejects_lower_circuits(self):
        tiers = {
            1: "Challenger 125",
            2: "Challenger 100",
            3: "Challenger 75",
            4: "Challenger 50",
            5: "Future",
            6: "ITF",
            7: "Unknown",
        }
        matches = [
            {"id": tournament_id, "tournamentId": tournament_id, "_tour": "atp"}
            for tournament_id in tiers
        ]
        with patch.object(
            main.fetch_data,
            "get_tournament_info",
            side_effect=lambda tournament_id, _tour: {
                "name": f"Event {tournament_id}",
                "surface": "Hard",
                "tier": tiers[tournament_id],
            },
        ):
            actual = main._filter_and_enrich_with_tournament_info(matches)
        self.assertEqual([item["tournamentId"] for item in actual], [1])
        self.assertEqual(actual[0]["tier"], "Challenger 125")

    def test_factual_report_marks_challenger_as_experimental(self):
        payload = self._base_payload()
        payload["market_odds_decimal"] = None
        payload["odds_operational_pricing_eligible"] = False
        payload["pricing"] = {"available": False, "reason": "recent_odds_unavailable"}
        payload["prelive_decision"] = {
            "state": "PRICING_UNAVAILABLE",
            "paper_eligible": False,
            "paper_markets": [],
            "coverage": {"weighted_pct": 0, "status": "insuficiente"},
            "reason": "recent_odds_unavailable",
        }
        tournament_policy.apply_experimental_paper_gate(payload)
        rendered = report_html.build_report_html(
            payload,
            {"flag": "🟡", "summary_line": "Análise factual", "key_points": []},
        )
        self.assertIn("Challenger 125 · EXPERIMENTAL", rendered)
        self.assertIn("não é promovido para PAPER ou GREEN", rendered)

    def test_without_operational_quote_pricing_is_unavailable(self):
        payload = self._base_payload()
        payload["odds_operational_pricing_eligible"] = False
        priced = pricing.estimate_market_residual_pricing(payload, self._divergence())
        self.assertFalse(priced["available"])
        self.assertEqual(priced["reason"], "operational_market_quote_ineligible")

    def test_valid_quote_allows_pricing_but_experiment_blocks_paper(self):
        payload = self._priced_payload()
        self.assertTrue(payload["prelive_decision"]["paper_eligible"])
        would_be = tournament_policy.apply_experimental_paper_gate(payload)
        decision = payload["prelive_decision"]
        self.assertTrue(would_be)
        self.assertEqual(decision["state"], tournament_policy.EXPERIMENTAL_EDGE_STATE)
        self.assertFalse(decision["paper_eligible"])
        self.assertEqual(decision["paper_markets"], [])
        self.assertEqual(
            decision["experimental_tier_gate"]["reason_code"],
            config.EXPERIMENTAL_TIER_PAPER_REASON_CODE,
        )
        self.assertEqual(paper_trading.build_entries(payload), [])

    def test_paper_defence_blocks_even_if_caller_bypasses_decision_gate(self):
        payload = self._priced_payload()
        self.assertTrue(payload["prelive_decision"]["paper_eligible"])
        self.assertEqual(paper_trading.build_entries(payload), [])

    def test_embedded_upcoming_and_wrong_contract_stay_fail_closed(self):
        embedded = self._base_payload()
        embedded.update({
            "odds_source": "rapidapi_extend_upcoming",
            "odds_operational_pricing_eligible": False,
        })
        self.assertFalse(
            pricing.estimate_market_residual_pricing(
                embedded, self._divergence()
            )["available"]
        )

        wrong = self._base_payload()
        wrong["odds_source_contract_fingerprint"] = "wrong"
        wrong["pricing"] = pricing.estimate_market_residual_pricing(
            wrong, self._divergence()
        )
        self.assertFalse(wrong["pricing"]["available"])
        wrong["prelive_decision"] = {
            "paper_eligible": True,
            "paper_markets": [{"market_type": "Moneyline", "side": "a"}],
        }
        self.assertEqual(paper_trading.build_entries(wrong), [])

    def test_experimental_candidate_is_ineligible_for_green_with_explicit_reason(self):
        payload = self._priced_payload()
        tournament_policy.apply_experimental_paper_gate(payload)
        membership = green_strong_validation.classify_snapshot(
            payload,
            snapshot_key="test:701",
            classified_at_utc=payload["analyzed_at_utc"],
        )
        self.assertFalse(membership["eligible"])
        self.assertIn(
            config.EXPERIMENTAL_TIER_PAPER_REASON_CODE,
            membership["reason_codes"],
        )

    def test_main_tour_and_250_behaviour_remain_unchanged(self):
        for tier in ("ATP 500", "ATP 250", "WTA 250"):
            with self.subTest(tier=tier):
                payload = self._priced_payload(tier)
                original = dict(payload["prelive_decision"])
                self.assertFalse(tournament_policy.apply_experimental_paper_gate(payload))
                self.assertEqual(payload["prelive_decision"], original)
                self.assertEqual(len(paper_trading.build_entries(payload)), 1)

    def test_gate_preserves_identity_v2_and_legacy_payloads_without_tier(self):
        payload = self._priced_payload()
        payload.update({
            "identity_schema_version": 2,
            "canonical_match_instance_id": "match-instance-1",
            "identity_status": "CANONICAL_STRONG",
        })
        tournament_policy.apply_experimental_paper_gate(payload)
        self.assertEqual(payload["canonical_match_instance_id"], "match-instance-1")
        self.assertEqual(payload["identity_status"], "CANONICAL_STRONG")

        historical = {"prelive_decision": {"state": "EDGE_POSITIVE", "paper_eligible": True}}
        before = {"state": "EDGE_POSITIVE", "paper_eligible": True}
        self.assertFalse(tournament_policy.apply_experimental_paper_gate(historical))
        self.assertEqual(historical["prelive_decision"], before)

    def test_existing_challenger_history_resolves_current_factors_without_imputation(self):
        history = pd.DataFrame([
            {
                "winner_name": "Alpha One", "loser_name": "Beta Two",
                "tourney_date": 20260920, "surface": "Hard", "score": "6-4 6-4",
                "tournament_level": "Challenger 125",
            },
            {
                "winner_name": "Gamma Three", "loser_name": "Alpha One",
                "tourney_date": 20260922, "surface": "Hard", "score": "7-6 6-3",
                "tournament_level": "Challenger 125",
            },
        ])
        match_date = datetime(2026, 9, 25, tzinfo=timezone.utc)
        self.assertIsNotNone(fetch_data.compute_recent_form(history, "Alpha One", 10))
        self.assertIsNotNone(fetch_data.compute_fatigue(history, "Alpha One", match_date))
        self.assertIsNotNone(fetch_data.compute_h2h(history, "Alpha One", "Beta Two", "Hard"))
        self.assertIsNotNone(fetch_data.compute_surface_stats(history, "Alpha One"))
        self.assertIsNone(fetch_data.compute_recent_form(history, "Missing Player", 10))

    def test_rapidapi_telemetry_attributes_calls_without_changing_quota(self):
        response = Mock(status_code=200, headers={})
        with patch.dict(fetch_data._RAPIDAPI_ENDPOINT_CALLS, {}, clear=True), patch.dict(
            fetch_data._RAPIDAPI_CONTEXT_ENDPOINT_CALLS, {}, clear=True
        ), patch.object(fetch_data, "_reserve_rapidapi_call"), patch.object(
            fetch_data, "RAPIDAPI_MIN_INTERVAL", 0
        ), patch.object(fetch_data.requests, "get", return_value=response):
            with fetch_data.rapidapi_call_context("Challenger 125"):
                fetch_data._rapidapi_get(
                    "https://example.test/tennis/v2/atp/player/past-matches/1"
                )
            metrics = fetch_data.get_rapidapi_call_context_metrics()
        self.assertEqual(metrics["Challenger 125"]["calls"], 1)
        self.assertEqual(
            metrics["Challenger 125"]["by_endpoint_family"],
            {"statistical_enrichment": 1},
        )
        self.assertEqual(config.RAPIDAPI_MAX_CALLS_PER_RUN, 2250)
        self.assertEqual(config.RAPIDAPI_MAX_CALLS_PER_DAY, 4500)
        self.assertEqual(config.RAPIDAPI_OPERATIONAL_RESERVE, 1500)

    def test_run_telemetry_counts_pricing_and_would_be_paper_without_persisting(self):
        payload = self._priced_payload()
        payload.update({
            "report_data_status": "DEGRADED",
            "data_coverage": {
                "recent_form": {
                    "a": {"status": "AVAILABLE", "reason": None},
                    "b": {"status": "UNAVAILABLE", "reason": "recent_form_unavailable"},
                },
            },
            "odds_bookmaker": "Book A",
            "odds_market_integrity": {"status": "PASS"},
        })
        tournament_policy.apply_experimental_paper_gate(payload)
        candidate = {
            "tier": "Challenger 125",
            "tournamentId": 99001,
            "_rapidapi_event_integrity": {"status": "verified"},
        }
        with patch.object(
            fetch_data,
            "get_rapidapi_call_context_metrics",
            return_value={
                "Challenger 125": {
                    "calls": 6,
                    "by_endpoint_family": {"statistical_enrichment": 5, "market_odds": 1},
                },
                "ATP 250": {"calls": 3, "by_endpoint_family": {}},
                "shared": {"calls": 2, "by_endpoint_family": {}},
            },
        ), patch.object(fetch_data, "get_rapidapi_call_count", return_value=11), patch.object(
            fetch_data, "get_rapidapi_recorded_today_calls", return_value=100
        ):
            metrics = main._experimental_tier_metrics(
                [candidate], [candidate], [(payload, {})]
            )
        self.assertEqual(metrics["discovery"]["games_processed"], 1)
        self.assertEqual(metrics["data"]["reports"], {"complete": 0, "degraded": 1})
        self.assertEqual(metrics["market"]["recent_odds_available"], 1)
        self.assertEqual(metrics["pricing"], {"available": 1, "unavailable": 0})
        self.assertEqual(metrics["paper"]["would_be_candidates"], 1)
        self.assertEqual(metrics["paper"]["persisted"], 0)
        self.assertEqual(
            metrics["paper"]["blocked_by_reason"],
            {config.EXPERIMENTAL_TIER_PAPER_REASON_CODE: 1},
        )
        self.assertEqual(metrics["cost"]["challenger_125_attributed_calls"], 6)
        self.assertEqual(metrics["cost"]["main_tour_attributed_calls"], 3)


if __name__ == "__main__":
    unittest.main()
