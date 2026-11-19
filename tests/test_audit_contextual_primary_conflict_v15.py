import unittest

from scripts.audit_contextual_primary_conflict_v15 import (
    _conflict_consensus_governor,
    _secondary_conflict_consensus,
)


def _conflict():
    return {
        "recent_form": -0.13,
        "structural_strength": 0.06,
        "surface_conditions": 0.22,
        "matchup_h2h": 0.11,
        "serve_return": 0.21,
    }


class PrimaryConflictAuditTests(unittest.TestCase):
    def test_detects_primary_conflict_with_three_aligned_secondaries(self):
        self.assertTrue(_secondary_conflict_consensus(_conflict()))

    def test_does_not_treat_partial_secondary_evidence_as_consensus(self):
        values = _conflict()
        values["matchup_h2h"] = 0.0
        self.assertFalse(_secondary_conflict_consensus(values))

    def test_primary_total_cap_preserves_individual_primary_authority(self):
        governed, audit = _conflict_consensus_governor("primary_total")(
            _conflict()
        )
        self.assertEqual(
            audit["policy"],
            "SECONDARY_CONSENSUS_ARBITRATES_PRIMARY_CONFLICT",
        )
        self.assertLessEqual(
            max(abs(governed[key]) for key in (
                "surface_conditions", "matchup_h2h", "serve_return",
            )),
            0.19 + 1e-12,
        )

    def test_uncapped_candidate_changes_only_the_audited_profile(self):
        values = _conflict()
        governed, _ = _conflict_consensus_governor("uncapped")(values)
        self.assertEqual(governed, values)


if __name__ == "__main__":
    unittest.main()

