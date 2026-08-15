import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import generate_profile, player_profile


class PlayerProfileFormattingTests(unittest.TestCase):
    def test_reliability_boundaries_and_percentage(self):
        self.assertIn("muito pequena", player_profile._reliability_label(9))
        self.assertEqual(player_profile._reliability_label(10), "amostra pequena")
        self.assertEqual(player_profile._reliability_label(30), "amostra razoável")
        self.assertEqual(player_profile._reliability_label(100), "amostra sólida")
        self.assertEqual(player_profile._pct(0, 0), "n/d")
        self.assertEqual(player_profile._pct(3, 4), "75.0%")

    def test_unknown_player_returns_none_without_calculating_stats(self):
        history = pd.DataFrame()
        with patch.object(player_profile.fetch_data, "resolve_player_name", return_value=None), \
             patch.object(player_profile.fetch_data, "get_player_ranking") as ranking:
            actual = player_profile.build_player_profile_markdown(history, "Unknown", "atp")

        self.assertIsNone(actual)
        ranking.assert_not_called()

    def test_profile_contains_samples_and_tolerates_missing_ranking_date(self):
        history = pd.DataFrame()
        surface = {
            "Hard": {"wins": 30, "losses": 20, "matches": 50},
            "Clay": {"wins": 3, "losses": 2, "matches": 5},
        }
        set1 = {"bo3": {"comeback_rate_pct": 40.0, "matches_lost_set1_won_overall": 4, "matches_lost_set1": 10}}
        deciding = {"bo3": {"win_rate_pct": 60.0, "wins": 6, "matches_went_the_distance": 10}}
        layoff = {"win_rate_pct": 50.0, "wins_after_layoff": 2, "matches_after_layoff": 4}
        handedness = {"vs_left_handed": {"wins": 6, "losses": 4, "matches": 10}}
        rounds = {"late_rounds": {"wins": 7, "losses": 3, "matches": 10}}
        career = {"playerStats": {"statMatchesPlayed": 100, "firstServePercentage": 62}}

        with patch.object(player_profile.fetch_data, "resolve_player_name", return_value="Player One"), \
             patch.object(player_profile.fetch_data, "get_player_ranking", return_value={"rank": 12, "points": 2000, "as_of": None}), \
             patch.object(player_profile.fetch_data, "compute_recent_form", side_effect=lambda _h, _p, n: {"matches": n, "wins": n - 1, "losses": 1}), \
             patch.object(player_profile.fetch_data, "compute_surface_stats", return_value=surface), \
             patch.object(player_profile.fetch_data, "compute_serve_return_stats", return_value=None), \
             patch.object(player_profile.fetch_data, "compute_set1_comeback_stats", return_value=set1), \
             patch.object(player_profile.fetch_data, "compute_deciding_set_stats", return_value=deciding), \
             patch.object(player_profile.fetch_data, "compute_return_from_layoff_stats", return_value=layoff), \
             patch.object(player_profile.fetch_data, "compute_handedness_matchup_stats", return_value=handedness), \
             patch.object(player_profile.fetch_data, "compute_round_stage_stats", return_value=rounds):
            markdown = player_profile.build_player_profile_markdown(history, "Player One", "atp", career_stats=career)

        self.assertIn("# Player One", markdown)
        self.assertIn("**Ranking:** #12, 2000 pts (à data de ?)", markdown)
        self.assertIn("50 jogos", markdown)
        self.assertIn("amostra razoável", markdown)
        self.assertIn("Depois de perder o 1º set", markdown)
        self.assertIn("Stats de carreira", markdown)


class ProfileGenerationTests(unittest.TestCase):
    def test_slug_transliterates_accents(self):
        self.assertEqual(generate_profile._slug(" João Sousa "), "joao_sousa")

    def test_generate_one_writes_profile_atomically_with_rich_stats(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(generate_profile, "OUTPUT_DIR", directory), \
             patch.object(generate_profile.fetch_data, "get_history", return_value=pd.DataFrame()), \
             patch.object(generate_profile.fetch_data, "get_player_id_from_ranking", return_value=42), \
             patch.object(generate_profile.fetch_data, "fetch_player_career_stats", return_value={"matches": 10}), \
             patch.object(generate_profile, "build_player_profile_markdown", return_value="# João Sousa"):
            path = generate_profile.generate_one("João Sousa", "atp")

            self.assertEqual(Path(path).name, "joao_sousa.md")
            self.assertEqual(Path(path).read_text(encoding="utf-8"), "# João Sousa")
            self.assertEqual(list(Path(directory).glob(".profile-*.tmp")), [])

    def test_generate_one_does_not_write_unknown_player(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(generate_profile, "OUTPUT_DIR", directory), \
             patch.object(generate_profile.fetch_data, "get_history", return_value=pd.DataFrame()), \
             patch.object(generate_profile.fetch_data, "get_player_id_from_ranking", return_value=None), \
             patch.object(generate_profile, "build_player_profile_markdown", return_value=None):
            path = generate_profile.generate_one("Unknown", "wta")

        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
