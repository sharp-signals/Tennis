import unittest

from scripts.audit_contextual_low_consensus_regimes import (
    _context_verdict,
    _segment,
)


def _cases(sample, wins, probability=0.60):
    return [
        {
            "favorite_won": index < wins,
            "favorite_probability": probability,
        }
        for index in range(sample)
    ]


class LowConsensusRegimeAuditTests(unittest.TestCase):
    def test_segment_reports_observed_gap_and_wilson_interval(self):
        result = _segment(_cases(20, 15, 0.60))
        self.assertEqual(result["sample"], 20)
        self.assertEqual(result["observed_pct"], 75.0)
        self.assertEqual(result["predicted_pct"], 60.0)
        self.assertEqual(result["gap_pp"], 15.0)
        self.assertLess(result["observed_wilson_95_pct"][0], 75.0)

    def test_repeated_signal_requires_wilson_and_two_folds(self):
        aggregate = _segment(_cases(40, 32, 0.55))
        folds = {
            "early": _segment(_cases(20, 16, 0.55)),
            "late": _segment(_cases(20, 16, 0.55)),
        }
        self.assertEqual(
            _context_verdict(aggregate, folds),
            "REPEATED_UNDERCONFIDENCE_SIGNAL",
        )

    def test_contradictory_fold_blocks_repeated_signal(self):
        aggregate = _segment(_cases(40, 26, 0.55))
        folds = {
            "early": _segment(_cases(20, 16, 0.55)),
            "late": _segment(_cases(20, 10, 0.55)),
        }
        self.assertEqual(
            _context_verdict(aggregate, folds),
            "UNSTABLE_OR_CONTRADICTORY",
        )


if __name__ == "__main__":
    unittest.main()
