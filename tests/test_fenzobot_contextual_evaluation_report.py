import json
from pathlib import Path
import unittest

from scripts.generated_output_contract import is_allowed
from src import contextual_shadow_report_v2 as report
from src import contextual_shadow_settlement_v2 as settlement
from src.fenzobot_contextual_runtime import GLOBAL_RELEASE_ID


def _observation():
    return {
        "schema_version": 3,
        "observation_id": "global-obs-1",
        "canonical_match_instance_id": "global-match-1",
        "tour": "atp",
        "tier": "ATP 500",
        "commence_time_utc": "2026-11-12T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-11T10:00:00+00:00",
        "players": {
            "a": {"id": 1, "name": "Alpha"},
            "b": {"id": 2, "name": "Beta"},
        },
        "competition": {
            "tournament_name": "Test Open",
            "round_stage": "EARLY_ROUNDS",
            "surface": "hard_indoor",
        },
        "contextual_shadow": {
            "global_release_id": GLOBAL_RELEASE_ID,
            "component_versions": {
                "ranking_model": "contextual-ranking-v7.1",
                "family_combination": "contextual-family-combination-v4-ranking-v7",
                "probability_calibration": "contextual-probability-uncertainty-v4",
                "runtime_generation": 6,
            },
            "configuration_fingerprint": "global-fingerprint",
            "probability_model_a": 0.61,
            "probability_model_b": 0.39,
            "probability_interval_90_model_a": [0.53, 0.68],
            "fair_odd_model_a": {
                "central": 1.6393, "lower_odd": 1.4706, "upper_odd": 1.8868,
            },
            "fair_odd_model_b": {
                "central": 2.5641, "lower_odd": 2.1277, "upper_odd": 3.125,
            },
            "families": [{
                "key": "recent_form", "label": "Forma recente ajustada",
                "probability_model_a": 0.64, "logit_contribution": 0.2,
                "impact_pp_model_a": 4.1, "impact_intensity": "MODERATE",
                "coverage_grade": "SOLID",
                "data_state": "OBSERVED",
            }],
            "family_coverage": {"solid": 5, "partial": 0,
                                "observed_neutral": 0, "unavailable": 0,
                                "usable": 5, "total": 5, "pct": 100.0},
            "surface_context": "hard_indoor",
            "quality_group": "PRIMARY_READY_COMPLETE",
            "status": "READY_FOR_PROSPECTIVE_SHADOW",
            "reason_codes": [],
            "calibration_bin_sample": 0,
            "market_used": False,
            "production_effect": False,
        },
        "paper_eligible": False,
        "green_eligible": False,
    }


def _contract():
    return report.load_report_contract(
        Path("data/models/fenzobot-contextual-2026-11-report.json"),
        expected_model_version=GLOBAL_RELEASE_ID,
        expected_contract_version="fenzobot-contextual-2026-11-report.10",
    )


class FenzobotContextualEvaluationReportTests(unittest.TestCase):
    def test_global_release_report_preserves_prediction_and_identity(self):
        view = report.build_report_view_model(
            _observation(),
            contract=_contract(),
            expected_model_version=GLOBAL_RELEASE_ID,
        )
        self.assertEqual(view["players"]["a"]["probability"], 0.61)
        self.assertEqual(view["global_release_id"], GLOBAL_RELEASE_ID)
        self.assertEqual(
            view["component_versions"]["ranking_model"],
            "contextual-ranking-v7.1",
        )
        html = report.render_report_html(view)
        self.assertIn(GLOBAL_RELEASE_ID, html)
        self.assertNotIn("contextual-ranking-v7.1", html)
        self.assertNotIn("contextual-probability-uncertainty-v4", html)
        self.assertNotIn("configuration_fingerprint", html)
        self.assertNotIn("REGISTAR PAPER", html)
        self.assertNotIn("APOSTAR", html)

    def test_global_release_evaluation_uses_separate_immutable_outcome(self):
        observation = _observation()
        outcome = {
            "observation_id": observation["observation_id"],
            "canonical_match_instance_id": observation[
                "canonical_match_instance_id"
            ],
            "configuration_fingerprint": "global-fingerprint",
            "model_version": GLOBAL_RELEASE_ID,
            "winner_side": "a",
        }
        contract = settlement.load_validation_contract(
            Path("data/models/fenzobot-contextual-2026-11-validation.json"),
            expected_model_version=GLOBAL_RELEASE_ID,
            expected_contract_version=(
                "fenzobot-contextual-2026-11-validation.1"
            ),
        )
        result = settlement.build_evaluation(
            [observation], [outcome],
            validation_contract=contract,
            model_version=GLOBAL_RELEASE_ID,
        )
        self.assertEqual(result["model_version"], GLOBAL_RELEASE_ID)
        self.assertEqual(result["counts"]["ready_settled"], 1)
        self.assertEqual(result["settlement_audit"]["status"], "HEALTHY")
        self.assertFalse(result["promotion_authorized"])

    def test_global_workflow_orders_evidence_before_report_and_publish(self):
        workflow = Path(
            ".github/workflows/fenzobot-contextual-2026-11.yml"
        ).read_text(encoding="utf-8")
        commands = [
            "python scripts/settle_fenzobot_contextual_2026_11.py",
            "python scripts/run_fenzobot_contextual_2026_11.py",
            "python scripts/capture_fenzobot_contextual_market.py",
            "python scripts/build_fenzobot_contextual_report_preview.py",
            "python scripts/stage_generated_outputs.py --profile bot",
        ]
        positions = [workflow.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("python scripts/build_fenzobot_contextual_publication.py", workflow)
        self.assertIn("python -m src.report_notifications wait", workflow)
        self.assertIn("python -m src.report_notifications send", workflow)
        self.assertIn("TELEGRAM_BOT_TOKEN", workflow)
        self.assertTrue(is_allowed(
            "data/contextual_shadow_market-fenzobot-contextual-2026-11.jsonl",
            "bot",
        ))
        self.assertTrue(is_allowed(
            "data/contextual_shadow_outcomes-fenzobot-contextual-2026-11.jsonl",
            "bot",
        ))
        self.assertTrue(is_allowed(
            "data/contextual_shadow_h2h_evidence-fenzobot-contextual-2026-11.jsonl",
            "bot",
        ))


if __name__ == "__main__":
    unittest.main()
