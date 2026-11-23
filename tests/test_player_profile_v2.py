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
        roles = {metric["model_role"] for metric in profile["metrics"]}
        self.assertIn("MODEL_ACTIVE", roles)
        self.assertIn("DESCRIPTIVE_ONLY", roles)

    def test_context_splits_keep_samples_and_do_not_enter_model(self):
        history = pd.DataFrame([
            {
                "winner_name": "Player A", "loser_name": "Player B",
                "winner_rank": 12, "loser_rank": 2, "tourney_date": 20260102,
                "tourney_level": "G", "best_of": 5, "surface": "Hard", "indoor": False,
            },
            {
                "winner_name": "Player C", "loser_name": "Player A",
                "winner_rank": 8, "loser_rank": 11, "tourney_date": 20260202,
                "tourney_level": "M", "best_of": 3, "surface": "Hard", "indoor": True,
            },
        ])
        metrics = []

        player_profile_v2._append_context_metrics(metrics, history, "Player A")

        by_id = {metric["metric_id"]: metric for metric in metrics}
        self.assertEqual(by_id["opponent_level_top3"]["sample_size"], 1)
        self.assertEqual(by_id["opponent_level_top10"]["sample_size"], 2)
        self.assertEqual(by_id["tournament_level_grand_slam"]["context"]["wins"], 1)
        self.assertEqual(by_id["format_bo5"]["sample_size"], 1)
        self.assertEqual(by_id["venue_indoor_career"]["sample_size"], 1)
        self.assertTrue(all(metric["model_role"] == "DESCRIPTIVE_ONLY" for metric in metrics))

    def test_builder_returns_none_for_unknown_player(self):
        with patch.object(player_profile_v2.fetch_data, "resolve_player_name", return_value=None):
            profile = player_profile_v2.build_player_profile_v2_record(
                pd.DataFrame(), "Unknown", "wta",
            )

        self.assertIsNone(profile)

    def test_recent_quality_and_season_surface_exclude_future_rows(self):
        history = pd.DataFrame([
            {
                "winner_name": "Player A", "loser_name": "Player B",
                "winner_rank": 30, "loser_rank": 10,
                "tourney_date": 20261001, "surface": "Hard", "tourney_name": "Event 1",
            },
            {
                "winner_name": "Player C", "loser_name": "Player A",
                "winner_rank": 80, "loser_rank": 25,
                "tourney_date": 20261015, "surface": "Clay", "tourney_name": "Event 2",
            },
            {
                "winner_name": "Player A", "loser_name": "Player D",
                "winner_rank": 20, "loser_rank": 5,
                "tourney_date": 20261201, "surface": "Grass", "tourney_name": "Future",
            },
        ])
        metrics = []
        cutoff = pd.Timestamp("2026-11-23T12:00:00Z").to_pydatetime()

        player_profile_v2._append_recent_quality_metrics(metrics, history, "Player A", cutoff)
        player_profile_v2._append_season_surface_metrics(metrics, history, "Player A", cutoff)

        by_id = {metric["metric_id"]: metric for metric in metrics}
        self.assertEqual(by_id["recent_90d_quality_wins"]["context"]["count"], 1)
        self.assertEqual(by_id["recent_90d_quality_wins"]["sample_size"], 1)
        self.assertEqual(by_id["recent_90d_costly_losses"]["context"]["count"], 1)
        season = by_id["season_surface_evolution"]["value"]
        self.assertEqual(season[0]["overall"]["matches"], 2)
        self.assertEqual(season[0]["hard"]["wins"], 1)
        self.assertEqual(season[0]["grass"]["sample_assessment"]["status"], "NOT_APPLICABLE")

    def test_historical_odds_metrics_keep_band_samples_and_are_descriptive(self):
        odds = pd.DataFrame([
            {
                "winner_name": "Player A", "loser_name": "Player B",
                "date": "2026-01-10", "score": "6-4 6-4",
                "B365W": 1.35, "B365L": 3.20, "best_of": 3,
            },
            {
                "winner_name": "Player C", "loser_name": "Player A",
                "date": "2026-02-10", "score": "6-3 6-4",
                "B365W": 1.60, "B365L": 2.20, "best_of": 3,
            },
        ])
        odds.attrs["source"] = "test_odds_cache"
        metrics = []

        player_profile_v2._append_odds_metrics(
            metrics, odds, "Player A", pd.Timestamp("2026-11-23T12:00:00Z").to_pydatetime(),
        )

        by_id = {metric["metric_id"]: metric for metric in metrics}
        self.assertEqual(by_id["moneyline_odds_band_1_31_1_40"]["sample_size"], 1)
        self.assertEqual(by_id["moneyline_observed_1_20_to_2_00"]["value"], 1.0)
        self.assertEqual(by_id["moneyline_observed_above_2_00"]["value"], 0.0)
        formats = by_id["moneyline_odds_band_1_31_1_40"]["context"]["by_format"]
        self.assertNotIn("margins", formats["bo3"])
        self.assertEqual(formats["bo3"]["n"], 1)
        self.assertTrue(all(metric["model_role"] == "DESCRIPTIVE_ONLY" for metric in metrics))


if __name__ == "__main__":
    unittest.main()
