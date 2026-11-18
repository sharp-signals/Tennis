from datetime import date
import unittest

import pandas as pd

from src.contextual_chronological_rating import (
    augment_replay_rows_with_ratings,
    build_rating_features,
    clear_rating_cache,
)


class ChronologicalRatingTest(unittest.TestCase):
    def test_uses_only_prior_matches_and_defers_same_day_updates(self):
        history = pd.DataFrame([
            {"tourney_date": 20260101, "winner_name": "A", "loser_name": "B",
             "surface": "Hard", "indoor": False},
            {"tourney_date": 20260102, "winner_name": "A", "loser_name": "B",
             "surface": "Hard", "indoor": False},
        ])
        clear_rating_cache()
        before_second = build_rating_features(
            history, universe="atp", cutoff=date(2026, 1, 2),
            player_a="A", player_b="B", surface_context="hard_outdoor",
        )
        after_second = build_rating_features(
            history, universe="atp", cutoff=date(2026, 1, 3),
            player_a="A", player_b="B", surface_context="hard_outdoor",
        )
        self.assertEqual(
            before_second["chronological_elo_margin_k32"], 0.08,
        )
        self.assertGreater(
            after_second["chronological_elo_margin_k32"], 0.08,
        )

        rows = [
            {"event_date": "2026-01-01", "player_a": "A", "player_b": "B",
             "target_a_win": True, "features": {}, "diagnostics": {
                 "surface_context": "hard_outdoor"}},
            {"event_date": "2026-01-01", "player_a": "A", "player_b": "C",
             "target_a_win": True, "features": {}, "diagnostics": {
                 "surface_context": "hard_outdoor"}},
        ]
        augmented = augment_replay_rows_with_ratings(rows, universe="wta")
        self.assertEqual(
            augmented[0]["features"]["chronological_elo_margin_k24"], 0.0,
        )
        self.assertEqual(
            augmented[1]["features"]["chronological_elo_margin_k24"], 0.0,
        )
