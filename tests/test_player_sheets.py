import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import main


class PlayerSheetTests(unittest.TestCase):
    def test_rich_data_is_persisted_with_identity_and_reused(self):
        career = {"playerStats": {"decidingSetWinPercentage": 61, "decidingSetCount": 20}}
        perf = {"by_surface": {"hard": {"matches": 10, "win_pct": 60}}}
        previous_budget = main._RICH_FETCH_BUDGET["remaining"]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            main.fetch_data, "fetch_player_career_stats", return_value=career,
        ) as career_fetch, patch.object(
            main.fetch_data, "fetch_player_perf_breakdown", return_value=perf,
        ) as perf_fetch:
            main._RICH_FETCH_BUDGET["remaining"] = 10
            previous_cwd = os.getcwd()
            os.chdir(directory)
            try:
                first = main._get_rich_player_data("atp", "Jogador Teste", None, player_id=42)
                sheet_path = Path(main._player_sheet_path("atp", 42, "Jogador Teste"))
                stored = json.loads(sheet_path.read_text(encoding="utf-8"))
                second = main._get_rich_player_data("atp", "Jogador Teste", None, player_id=42)
            finally:
                os.chdir(previous_cwd)
                main._RICH_FETCH_BUDGET["remaining"] = previous_budget

        self.assertEqual(first, second)
        self.assertEqual(stored["schema_version"], 1)
        self.assertEqual(stored["player"], {"id": 42, "name": "Jogador Teste", "tour": "atp"})
        self.assertEqual(stored["data"], first)
        career_fetch.assert_called_once_with("atp", 42)
        perf_fetch.assert_called_once_with("atp", 42)

    def test_sheet_paths_separate_tours_and_ids(self):
        atp = main._player_sheet_path("atp", 7, "Alex Smith")
        wta = main._player_sheet_path("wta", 7, "Alex Smith")
        other = main._player_sheet_path("atp", 8, "Alex Smith")
        self.assertEqual(len({atp, wta, other}), 3)

    def test_expired_sheet_is_refreshed(self):
        previous_budget = main._RICH_FETCH_BUDGET["remaining"]
        with tempfile.TemporaryDirectory() as directory, patch.object(
            main.fetch_data, "fetch_player_career_stats", return_value={"playerStats": {"aces": 9}},
        ) as career_fetch, patch.object(
            main.fetch_data, "fetch_player_perf_breakdown", return_value={},
        ):
            main._RICH_FETCH_BUDGET["remaining"] = 10
            previous_cwd = os.getcwd()
            os.chdir(directory)
            try:
                path = Path(main._player_sheet_path("wta", 15, "Jogadora Teste"))
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({
                    "schema_version": 1,
                    "updated_at_utc": "2020-01-01T00:00:00+00:00",
                    "data": {"style": {"aces": 1}},
                }), encoding="utf-8")
                actual = main._get_rich_player_data("wta", "Jogadora Teste", None, player_id=15)
            finally:
                os.chdir(previous_cwd)
                main._RICH_FETCH_BUDGET["remaining"] = previous_budget

        self.assertEqual(actual["style"]["aces"], 9)
        career_fetch.assert_called_once_with("wta", 15)


if __name__ == "__main__":
    unittest.main()
