import json
import tempfile
import unittest
from pathlib import Path

from src import calibration_store, market_integrity, report_html
from src.pricing import (
    MODEL_VERSION,
    PricingParameters,
    apply_logit_residual,
    calculate_expected_edge,
    de_vig_market_probabilities,
    evidence_probability,
    estimate_market_residual_pricing,
    market_prior_probability,
)


class MarketResidualPricingTests(unittest.TestCase):
    def _estimate(self, payload, divergence):
        """Exercita a matemática residual com uma escala explícita de teste."""
        return estimate_market_residual_pricing(
            payload,
            divergence,
            parameters=PricingParameters(
                atp_maximum_adjustment_pp=6.0,
                wta_maximum_adjustment_pp=6.0,
                challenger_maximum_adjustment_pp=3.0,
            ),
        )

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
            "odds_operational_pricing_eligible": True,
            "odds_source_contract_version": market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
            "odds_source_contract_fingerprint": market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
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

    def test_no_evidence_signal_keeps_market_prior(self):
        pricing = self._estimate(
            self._payload(), self._divergence(index_a=53, factors=4, intensity=0)
        )
        self.assertAlmostEqual(
            pricing["sharp_estimate_a"], pricing["market_probability_a"], places=12,
        )
        self.assertIsNone(pricing["residual_logit"])

    def test_production_default_uses_only_validated_zero_scale(self):
        pricing = estimate_market_residual_pricing(
            self._payload(), self._divergence(index_a=100, factors=8, intensity=3)
        )
        self.assertAlmostEqual(
            pricing["sharp_estimate_a"], pricing["market_probability_a"], places=12,
        )
        self.assertEqual(pricing["maximum_adjustment_pp"], 0.0)
        self.assertEqual(
            pricing["residual_calibration"]["status"],
            "NOT_SUPPORTED_OUT_OF_SAMPLE",
        )

    def test_positive_evidence_increases_a_and_decreases_b(self):
        pricing = self._estimate(self._payload(), self._divergence(80))
        self.assertGreater(pricing["sharp_estimate_a"], pricing["market_probability_a"])
        self.assertLess(pricing["sharp_estimate_b"], pricing["market_probability_b"])

    def test_negative_evidence_decreases_a(self):
        pricing = self._estimate(self._payload(), self._divergence(20))
        self.assertLess(pricing["sharp_estimate_a"], pricing["market_probability_a"])

    def test_probability_coherence_and_fair_odds(self):
        pricing = self._estimate(self._payload(), self._divergence(80))
        self.assertAlmostEqual(pricing["sharp_estimate_a"] + pricing["sharp_estimate_b"], 1.0)
        self.assertAlmostEqual(pricing["fair_odd_a"], 1.0 / pricing["sharp_estimate_a"])
        self.assertAlmostEqual(pricing["fair_odd_b"], 1.0 / pricing["sharp_estimate_b"])

    def test_fair_probability_uses_market_as_prior_but_residual_is_bounded(self):
        first = self._estimate(
            self._payload(2.10, 1.90), self._divergence(79)
        )
        second = self._estimate(
            self._payload(8.00, 1.15), self._divergence(79)
        )
        self.assertNotEqual(first["sharp_estimate_a"], second["sharp_estimate_a"])
        self.assertNotEqual(first["fair_odd_a"], second["fair_odd_a"])
        self.assertNotEqual(first["expected_edge_a"], second["expected_edge_a"])
        self.assertTrue(first["market_used_in_fair_probability"])
        self.assertLessEqual(abs(first["bounded_adjustment_pp"]), 6.0)
        self.assertLessEqual(abs(second["bounded_adjustment_pp"]), 6.0)

    def test_index_is_not_used_directly_as_probability(self):
        self.assertAlmostEqual(evidence_probability(79, 1.0), 0.61774, places=5)

    def test_market_prior_extreme_index_does_not_create_85_pct_automatically(self):
        probability, adjustment = market_prior_probability(
            0.56, 100, 1.0, maximum_adjustment_pp=6.0,
        )
        self.assertAlmostEqual(probability, 0.62)
        self.assertAlmostEqual(adjustment, 0.06)

    def test_challenger_residual_is_more_conservative(self):
        probability, adjustment = market_prior_probability(
            0.50, 100, 1.0, maximum_adjustment_pp=3.0,
        )
        self.assertAlmostEqual(probability, 0.53)
        self.assertAlmostEqual(adjustment, 0.03)

    def test_hurkacz_like_favourite_cannot_be_crushed_to_1_18(self):
        pricing = self._estimate(
            self._payload(1.59, 2.34),
            self._divergence(100, factors=8, intensity=3, weight=5),
        )
        self.assertLessEqual(pricing["bounded_adjustment_pp"], 6.0)
        self.assertGreater(pricing["fair_odd_a"], 1.45)
        self.assertLess(pricing["expected_edge_a"], 0.10)

    def test_balanced_evidence_keeps_underdog_at_market_prior(self):
        pricing = self._estimate(
            self._payload(1.52, 2.66),
            self._divergence(50, factors=8, intensity=0, weight=5),
        )
        self.assertAlmostEqual(
            pricing["sharp_estimate_b"], pricing["market_probability_b"], places=12,
        )
        self.assertAlmostEqual(pricing["bounded_adjustment_pp"], 0.0, places=12)

    def test_expected_edge_explicit_example(self):
        self.assertAlmostEqual(calculate_expected_edge(0.442, 2.44), 0.07848, places=5)
        transformed = apply_logit_residual(0.41, 0.1309163)
        self.assertAlmostEqual(transformed, 0.442, places=3)

    def test_weak_single_factor_is_attenuated_and_not_promoted(self):
        pricing = self._estimate(
            self._payload(2.0, 2.0), self._divergence(100, factors=1, intensity=3, weight=18)
        )
        self.assertLess(pricing["sharp_estimate_a"], 0.85)
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertEqual(pricing["candidate_side"], "a")

    def test_valid_edge_is_promoted_only_after_quality_gates(self):
        pricing = self._estimate(
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
        pricing = self._estimate(
            payload, self._divergence(100, factors=4, intensity=3, weight=5)
        )
        self.assertTrue(pricing["available"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertEqual(pricing["candidate_side"], "a")
        self.assertEqual(pricing["candidate_status"], "experimental_edge")

    def test_identity_warning_reduces_quality_and_blocks_candidate(self):
        payload = self._payload()
        payload["data_quality"] = {
            "issues": [{"severity": "warning", "type": "name_resolution"}]
        }
        pricing = self._estimate(
            payload, self._divergence(100, factors=4, intensity=3, weight=5)
        )
        self.assertEqual(pricing["evidence_quality"]["source_reliability"], 0.5)
        self.assertFalse(pricing["evidence_quality"]["source_gate_passed"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertEqual(pricing["candidate_side"], "a")

    def test_insufficient_factor_family_coverage_blocks_candidate(self):
        divergence = self._divergence(100, factors=4, intensity=3, weight=5)
        divergence["evidence_coverage"] = {
            "coverage_quality": 2 / 3,
            "source_reliability": 1.0,
            "pricing_eligible": False,
        }
        pricing = self._estimate(self._payload(), divergence)
        self.assertAlmostEqual(pricing["evidence_quality"]["coverage_quality"], 2 / 3, places=6)
        self.assertFalse(pricing["evidence_quality"]["coverage_gate_passed"])
        self.assertFalse(pricing["quality_gate_passed"])
        self.assertEqual(pricing["candidate_side"], "a")

    def test_missing_odds_fails_safely(self):
        payload = self._payload()
        payload["market_odds_decimal"] = {}
        pricing = self._estimate(payload, self._divergence())
        self.assertFalse(pricing["available"])
        self.assertFalse(pricing["candidate"])
        self.assertEqual(pricing["reason"], "missing_or_invalid_two_way_moneyline")
        self.assertNotIn("sharp_estimate_a", pricing)

    def test_snapshot_freezes_pricing_and_duplicate_cannot_overwrite_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            payload = self._payload()
            payload["pricing"] = self._estimate(payload, self._divergence(80))
            first = calibration_store.build_snapshot(
                payload, analyzed_at_utc="2026-08-26T08:00:00+00:00"
            )
            changed = dict(payload)
            changed["pricing"] = self._estimate(changed, self._divergence(20))
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
        payload["pricing"] = self._estimate(payload, payload["divergencia"])
        html = report_html.build_report_html_v2(
            payload, {}, lambda _: payload["divergencia"]
        )
        for expected in (
            "Market probability", "Fenzobot estimate", "Fair odd", "Market odd",
            "Expected edge", "EXPERIMENTAL", "Estimativa experimental em desenvolvimento",
            "Cobertura", "Coeficiente de fonte (pricing)",
        ):
            self.assertIn(expected, html)
        self.assertNotIn("Veredicto de mercado", html)


if __name__ == "__main__":
    unittest.main()
