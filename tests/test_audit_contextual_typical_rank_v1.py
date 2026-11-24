import pytest

from scripts.audit_contextual_typical_rank_v1 import (
    BASELINE_PROFILES,
    CANDIDATE_FEATURE,
    CANDIDATE_PROFILES,
    _residual_segments,
)
from src.contextual_family_calibration import CALIBRATION_FEATURE_PROFILES


@pytest.mark.parametrize("universe", ("atp", "wta"))
def test_typical_rank_candidate_adds_one_feature_to_correct_baseline(universe):
    baseline = CALIBRATION_FEATURE_PROFILES[BASELINE_PROFILES[universe]][
        "structural_strength"
    ]
    candidate = CALIBRATION_FEATURE_PROFILES[CANDIDATE_PROFILES[universe]][
        "structural_strength"
    ]
    assert candidate[:-1] == baseline
    assert candidate[-1] == CANDIDATE_FEATURE


def test_residual_diagnostics_distinguish_material_opposition():
    import numpy as np

    rows = [{
        CANDIDATE_FEATURE: -0.4,
        "contextual_structural_material_rank_core_v6": 0.8,
    }]
    result = _residual_segments(
        rows, np.asarray([1.0]), np.asarray([0.6]), np.asarray([0.55]),
    )
    assert result["material_0_25_to_0_75"]["targets"] == 1
    assert result["opposes_current_rank"]["targets"] == 1
