import unittest
from unittest.mock import patch

import pandas as pd

from src import player_profile_v2


class PlayerProfileV2BuilderTests(unittest.TestCase):
    def test_builder_counts_only_selected_player_and_marks_low_sample(self):
        history = pd.DataFrame([
            {"winner_name": "Player A", "loser_name": "Player B"},
            {"winner_name": "Player C", "loser_name": "Player A"},
            {"winner_name": "Player B", "loser_name": "Player C"},
        ])
        with patch.object(player_profile_v2.fetch_data, "resolve_player_name", return_value="Player A"), \
             patch.object(player_profile_v2.fetch_data, "get_player_ranking", return_value={
                 "rank": 25, "points": 1500, "as_of": "2026-11-20",
             }), \
             patch.object(player_profile_v2.fetch_data, "compute_recent_form", return_value={
                 "matches": 2, "wins": 1, "losses": 1,
             }), \
             patch.object(player_profile_v2.fetch_data, "compute_surface_stats", return_value={
                 "Hard": {"matches": 2, "wins": 1, "losses": 1},
             }), \
             patch.object(player_profile_v2.fetch_data, "compute_serve_return_stats", return_value=None):
            profile = player_profile_v2.build_player_profile_v2_record(
                history, "Player A", "atp", player_id=9,
                generated_at_utc="2026-11-23T12:00:00+00:00",
            )

        self.assertEqual(profile["overall_sample"]["matches"], 2)
        self.assertEqual(profile["overall_sample"]["status"], "VERY_LOW")
        self.assertEqual(profile["alerts"][0]["code"], "PLAYER_SAMPLE_BELOW_20")
        self.assertEqual(profile["player"]["current_rank"], 25)
        self.assertTrue(all(metric["model_role"] == "DESCRIPTIVE_ONLY" for metric in profile["metrics"]))

    def test_builder_returns_none_for_unknown_player(self):
        with patch.object(player_profile_v2.fetch_data, "resolve_player_name", return_value=None):
            profile = player_profile_v2.build_player_profile_v2_record(
                pd.DataFrame(), "Unknown", "wta",
            )

        self.assertIsNone(profile)


if __name__ == "__main__":
    unittest.main()
