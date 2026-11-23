import unittest

import numpy as np

from scripts.audit_contextual_elite_dynamic_gate import (
    ELO_KEY,
    _apply_candidate,
    _candidate_passes,
    _gate_summary,
)


def _row(*, elo_a=0.85, rank_a=2, recent_a=0.70):
    return {
        "features": {ELO_KEY: elo_a},
        "diagnostics": {"rank_a": rank_a, "rank_b": 20},
        "family_probabilities": {"recent_form": recent_a},
    }


class EliteDynamicGateTests(unittest.TestCase):
    def test_candidate_does_not_change_probability_outside_gate(self):
        probability, gated = _apply_candidate(
            [_row(rank_a=10)], np.asarray([0.72]),
            {"rank_max": 3, "elo_min": 0.80, "recent_min": 0.65, "alpha": 0.5},
        )
        self.assertFalse(gated[0])
        self.assertAlmostEqual(probability[0], 0.72)

    def test_candidate_blends_only_when_directions_and_evidence_agree(self):
        probability, gated = _apply_candidate(
            [_row()], np.asarray([0.72]),
            {"rank_max": 3, "elo_min": 0.80, "recent_min": 0.65, "alpha": 0.5},
        )
        self.assertTrue(gated[0])
        self.assertGreater(probability[0], 0.72)
        self.assertLess(probability[0], 0.85)

    def test_candidate_is_orientation_symmetric(self):
        candidate = {
            "rank_max": 3, "elo_min": 0.80, "recent_min": 0.65, "alpha": 0.5,
        }
        a, _ = _apply_candidate([_row()], np.asarray([0.72]), candidate)
        mirrored = _row(elo_a=0.15, rank_a=20, recent_a=0.30)
        mirrored["diagnostics"]["rank_b"] = 2
        b, _ = _apply_candidate([mirrored], np.asarray([0.28]), candidate)
        self.assertAlmostEqual(a[0], 1.0 - b[0])

    def test_gate_summary_uses_full_indexes_for_sparse_gate(self):
        rows = [
            {"player_a": "A", "player_b": "B"},
            {"player_a": "C", "player_b": "D"},
            {"player_a": "E", "player_b": "F"},
        ]
        result = _gate_summary(
            rows,
            np.asarray([1.0, 0.0, 1.0]),
            np.asarray([0.60, 0.40, 0.70]),
            np.asarray([0.60, 0.40, 0.80]),
            [False, False, True],
        )
        self.assertEqual(result["sample"], 1)
        self.assertEqual(result["players"], ["E"])

    def test_inconclusive_gain_never_passes_promotion(self):
        gate = {
            "sample": 100,
            "observed_selected_side_win_pct": 90.0,
            "baseline_selected_side_probability_pct": 87.0,
            "candidate_selected_side_probability_pct": 89.0,
        }
        self.assertFalse(_candidate_passes({"status": "INCONCLUSIVE"}, gate))
        self.assertTrue(_candidate_passes({"status": "SUPPORTED"}, gate))

    def test_supported_candidate_still_fails_if_gate_calibration_worsens(self):
        gate = {
            "sample": 100,
            "observed_selected_side_win_pct": 88.0,
            "baseline_selected_side_probability_pct": 88.0,
            "candidate_selected_side_probability_pct": 90.0,
        }
        self.assertFalse(_candidate_passes({"status": "SUPPORTED"}, gate))


if __name__ == "__main__":
    unittest.main()
