from __future__ import annotations

import unittest

from scripts.plan_validation import main_drift_plan, validation_plan


class ValidationPlanTests(unittest.TestCase):
    def test_docs_only_level1_does_not_force_full_ci(self):
        plan = validation_plan(
            ["AGENTS.md", "docs/development/CODEX_FAST_PATH.md"],
            level=1,
        )
        self.assertEqual(plan["scope"], "DOCS_ONLY")
        self.assertFalse(plan["full_ci_required_at_final_checkpoint"])
        self.assertEqual(plan["targeted_commands"], [])

    def test_sensitive_file_gets_targeted_tests_and_final_ci(self):
        plan = validation_plan(["src/fetch_data.py"], level=1)
        self.assertEqual(plan["scope"], "SENSITIVE_CODE")
        self.assertTrue(plan["full_ci_required_at_final_checkpoint"])
        rendered = "\n".join(plan["targeted_commands"])
        self.assertIn("tests.test_data_transforms", rendered)
        self.assertIn("tests.test_external_data_resilience", rendered)

    def test_level2_forces_final_ci_even_for_non_sensitive_change(self):
        plan = validation_plan(["scripts/refresh_observability.py"], level=2)
        self.assertTrue(plan["full_ci_required_at_final_checkpoint"])

    def test_changed_test_file_runs_only_that_test_in_targeted_loop(self):
        plan = validation_plan(["tests/test_pricing.py"], level=1)
        self.assertIn(
            "python -m unittest -v tests.test_pricing",
            plan["targeted_commands"],
        )
        self.assertFalse(plan["full_ci_required_at_final_checkpoint"])

    def test_data_only_main_drift_waits_for_final_sync(self):
        drift = main_drift_plan(
            ["src/pricing.py"],
            ["data/manual_paper_22bet.json", "data/run_metrics_log.json"],
        )
        self.assertEqual(drift["action"], "FINAL_SYNC_ONLY")
        self.assertTrue(drift["drift_data_only"])

    def test_exact_overlap_requires_immediate_sync(self):
        drift = main_drift_plan(
            ["src/main.py", "tests/test_main_deterministic.py"],
            ["src/main.py"],
        )
        self.assertEqual(drift["action"], "SYNC_NOW")
        self.assertEqual(drift["exact_file_overlap"], ["src/main.py"])

    def test_same_critical_domain_requires_immediate_sync(self):
        drift = main_drift_plan(
            ["src/competition_evidence.py"],
            ["src/fetch_data.py"],
        )
        self.assertEqual(drift["action"], "SYNC_NOW")
        self.assertIn("data_pipeline", drift["critical_domain_overlap"])

    def test_unrelated_code_drift_is_reviewed_once_not_restarted(self):
        drift = main_drift_plan(
            ["src/pricing.py"],
            ["src/player_profile.py"],
        )
        self.assertEqual(drift["action"], "REVIEW_ONCE_THEN_FINAL_SYNC")


if __name__ == "__main__":
    unittest.main()
