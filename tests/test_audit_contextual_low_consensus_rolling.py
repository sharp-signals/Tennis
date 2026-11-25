import unittest

from scripts.audit_contextual_low_consensus_rolling import _rolling_decision


class LowConsensusRollingAuditTests(unittest.TestCase):
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
