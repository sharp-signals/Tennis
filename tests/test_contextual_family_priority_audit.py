from scripts.audit_contextual_family_priority_v1 import (
    H2H_STRONG,
    H2H_STRONG_SURFACE,
    H2H_RELIABILITY,
    H2H_RELIABILITY_SURFACE,
    _augment_h2h_candidates,
)


def _row(global_margin, global_count, surface_margin, surface_count):
    return {
        "features": {
            "h2h_win_share_margin": global_margin,
            "same_surface_h2h_win_share_margin": surface_margin,
        },
        "samples": {
            "h2h": global_count,
            "same_surface_h2h": surface_count,
        },
    }


def test_strong_h2h_requires_five_matches_and_eighty_percent_dominance():
    rows = [
        _row(0.6, 5, 0.6, 5),
        _row(0.6, 4, 0.6, 4),
        _row(0.2, 5, 0.2, 5),
        _row(-0.6, 5, -0.6, 5),
    ]
    _augment_h2h_candidates(rows)
    assert rows[0]["features"][H2H_STRONG] == 0.6
    assert rows[0]["features"][H2H_STRONG_SURFACE] == 0.6
    assert rows[1]["features"][H2H_STRONG] == 0.0
    assert rows[2]["features"][H2H_STRONG] == 0.0
    assert rows[3]["features"][H2H_STRONG] == -0.6
    assert rows[0]["features"][H2H_RELIABILITY] > rows[0]["features"][H2H_STRONG]
    assert rows[0]["features"][H2H_RELIABILITY_SURFACE] > 0.6
