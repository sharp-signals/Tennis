"""Regressões do histórico ATP + Challenger isolado por tier."""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import pandas as pd

from src import fetch_data


class _Response:
    def __init__(self, *, json_body=None, text=""):
        self._json_body = json_body
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_body


class ChallengerHistoryCoverageTests(unittest.TestCase):
    def setUp(self):
        fetch_data._HISTORY_CACHE.clear()
        fetch_data._NAME_INDEX_CACHE.clear()

    def tearDown(self):
        fetch_data._HISTORY_CACHE.clear()
        fetch_data._NAME_INDEX_CACHE.clear()

    def test_loader_combines_tags_and_deduplicates_challenger_history(self):
        year = datetime.now(timezone.utc).year
        listing = {
            "files": [
                {"name": f"{year}.csv", "url": "https://test/main.csv"},
                {
                    "name": f"{year}_challenger.csv",
                    "url": "https://test/challenger.csv",
                },
                {
                    "name": "challenger_ongoing_tourneys.csv",
                    "url": "https://test/ongoing.csv",
                },
                {
                    "name": "ongoing_tourneys.csv",
                    "url": "https://test/main-ongoing.csv",
                },
            ]
        }
        main_csv = (
            "tourney_id,match_num,tourney_date,winner_name,loser_name,score,w_ace\n"
            "main-1,1,20260101,Main Winner,Main Loser,6-4 6-4,5\n"
        )
        challenger_csv = (
            "tourney_id,match_num,tourney_date,winner_name,loser_name,score,w_ace\n"
            "ch-1,1,20260102,Challenger Player,Other Player,6-3 6-3,\n"
            "ch-1,2,20260102,Second Player,Third Player,7-6 6-4,7\n"
        )
        ongoing_csv = (
            "tourney_id,match_num,tourney_date,winner_name,loser_name,score,w_ace\n"
            "ch-1,1,20260102,Challenger Player,Other Player,6-3 6-3,11\n"
            "ch-2,1,20260103,New Player,Fresh Player,6-2 6-2,9\n"
        )
        main_ongoing_csv = (
            "tourney_id,match_num,tourney_date,winner_name,loser_name,score,w_ace\n"
            "main-2,1,20260103,Fresh Main,Main Opponent,6-2 6-2,8\n"
        )

        def fake_get(url, **_kwargs):
            if url == fetch_data.TENNISMYLIFE_FILES_ENDPOINT:
                return _Response(json_body=listing)
            bodies = {
                "https://test/main.csv": main_csv,
                "https://test/challenger.csv": challenger_csv,
                "https://test/ongoing.csv": ongoing_csv,
                "https://test/main-ongoing.csv": main_ongoing_csv,
            }
            return _Response(text=bodies[url])

        with patch.object(fetch_data, "HISTORY_YEARS_TO_LOAD", 1), patch.object(
            fetch_data.requests, "get", side_effect=fake_get
        ):
            history = fetch_data._load_tennismylife(
                "atp", include_challenger=True
            )

        self.assertEqual(len(history), 5)
        self.assertEqual(
            fetch_data.history_scope_summary(history),
            {
                "mode": "ATP_MAIN_PLUS_CHALLENGER",
                "rows_total": 5,
                "rows_main": 2,
                "rows_challenger": 3,
            },
        )
        duplicate = history[
            (history["tourney_id"] == "ch-1") & (history["match_num"] == 1)
        ]
        self.assertEqual(len(duplicate), 1)
        self.assertEqual(float(duplicate.iloc[0]["w_ace"]), 11.0)
        self.assertEqual(
            fetch_data.resolve_player_name(history, "Challenger Player"),
            "Challenger Player",
        )

    def test_get_history_keeps_main_and_challenger_universes_separate(self):
        main = pd.DataFrame([
            {"winner_name": "Main A", "loser_name": "Main B"}
        ])
        combined = pd.DataFrame([
            {
                "winner_name": "Main A", "loser_name": "Main B",
                "_history_competition_scope": "main",
            },
            {
                "winner_name": "Challenger A", "loser_name": "Challenger B",
                "_history_competition_scope": "challenger",
            },
        ])

        def loader(_tour, *, include_challenger=False):
            result = (combined if include_challenger else main).copy()
            result.attrs["history_scope"] = (
                "ATP_MAIN_PLUS_CHALLENGER" if include_challenger else "ATP_MAIN"
            )
            return result

        with patch.object(fetch_data, "_load_tennismylife", side_effect=loader) as mocked:
            main_history = fetch_data.get_history("atp", tier="ATP 500")
            challenger_history = fetch_data.get_history(
                "atp", tier="Challenger 125"
            )
            self.assertIs(
                challenger_history,
                fetch_data.get_history("atp", tier="Challenger 125"),
            )

        self.assertEqual(len(main_history), 1)
        self.assertEqual(len(challenger_history), 2)
        self.assertEqual(mocked.call_count, 2)
        mocked.assert_any_call("atp", include_challenger=False)
        mocked.assert_any_call("atp", include_challenger=True)
        self.assertIsNone(
            fetch_data.resolve_player_name(main_history, "Challenger A")
        )
        self.assertEqual(
            fetch_data.resolve_player_name(challenger_history, "Challenger A"),
            "Challenger A",
        )

    def test_loader_supports_wta_rich_annual_and_ongoing_files(self):
        year = datetime.now(timezone.utc).year
        listing = {
            "files": [
                {"name": f"{year}_wta.csv", "url": "https://test/wta.csv"},
                {
                    "name": "wta_ongoing_tourneys.csv",
                    "url": "https://test/wta-ongoing.csv",
                },
            ]
        }
        annual = (
            "tourney_id,match_num,tourney_date,tourney_name,surface,"
            "winner_name,loser_name,w_ace,l_ace,w_svpt,l_svpt\n"
            "wta-1,1,20260101,WTA Event,Hard,A,B,5,3,50,50\n"
        )
        ongoing = (
            "tourney_id,match_num,tourney_date,tourney_name,surface,"
            "winner_name,loser_name,w_ace,l_ace,w_svpt,l_svpt\n"
            "wta-1,1,20260101,WTA Event,Hard,A,B,8,4,50,50\n"
            "wta-2,1,20260108,Current WTA,Hard,C,D,6,2,50,50\n"
        )

        def fake_get(url, **_kwargs):
            if url == fetch_data.TENNISMYLIFE_FILES_ENDPOINT:
                return _Response(json_body=listing)
            return _Response(text={
                "https://test/wta.csv": annual,
                "https://test/wta-ongoing.csv": ongoing,
            }[url])

        with patch.object(fetch_data, "HISTORY_YEARS_TO_LOAD", 1), patch.object(
            fetch_data.requests, "get", side_effect=fake_get
        ):
            history = fetch_data._load_tennismylife("wta")

        self.assertEqual(len(history), 2)
        updated = history[history["tourney_id"] == "wta-1"].iloc[0]
        self.assertEqual(float(updated["w_ace"]), 8.0)
        self.assertEqual(history.attrs["history_scope"], "WTA_MAIN")

    def test_filter_history_scope_is_a_non_mutating_challenger_view(self):
        history = pd.DataFrame([
            {
                "winner_name": "Main A", "loser_name": "Main B",
                "_history_competition_scope": "main",
            },
            {
                "winner_name": "Challenger A", "loser_name": "Challenger B",
                "_history_competition_scope": "challenger",
            },
        ])
        filtered = fetch_data.filter_history_scope(history, "challenger")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["winner_name"], "Challenger A")
        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
