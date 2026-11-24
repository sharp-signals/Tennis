import unittest

from scripts.audit_contextual_typical_rank_v1 import (
    BASELINE_PROFILES,
    CANDIDATE_FEATURE,
    CANDIDATE_PROFILES,
    _residual_segments,
)
from src.contextual_family_calibration import CALIBRATION_FEATURE_PROFILES


class TypicalRankAuditTests(unittest.TestCase):
    def test_candidate_adds_one_feature_to_correct_baseline(self):
        for universe in ("atp", "wta"):
            with self.subTest(universe=universe):
                baseline = CALIBRATION_FEATURE_PROFILES[
                    BASELINE_PROFILES[universe]
                ]["structural_strength"]
                candidate = CALIBRATION_FEATURE_PROFILES[
                    CANDIDATE_PROFILES[universe]
                ]["structural_strength"]
                self.assertEqual(candidate[:-1], baseline)
                self.assertEqual(candidate[-1], CANDIDATE_FEATURE)

    def test_residual_diagnostics_distinguish_material_opposition(self):
        import numpy as np

        rows = [{
            CANDIDATE_FEATURE: -0.4,
            "contextual_structural_material_rank_core_v6": 0.8,
        }]
        result = _residual_segments(
            rows, np.asarray([1.0]), np.asarray([0.6]), np.asarray([0.55]),
        )
        self.assertEqual(result["material_0_25_to_0_75"]["targets"], 1)
        self.assertEqual(result["opposes_current_rank"]["targets"], 1)
