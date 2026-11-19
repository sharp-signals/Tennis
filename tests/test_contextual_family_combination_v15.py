import math
import unittest

from src.contextual_family_hierarchy import govern_atp_primary_conflict_consensus


class CombinationV15Tests(unittest.TestCase):
    def test_three_secondaries_preserve_strength_in_primary_conflict(self):
        original = {
            "recent_form": -0.13,
            "structural_strength": 0.06,
            "surface_conditions": 0.22,
            "matchup_h2h": 0.11,
            "serve_return": 0.21,
        }
        governed, audit = govern_atp_primary_conflict_consensus(original)
        self.assertEqual(governed, original)
        self.assertTrue(audit["three_secondary_consensus"])

    def test_partial_secondary_evidence_keeps_v14_conflict_cap(self):
        governed, audit = govern_atp_primary_conflict_consensus({
            "recent_form": -0.13,
            "structural_strength": 0.06,
            "surface_conditions": 0.22,
            "matchup_h2h": 0.0,
            "serve_return": 0.21,
        })
        secondary = sum(abs(governed[key]) for key in (
            "surface_conditions", "matchup_h2h", "serve_return",
        ))
        self.assertEqual(audit["policy"], "STRICT_CONFLICT_BLOCK_CAP")
        self.assertLessEqual(secondary, 0.19 + 1e-12)

    def test_opposing_secondary_keeps_v14_conflict_cap(self):
        governed, audit = govern_atp_primary_conflict_consensus({
            "recent_form": -0.13,
            "structural_strength": 0.06,
            "surface_conditions": 0.22,
            "matchup_h2h": -0.11,
            "serve_return": 0.21,
        })
        self.assertEqual(audit["policy"], "STRICT_CONFLICT_BLOCK_CAP")
        self.assertTrue(math.isfinite(sum(governed.values())))


if __name__ == "__main__":
    unittest.main()
