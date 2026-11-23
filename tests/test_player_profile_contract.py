import unittest

from src.player_profile_contract import (
    CANDIDATE_REPLAY_REQUIRED,
    build_profile_contract,
    build_search_index_entry,
    make_metric,
    assess_sample,
)


class PlayerProfileContractTests(unittest.TestCase):
    def test_sample_below_twenty_is_critical_and_not_comparable(self):
        assessment = assess_sample(19)

        self.assertEqual(assessment["status"], "VERY_LOW")
        self.assertEqual(assessment["alert_level"], "CRITICAL")
        self.assertFalse(assessment["eligible_for_comparison"])

    def test_sample_boundaries_are_explicit(self):
        self.assertEqual(assess_sample(20)["status"], "LIMITED")
        self.assertEqual(assess_sample(50)["status"], "REASONABLE")
        self.assertEqual(assess_sample(100)["status"], "SOLID")
        self.assertEqual(assess_sample(None, applicable=False)["status"], "NOT_APPLICABLE")

    def test_low_sample_profile_exposes_alert_in_search_index(self):
        metric = make_metric(
            metric_id="surface_hard_career",
            label="Carreira em hard",
            family="surface_conditions",
            value=0.6,
            unit="win_rate",
            sample_size=10,
            source="canonical_history",
            model_role=CANDIDATE_REPLAY_REQUIRED,
        )
        profile = build_profile_contract(
            player_name="Jogador Teste",
            tour="atp",
            overall_matches=12,
            metrics=[metric],
            generated_at_utc="2026-11-23T12:00:00+00:00",
            identity={"player_id": 42, "current_rank": 123},
        )

        self.assertEqual(profile["alerts"][0]["code"], "PLAYER_SAMPLE_BELOW_20")
        self.assertEqual(profile["metrics"][0]["sample_assessment"]["status"], "VERY_LOW")
        index = build_search_index_entry(profile)
        self.assertEqual(index["name"], "Jogador Teste")
        self.assertEqual(index["current_rank"], 123)
        self.assertTrue(index["has_critical_alert"])

    def test_invalid_model_role_is_rejected(self):
        with self.assertRaises(ValueError):
            make_metric(
                metric_id="x",
                label="X",
                family="recent_form",
                value=1,
                sample_size=20,
                source="test",
                model_role="AUTO_PROMOTE",
            )


if __name__ == "__main__":
    unittest.main()
