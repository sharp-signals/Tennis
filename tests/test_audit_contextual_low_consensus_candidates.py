import unittest

import numpy as np

from scripts.audit_contextual_low_consensus_candidates import (
    _candidate_features,
    _favorite_segment,
    _fit_nonnegative_logistic,
)
from src.contextual_family_combination_v2 import FAMILY_ORDER


def _prediction_row(
    sign=1.0, *, missing_secondary=False, primary_dominant=False,
):
    raw = {
        family: sign * (
            0.08 if primary_dominant and index < 2 else 0.01
            if primary_dominant else 0.02 + 0.005 * index
        )
        for index, family in enumerate(FAMILY_ORDER)
    }
    if missing_secondary:
        raw["serve_return"] = 0.0
    return {
        "pre_hierarchy_family_contributions": raw,
        "realized_family_contributions": dict(raw),
    }


class LowConsensusCandidateAuditTests(unittest.TestCase):
    def test_candidate_features_are_symmetric_and_require_all_five_families(self):
        features = _candidate_features(
            [
                _prediction_row(1.0),
                _prediction_row(-1.0),
                _prediction_row(1.0, missing_secondary=True),
            ],
            baseline_slope=1.0,
        )
        self.assertTrue(np.isclose(
            features["base_logit"][0], -features["base_logit"][1],
        ))
        self.assertEqual(features["bonus_feature"][0], 1.0)
        self.assertEqual(features["bonus_feature"][1], -1.0)
        self.assertEqual(
            features["unanimous_mask"].tolist(), [True, True, False],
        )
        self.assertEqual(
            features["low_consensus_mask"].tolist(), [True, True, False],
        )

    def test_nonnegative_logistic_learns_positive_targeted_bonus(self):
        rng = np.random.default_rng(7)
        base = rng.normal(0.0, 1.0, 4000)
        targeted = (np.abs(base) < 0.5).astype(float) * np.sign(base)
        probability = 1.0 / (1.0 + np.exp(-(0.7 * base + 0.8 * targeted)))
        targets = (rng.random(len(base)) < probability).astype(float)
        weights = _fit_nonnegative_logistic(
            np.column_stack((base, targeted)), targets,
        )
        self.assertGreater(weights[0], 0.0)
        self.assertGreater(weights[1], 0.2)

    def test_primary_dominant_mask_requires_the_primary_block_to_lead(self):
        features = _candidate_features(
            [_prediction_row(), _prediction_row(primary_dominant=True)],
            baseline_slope=1.0,
        )
        self.assertEqual(
            features["primary_dominant_mask"].tolist(), [False, True],
        )
        self.assertEqual(
            features["primary_dominant_bonus_feature"].tolist(), [0.0, 1.0],
        )

    def test_favorite_segment_keeps_baseline_side_fixed(self):
        result = _favorite_segment(
            np.asarray([1.0, 0.0]),
            np.asarray([0.60, 0.40]),
            np.asarray([0.70, 0.30]),
            np.asarray([True, True]),
        )
        self.assertEqual(result["sample"], 2)
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["baseline_predicted_pct"], 60.0)
        self.assertEqual(result["candidate_predicted_pct"], 70.0)


if __name__ == "__main__":
    unittest.main()
