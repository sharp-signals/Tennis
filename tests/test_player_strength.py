import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import player_strength


class PlayerStrengthTests(unittest.TestCase):
    def test_normalize_surface_supports_historical_french_labels(self):
        self.assertEqual(player_strength.normalize_surface("dur"), "hard")
        self.assertEqual(player_strength.normalize_surface("dur intérieur"), "hard")
        self.assertEqual(player_strength.normalize_surface("dur int�rieur"), "hard")
        self.assertEqual(player_strength.normalize_surface("terre battue"), "clay")
        self.assertEqual(player_strength.normalize_surface("gazon"), "grass")

    def test_atp_prior_excludes_challengers_and_same_day_results(self):
        fieldnames = [
            "date", "surface", "winner_name", "loser_name", "score",
            "_history_competition_scope",
        ]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "history.csv.gz"
            rows = []
            for day in range(1, 6):
                rows.append({
                    "date": f"2026-01-0{day}", "surface": "Hard",
                    "winner_name": "Player Alpha", "loser_name": "Player Beta",
                    "score": "6-4 6-4", "_history_competition_scope": "main",
                })
            for day in range(6, 9):
                rows.append({
                    "date": f"2026-01-0{day}", "surface": "Hard",
                    "winner_name": "Player Beta", "loser_name": "Player Alpha",
                    "score": "6-0 6-0", "_history_competition_scope": "challenger",
                })
            rows.append({
                "date": "2026-01-10", "surface": "Hard",
                "winner_name": "Player Beta", "loser_name": "Player Alpha",
                "score": "6-0 6-0", "_history_competition_scope": "main",
            })
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            payload = {
                "player_a": "Player Alpha", "player_b": "Player Beta",
                "surface": "Indoor Hard",
                "analyzed_at_utc": "2026-01-10T08:00:00+00:00",
            }
            with patch.object(player_strength, "ATP_HISTORY_FILES", (path,)):
                player_strength._history_matches.cache_clear()
                player_strength._RATING_CACHE.clear()
                result = player_strength.atp_main_strength_features(payload)
            player_strength._history_matches.cache_clear()
            player_strength._RATING_CACHE.clear()
        self.assertTrue(result["available"])
        self.assertEqual(result["history_scope"], "ATP_MAIN_ONLY")
        self.assertEqual(result["processed_matches"], 5)
        self.assertGreater(result["global_logit"], 0)
        self.assertGreater(result["surface_logit"], 0)

    def test_unique_middle_name_variant_resolves_without_hardcoded_alias(self):
        counts = {
            "taylor harry fritz": 393,
            "denis shapovalov": 214,
            "other player": 50,
        }
        resolved, basis = player_strength._resolve_history_name(
            "taylor fritz", counts
        )
        self.assertEqual(resolved, "taylor harry fritz")
        self.assertEqual(basis, "UNIQUE_TOKEN_CONTAINMENT")

    def test_ambiguous_structural_name_variant_fails_closed(self):
        counts = {
            "alexander john smith": 20,
            "alexander paul smith": 20,
        }
        resolved, basis = player_strength._resolve_history_name(
            "alexander smith", counts
        )
        self.assertEqual(resolved, "alexander smith")
        self.assertEqual(basis, "AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
