import unittest

from src.contextual_family_hierarchy import (
    govern_consensus_aware_family_contributions,
    govern_realized_family_contributions,
)


class RealizedFamilyHierarchyTests(unittest.TestCase):
    def test_secondary_block_cannot_exceed_primary_block(self):
        governed, audit = govern_realized_family_contributions({
            "recent_form": 0.4,
            "structural_strength": 0.2,
            "surface_conditions": 1.2,
            "matchup_h2h": -0.5,
            "serve_return": 0.3,
        })
        primary = abs(governed["recent_form"]) + abs(governed["structural_strength"])
        secondary = sum(abs(governed[key]) for key in (
            "surface_conditions", "matchup_h2h", "serve_return",
        ))
        self.assertLessEqual(secondary, primary + 1e-12)
        self.assertLessEqual(max(abs(governed[key]) for key in (
            "surface_conditions", "matchup_h2h", "serve_return",
        )), primary / 2.0 + 1e-12)
        self.assertIs(audit["applied"], True)
    def test_projection_preserves_secondary_signs_and_relative_proportions(self):
        original = {
            "recent_form": 0.2,
            "structural_strength": -0.1,
            "surface_conditions": 0.9,
            "matchup_h2h": -0.3,
            "serve_return": 0.15,
        }
        governed, audit = govern_realized_family_contributions(original)
        scale = audit["secondary_scale"]
        for key in ("surface_conditions", "matchup_h2h", "serve_return"):
            self.assertAlmostEqual(governed[key], original[key] * scale)
        self.assertEqual(governed["recent_form"], original["recent_form"])
        self.assertEqual(governed["structural_strength"], original["structural_strength"])
    def test_no_primary_evidence_cannot_create_secondary_prediction(self):
        governed, audit = govern_realized_family_contributions({
            "recent_form": 0.0,
            "structural_strength": 0.0,
            "surface_conditions": 0.8,
            "matchup_h2h": -0.4,
            "serve_return": 0.2,
        })
        self.assertTrue(all(governed[key] == 0.0 for key in (
            "surface_conditions", "matchup_h2h", "serve_return",
        )))
        self.assertEqual(audit["secondary_scale"], 0.0)
    def test_already_compliant_contributions_remain_unchanged(self):
        original = {
            "recent_form": 0.8,
            "structural_strength": 0.6,
            "surface_conditions": 0.3,
            "matchup_h2h": -0.2,
            "serve_return": 0.1,
        }
        governed, audit = govern_realized_family_contributions(original)
        self.assertEqual(governed, original)
        self.assertIs(audit["applied"], False)
        self.assertEqual(audit["secondary_scale"], 1.0)


class ConsensusAwareFamilyHierarchyTests(unittest.TestCase):
    def test_unanimous_evidence_is_preserved_without_directional_conflict(self):
        governed, audit = govern_consensus_aware_family_contributions({
            "recent_form": 0.2,
            "structural_strength": 0.01,
            "surface_conditions": 0.6,
            "matchup_h2h": 0.08,
            "serve_return": 0.8,
        })
        self.assertIs(audit["consensus_reinforcement"], True)
        self.assertEqual(
            audit["policy"], "UNANIMOUS_REINFORCEMENT_PRESERVED",
        )
        self.assertEqual(audit["secondary_scale"], 1.0)
        self.assertEqual(governed["surface_conditions"], 0.6)
        self.assertEqual(governed["serve_return"], 0.8)
        self.assertGreater(
            sum(abs(governed[key]) for key in (
                "surface_conditions", "matchup_h2h", "serve_return",
            )),
            abs(governed["recent_form"]) + abs(governed["structural_strength"]),
        )

    def test_split_primary_families_keep_strict_block_cap(self):
        governed, audit = govern_consensus_aware_family_contributions({
            "recent_form": -0.2,
            "structural_strength": 0.1,
            "surface_conditions": 0.6,
            "matchup_h2h": -0.08,
            "serve_return": 0.8,
        })
        primary = abs(governed["recent_form"]) + abs(
            governed["structural_strength"]
        )
        secondary = sum(abs(governed[key]) for key in (
            "surface_conditions", "matchup_h2h", "serve_return",
        ))
        self.assertIs(audit["consensus_reinforcement"], False)
        self.assertEqual(audit["policy"], "STRICT_CONFLICT_BLOCK_CAP")
        self.assertLessEqual(secondary, primary + 1e-12)

    def test_aligned_primary_with_opposing_secondary_keeps_strict_cap(self):
        governed, audit = govern_consensus_aware_family_contributions({
            "recent_form": 0.2,
            "structural_strength": 0.1,
            "surface_conditions": 0.6,
            "matchup_h2h": -0.08,
            "serve_return": 0.8,
        })
        self.assertIs(audit["consensus_reinforcement"], False)
        self.assertLessEqual(
            sum(abs(governed[key]) for key in (
                "surface_conditions", "matchup_h2h", "serve_return",
            )),
            0.3 + 1e-12,
        )


if __name__ == "__main__":
    unittest.main()
