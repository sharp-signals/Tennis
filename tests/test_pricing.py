import json
import tempfile
import unittest
from pathlib import Path

from src import calibration_store, report_html
from src.pricing import (
    MODEL_VERSION,
    apply_logit_residual,
    calculate_expected_edge,
    de_vig_market_probabilities,
    estimate_market_residual_pricing,
)


class MarketResidualPricingTests(unittest.TestCase):
    def _payload(self, odd_a=2.10, odd_b=1.90):
        return {
            "match_id": "pricing-1",
            "tour": "atp",
            "player_a": "Jogador A",
            "player_b": "Jogador B",
            "player_a_id": 1,
            "player_b_id": 2,
            "commence_time_utc": "2026-08-27T12:00:00+00:00",
            "market_odds_decimal": {"Jogador A": odd_a, "Jogador B": odd_b},
        }

    def _divergence(self, index_a=80, factors=4, intensity=3, weight=5.0):
        return {
            "indice_evidencia_a": index_a,
            "indice_evidencia_b": 100 - index_a,
            "n_fatores": factors,
            "intensidade_nivel": intensity,
            "fatores_status": {
                f"fator_{number}": {"peso_efetivo": weight}
                for number in range(factors)
            },
        }

    def test_de_vig_market_probabilities_sum_to_one(self):
        market_a, market_b, overround = de_vig_market_probabilities(2.40, 1.60)
        self.assertAlmostEqual(market_a + market_b, 1.0, places=12)
        self.assertGreater(overround, 0)

    def test_no_evidence_adjustment_keeps_market_baseline(self):
        pricing = estimate_market_residual_pricing(
            self._payload(), self._divergence(index_a=53, factors=4, intensity=0)
        )
        self.assertAlmostEqual(
            pricing["sharp_estimate_a"], pricing["market_probability_a"], places=12
        )
        self.assertEqual(pricing["residual_logit"], 0.0)

    def test_positive_residual_increases_a_and_decreases_b(self):
        pricing = estimate_market_residual_pricing(self._payload(), self._divergence(80))
        self.assertGreater(pricing["sharp_estimate_a"], pricing["market_probability_a"])
        self.assertLess(pricing["sharp_estimate_b"], pricing["market_probability_b"])

    def test_negative_residual_decreases_a(self):
        pricing = estimate_market_residual_pricing(self._payload(), self._divergence(20))
        self.assertLess(pricing["sharp_estimate_a"], pricing["market_probability_a"])

    def test_probability_coherence_and_fair_odds(self):
        pricing = estimate_market_residual_pricing(self._payload(), self._divergence(80))
        self.assertAlmostEqual(pricing["sharp_estimate_a"] + pricing["sharp_estimate_b"], 1.0)
        self.assertAlmostEqual(pricing["fair_odd_a"], 1.0 / pricing["sharp_estimate_a"])
        self.assertAlmostEqual(pricing["fair_odd_b"], 1.0 / pricing["sharp_estimate_b"])

    def test_expected_edge_explicit_example(self):
        self.assertAlmostEqual(calculate_expected_edge(0.442, 2.44), 0.07848, places=5)
        transformed = apply_logit_residual(0.41, 0.1309163)
        self.assertAlmostEqual(transformed, 0.442, places=3)

    def test_weak_single_factor_is_attenuated_and_not_promoted(self):
        pricing = estimate_market_residual_pricing(
            self._payload(2.0, 2.0), self._divergence(100, factors=1, intensity=3, weight=18)
        )
        self.assertLess(pricing["residual_logit"], pricing["parameters"]["max_logit_shift"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertIsNone(pricing["candidate_side"])

    def test_valid_edge_is_promoted_only_after_quality_gates(self):
        pricing = estimate_market_residual_pricing(
            self._payload(), self._divergence(100, factors=4, intensity=3, weight=5)
        )
        self.assertTrue(pricing["quality_gate_passed"])
        self.assertTrue(pricing["candidate"])
        self.assertEqual(pricing["candidate_side"], "a")
        self.assertEqual(pricing["candidate_status"], "experimental_edge")

    def test_serious_data_quality_failure_blocks_promotion_but_keeps_numbers_visible(self):
        payload = self._payload()
        payload["data_quality"] = {
            "issues": [{"severity": "critical", "type": "corrupt_history"}]
        }
        pricing = estimate_market_residual_pricing(
            payload, self._divergence(100, factors=4, intensity=3, weight=5)
        )
        self.assertTrue(pricing["available"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertIsNone(pricing["candidate_side"])
        self.assertEqual(
            pricing["candidate_status"], "edge_not_promoted_insufficient_evidence"
        )

    def test_identity_warning_reduces_quality_and_blocks_candidate(self):
        payload = self._payload()
        payload["data_quality"] = {
            "issues": [{"severity": "warning", "type": "name_resolution"}]
        }
        pricing = estimate_market_residual_pricing(
            payload, self._divergence(100, factors=4, intensity=3, weight=5)
        )
        self.assertEqual(pricing["evidence_quality"]["source_reliability"], 0.5)
        self.assertFalse(pricing["evidence_quality"]["source_gate_passed"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertIsNone(pricing["candidate_side"])

    def test_insufficient_factor_family_coverage_blocks_candidate(self):
        divergence = self._divergence(100, factors=4, intensity=3, weight=5)
        divergence["evidence_coverage"] = {
            "coverage_quality": 2 / 3,
            "source_reliability": 1.0,
            "pricing_eligible": False,
        }
        pricing = estimate_market_residual_pricing(self._payload(), divergence)
        self.assertAlmostEqual(pricing["evidence_quality"]["coverage_quality"], 2 / 3, places=6)
        self.assertFalse(pricing["evidence_quality"]["coverage_gate_passed"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertIsNone(pricing["candidate_side"])

    def test_missing_odds_fails_safely(self):
        payload = self._payload()
        payload["market_odds_decimal"] = {}
        pricing = estimate_market_residual_pricing(payload, self._divergence())
        self.assertFalse(pricing["available"])
        self.assertFalse(pricing["candidate"])
        self.assertEqual(pricing["reason"], "missing_or_invalid_two_way_moneyline")
        self.assertNotIn("sharp_estimate_a", pricing)

    def test_snapshot_freezes_pricing_and_duplicate_cannot_overwrite_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            payload = self._payload()
            payload["pricing"] = estimate_market_residual_pricing(payload, self._divergence(80))
            first = calibration_store.build_snapshot(
                payload, analyzed_at_utc="2026-08-26T08:00:00+00:00"
            )
            changed = dict(payload)
            changed["pricing"] = estimate_market_residual_pricing(changed, self._divergence(20))
            second = calibration_store.build_snapshot(
                changed, analyzed_at_utc="2026-08-26T09:00:00+00:00"
            )
            self.assertEqual(calibration_store.upsert_snapshots([first], path), 1)
            self.assertEqual(calibration_store.upsert_snapshots([second], path), 0)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["pricing"]["model_version"], MODEL_VERSION)
            self.assertEqual(
                saved["pricing"]["configuration_fingerprint"],
                first["pricing"]["configuration_fingerprint"],
            )
            self.assertEqual(saved["pricing"]["sharp_estimate_a"], first["pricing"]["sharp_estimate_a"])

    def test_report_contract_contains_visible_pricing_fields_and_warning(self):
        payload = self._payload()
        payload["features"] = {
            "piso": {"lider": "Jogador A", "diff": 18, "amostra_a": 100, "amostra_b": 100},
            "ranking": {"lider": "Jogador A", "diff": 30},
        }
        payload["divergencia"] = self._divergence(80)
        payload["pricing"] = estimate_market_residual_pricing(payload, payload["divergencia"])
        html = report_html.build_report_html_v2(
            payload, {}, lambda _: payload["divergencia"]
        )
        for expected in (
            "Market probability", "Sharp estimate", "Fair odd", "Market odd",
            "Expected edge", "EXPERIMENTAL", "Estimativa experimental em desenvolvimento",
            "Cobertura", "Fiabilidade das fontes",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("Veredicto de mercado", html)


if __name__ == "__main__":
    unittest.main()
