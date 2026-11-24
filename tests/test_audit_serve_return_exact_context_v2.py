import numpy as np

from scripts.audit_serve_return_exact_context_v2 import (
    _calibration_bins,
    _paired_diagnostics,
)


def test_calibration_bins_preserve_counts_and_observed_rates():
    result = _calibration_bins(
        np.asarray([0.0, 1.0, 1.0]),
        np.asarray([0.12, 0.64, 0.66]),
    )

    assert sum(item["targets"] for item in result) == 3
    assert result[0]["observed_rate"] == 0.0
    assert result[1]["observed_rate"] == 1.0


def test_paired_diagnostics_separate_hard_context_and_favourite_strength():
    holdout = [
        {"diagnostics": {"surface_context": "hard_indoor"}},
        {"diagnostics": {"surface_context": "hard_outdoor"}},
        {"diagnostics": {"surface_context": "hard_indoor"}},
    ]
    result = _paired_diagnostics(
        holdout,
        [0, 1, 2],
        np.asarray([1.0, 0.0, 0.0]),
        np.asarray([0.72, 0.62, 0.45]),
        np.asarray([0.76, 0.58, 0.40]),
    )

    assert result["by_exact_context"]["hard_indoor"]["baseline"]["covered"] == 2
    assert result["by_exact_context"]["hard_outdoor"]["baseline"]["covered"] == 1
    bands = result["baseline_selected_favourite"]["by_baseline_strength"]
    assert bands["favourite_60_70"]["targets"] == 1
    assert bands["strong_favourite_70_plus"]["targets"] == 1
