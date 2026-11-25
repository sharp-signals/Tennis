import unittest

from scripts.audit_contextual_consensus_calibration import (
    _audit_records,
    _certification,
    _cross_grouped,
    _fair_band,
    _segment,
    _stage_trace,
)


class ContextualConsensusCalibrationAuditTests(unittest.TestCase):
    def test_fair_odd_bands_follow_requested_favorite_ranges(self):
        self.assertEqual(_fair_band(1 / 1.20), "1.10-1.25")
        self.assertEqual(_fair_band(1 / 1.35), "1.26-1.40")
        self.assertEqual(_fair_band(1 / 1.50), "1.41-1.60")
        self.assertEqual(_fair_band(1 / 1.70), "1.61-1.80")
        self.assertEqual(_fair_band(0.52), ">1.80")

    def test_consensus_is_measured_on_the_model_favorite_side(self):
        row = {
            "target_a_win": True,
            "family_probabilities": {
                "recent_form": 0.70,
                "structural_strength": 0.65,
                "surface_conditions": 0.55,
                "matchup_h2h": 0.60,
                "serve_return": 0.51,
            },
        }
        records = _audit_records(
            [row], [0.72],
            coefficients={name: 0.2 for name in row["family_probabilities"]},
            calibrator={"method": "IDENTITY", "intercept": 0.0, "slope": 1.0},
        )
        self.assertEqual(records[0]["consensus"], "5/5")
        self.assertTrue(records[0]["primary_aligned"])
        self.assertTrue(records[0]["favorite_won"])
        self.assertEqual(
            records[0]["primary_alignment_label"], "both_primary_aligned",
        )
        self.assertEqual(records[0]["consensus_label"], "unanimous_5_of_5")

    def test_probability_trace_separates_hierarchy_slope_and_final_calibration(self):
        row = {
            "target_a_win": True,
            "family_probabilities": {
                "recent_form": 0.70,
                "structural_strength": 0.65,
                "surface_conditions": 0.55,
                "matchup_h2h": 0.60,
                "serve_return": 0.51,
            },
            "realized_family_contributions": {
                "recent_form": 0.20,
                "structural_strength": 0.25,
                "surface_conditions": 0.05,
                "matchup_h2h": 0.03,
                "serve_return": 0.02,
            },
            "calibrated_realized_family_contributions": {
                "recent_form": 0.22,
                "structural_strength": 0.275,
                "surface_conditions": 0.055,
                "matchup_h2h": 0.033,
                "serve_return": 0.022,
            },
        }
        records = _audit_records(
            [row], [0.65], coefficients={},
            calibrator={"method": "IDENTITY", "intercept": 0.0, "slope": 1.0},
        )
        trace = _stage_trace(records)
        self.assertEqual(trace["sample"], 1)
        self.assertGreater(trace["mean_post_slope_probability_pct"], 50.0)
        self.assertEqual(trace["mean_final_probability_pct"], 65.0)
        self.assertGreater(
            trace["mean_primary_logit_contribution"],
            trace["mean_secondary_logit_contribution"],
        )

    def test_certification_requires_primary_hierarchy_and_monotonic_intensity(self):
        def segment(probability, wins):
            return _segment([
                {
                    "favorite_probability": probability,
                    "favorite_won": index < wins,
                }
                for index in range(100)
            ])

        overall = segment(0.65, 65)
        primary = {
            "both_primary_aligned": segment(0.70, 70),
            "not_both_primary_aligned": segment(0.55, 55),
        }
        intensity = {
            "SLIGHT": segment(0.55, 55),
            "MODERATE": segment(0.65, 65),
            "STRONG": segment(0.75, 75),
            "DECISIVE": segment(0.85, 85),
        }
        result = _certification(
            overall=overall, primary=primary,
            unanimous=segment(0.72, 72), intensity=intensity,
            coefficients={
                "recent_form": 0.40,
                "structural_strength": 0.46,
                "surface_conditions": 0.30,
                "matchup_h2h": 0.12,
                "serve_return": 0.12,
            },
        )
        self.assertEqual(result["status"], "PASSED")
        self.assertTrue(all(result["gates"].values()))

    def test_segment_reports_calibration_gap_without_refitting(self):
        result = _segment([
            {"favorite_probability": 0.70, "favorite_won": True},
            {"favorite_probability": 0.80, "favorite_won": False},
        ])
        self.assertEqual(result["sample"], 2)
        self.assertEqual(result["predicted_pct"], 75.0)
        self.assertEqual(result["observed_pct"], 50.0)
        self.assertEqual(result["gap_pp"], -25.0)

    def test_cross_grouping_keeps_probability_and_context_segments_separate(self):
        result = _cross_grouped([
            {
                "probability_band": "60-70%",
                "surface_context": "hard_indoor",
                "favorite_probability": 0.65,
                "favorite_won": True,
            },
            {
                "probability_band": "60-70%",
                "surface_context": "clay",
                "favorite_probability": 0.65,
                "favorite_won": False,
            },
        ], "probability_band", "surface_context")
        self.assertEqual(result["60-70% | hard_indoor"]["observed_pct"], 100.0)
        self.assertEqual(result["60-70% | clay"]["observed_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
