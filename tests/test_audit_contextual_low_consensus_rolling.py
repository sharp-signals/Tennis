import unittest

import numpy as np

from scripts.audit_contextual_low_consensus_rolling import (
    _low_consensus_case_records,
    _rolling_decision,
)


class LowConsensusRollingAuditTests(unittest.TestCase):
    def test_case_trace_uses_baseline_side_and_pre_match_context(self):
        rows = [{
            "event_date": "2026-01-01",
            "player_a": "Player A",
            "player_b": "Player B",
            "realized_family_contributions": {
                "recent_form": 0.03,
                "structural_strength": 0.04,
                "surface_conditions": 0.01,
                "matchup_h2h": 0.02,
                "serve_return": 0.01,
            },
            "diagnostics": {
                "rank_a": 12,
                "rank_b": 30,
                "surface_context": "hard_indoor",
                "target_tier": "500",
            },
            "samples": {"h2h": 6},
        }]
        features = {
            "low_consensus_mask": np.asarray([True]),
            "base_logit": np.asarray([0.11]),
        }
        records = _low_consensus_case_records(
            rows, np.asarray([1.0]), np.asarray([0.60]), features,
            baseline_slope=1.0, fold_name="late",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["favorite"], "Player A")
        self.assertTrue(records[0]["favorite_won"])
        self.assertEqual(records[0]["favorite_rank"], 12)
        self.assertEqual(records[0]["h2h_sample"], 6)
        self.assertEqual(records[0]["surface_context"], "hard_indoor")

    def test_support_requires_both_aggregate_gains_and_two_positive_folds(self):
        decision = _rolling_decision(
            {"status": "SUPPORTED"},
            {"paired_gain": {"status": "SUPPORTED"}},
            [0.01, 0.02, -0.01],
            {"brier": 0.22, "ece_10": 0.02},
            {"brier": 0.21, "ece_10": 0.019},
        )
        self.assertEqual(
            decision, "ROLLING_CANDIDATE_SUPPORTED_NOT_PROMOTED",
        )

    def test_support_is_withheld_when_calibration_worsens(self):
        decision = _rolling_decision(
            {"status": "SUPPORTED"},
            {"paired_gain": {"status": "SUPPORTED"}},
            [0.01, 0.02, -0.01],
            {"brier": 0.22, "ece_10": 0.02},
            {"brier": 0.21, "ece_10": 0.021},
        )
        self.assertEqual(decision, "INCONCLUSIVE_KEEP_CURRENT_RELEASE")

    def test_two_negative_folds_reject_candidate(self):
        decision = _rolling_decision(
            {"status": "INCONCLUSIVE"},
            {"paired_gain": {"status": "INCONCLUSIVE"}},
            [-0.01, -0.02, 0.01],
            {"brier": 0.22, "ece_10": 0.02},
            {"brier": 0.22, "ece_10": 0.02},
        )
        self.assertEqual(decision, "ROLLING_CANDIDATE_REJECTED")


if __name__ == "__main__":
    unittest.main()
