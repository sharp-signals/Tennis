import unittest

from scripts.audit_contextual_primary_dominant_consensus import (
    _exploratory_decision,
)


class PrimaryDominantConsensusAuditTests(unittest.TestCase):
    def test_support_remains_exploratory(self):
        decision = _exploratory_decision(
            {"status": "INCONCLUSIVE", "log_loss_gain": 0.0001},
            {"paired_gain": {"status": "SUPPORTED"}},
            [0.01, 0.02, -0.001],
            {"brier": 0.22, "ece_10": 0.02},
            {"brier": 0.219, "ece_10": 0.019},
        )
        self.assertEqual(
            decision,
            "EXPLORATORY_SUPPORTED_REQUIRES_PROSPECTIVE_CONFIRMATION",
        )

    def test_two_negative_folds_reject_candidate(self):
        decision = _exploratory_decision(
            {"status": "INCONCLUSIVE", "log_loss_gain": 0.0},
            {"paired_gain": {"status": "INCONCLUSIVE"}},
            [-0.01, -0.02, 0.01],
            {"brier": 0.22, "ece_10": 0.02},
            {"brier": 0.22, "ece_10": 0.02},
        )
        self.assertEqual(decision, "EXPLORATORY_CANDIDATE_REJECTED")


if __name__ == "__main__":
    unittest.main()
