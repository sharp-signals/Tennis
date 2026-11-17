import unittest

import numpy as np

from scripts.audit_contextual_family_hierarchy_v11 import (
    _consensus_feature,
    _favorite_reliability,
    _ordered_single_family_caps,
    _service_below_surface,
)


class ContextualFamilyHierarchyV11AuditTests(unittest.TestCase):
    def test_service_cap_is_surgical_and_preserves_missing_surface(self):
        aligned = {
            "recent_form": 0.4,
            "structural_strength": 0.3,
            "surface_conditions": 0.1,
            "matchup_h2h": 0.2,
            "serve_return": 0.25,
        }
        governed = _service_below_surface(aligned)
        self.assertAlmostEqual(governed["serve_return"], 0.1)

        without_surface = {**aligned, "surface_conditions": 0.0}
        governed = _service_below_surface(without_surface)
        self.assertAlmostEqual(governed["serve_return"], 0.25)

    def test_ordered_caps_do_not_apply_a_secondary_total_budget(self):
        aligned = {
            "recent_form": 0.4,
            "structural_strength": 0.3,
            "surface_conditions": 0.6,
            "matchup_h2h": 0.5,
            "serve_return": 0.7,
        }
        governed = _ordered_single_family_caps(aligned)
        self.assertAlmostEqual(governed["surface_conditions"], 0.4)
        self.assertAlmostEqual(governed["matchup_h2h"], 0.4)
        self.assertAlmostEqual(governed["serve_return"], 0.4)
        self.assertGreater(
            sum(abs(governed[key]) for key in (
                "surface_conditions", "matchup_h2h", "serve_return",
            )),
            sum(abs(governed[key]) for key in (
                "recent_form", "structural_strength",
            )),
        )

    def test_consensus_feature_requires_all_five_families_to_align(self):
        aligned = {
            "recent_form": 0.4,
            "structural_strength": 0.3,
            "surface_conditions": 0.2,
            "matchup_h2h": 0.1,
            "serve_return": 0.05,
        }
        opposed = {**aligned, "serve_return": -0.05}
        feature = _consensus_feature([aligned, opposed])
        np.testing.assert_allclose(feature, np.asarray([1.05, 0.0]))

    def test_favorite_reliability_is_independent_of_player_side(self):
        rows = _favorite_reliability(
            np.asarray([1.0, 0.0]),
            np.asarray([0.62, 0.38]),
            np.asarray([0, 1]),
        )
        self.assertEqual(rows[0]["sample"], 2)
        self.assertEqual(rows[0]["observed_favorite_win_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
