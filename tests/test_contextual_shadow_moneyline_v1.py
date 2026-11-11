from datetime import date

import pandas as pd

from src.contextual_shadow_moneyline_v1 import (
    build_frozen_moneyline_evidence,
    select_moneyline_history,
)


def test_moneyline_evidence_is_pre_match_and_selects_current_band():
    history = pd.DataFrame([
        {
            "date": "2026-10-01", "winner_name": "Alpha", "loser_name": "Beta",
            "score": "6-4 6-4", "best_of": 3, "B365W": 1.90, "B365L": 2.00,
        },
        {
            "date": "2026-10-10", "winner_name": "Gamma", "loser_name": "Alpha",
            "score": "6-3 6-4", "best_of": 3, "B365W": 1.80, "B365L": 1.95,
        },
        {
            "date": "2026-11-12", "winner_name": "Alpha", "loser_name": "Delta",
            "score": "6-0 6-0", "best_of": 3, "B365W": 1.90, "B365L": 2.00,
        },
    ])
    evidence = build_frozen_moneyline_evidence(
        history,
        observation_id="obs-1",
        configuration_fingerprint="fingerprint",
        player_a="Alpha",
        player_b="Beta",
        cutoff=date(2026, 11, 11),
        captured_at_utc="2026-11-10T10:00:00+00:00",
    )
    selected = select_moneyline_history(
        evidence, side="a", observed_odd=1.90, match_format="bo3",
    )
    assert selected["general"] == {
        "sample": 2, "wins": 1, "win_rate_pct": 50.0,
    }
    assert selected["current_band_label"] == "1.81-2.00"
    assert selected["current_band"] == {
        "sample": 2, "wins": 1, "win_rate_pct": 50.0,
    }
    assert evidence["production_effect"] is False
