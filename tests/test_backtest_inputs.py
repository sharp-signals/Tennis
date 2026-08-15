import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from src import backtest


class BacktestInputTests(unittest.TestCase):
    def test_surname_index_resolves_unique_name_and_rejects_ambiguity(self):
        history = pd.DataFrame(
            {
                "winner_name": ["Carlos Alcaraz", "Camilo Alcaraz", "Jannik Sinner"],
                "loser_name": ["Novak Djokovic", "Daniil Medvedev", None],
            }
        )

        index = backtest._build_surname_index(history)

        self.assertEqual(backtest._resolve_tennisdata_name("Sinner J.", index), "Jannik Sinner")
        self.assertIsNone(backtest._resolve_tennisdata_name("Alcaraz C.", index))
        self.assertIsNone(backtest._resolve_tennisdata_name("SingleName", index))

    def test_odds_use_preferred_valid_pair_and_ignore_invalid_values(self):
        row = pd.Series({"PSW": "bad", "PSL": 1.8, "AvgW": 2.1, "AvgL": 1.7, "B365W": 9, "B365L": 9})
        self.assertEqual(backtest._get_odds(row), (2.1, 1.7))
        self.assertIsNone(backtest._get_odds(pd.Series({"PSW": 1.0, "PSL": 2.0})))

    def test_implied_probability_removes_bookmaker_margin(self):
        probability = backtest._implied_prob_winner(2.0, 2.0)
        favorite_probability = backtest._implied_prob_winner(1.5, 3.0)

        self.assertEqual(probability, 0.5)
        self.assertAlmostEqual(favorite_probability, 2 / 3)

    def test_date_parser_supports_known_formats_and_preserves_timezone(self):
        self.assertEqual(backtest._parse_date("15/08/2026").date().isoformat(), "2026-08-15")
        self.assertEqual(backtest._parse_date("15/08/26").tzinfo, timezone.utc)
        self.assertEqual(backtest._parse_date("2026-08-15").tzinfo, timezone.utc)
        aware = datetime(2026, 8, 15, tzinfo=timezone(timedelta(hours=2)))
        self.assertIs(backtest._parse_date(aware), aware)
        self.assertIsNone(backtest._parse_date("not-a-date"))

    def test_load_years_combines_only_non_empty_sources(self):
        frames = {
            2024: pd.DataFrame({"Winner": ["A"]}),
            2025: pd.DataFrame(),
            2026: None,
        }
        with patch.object(backtest, "BACKTEST_YEARS", [2024, 2025, 2026]), \
             patch.object(backtest, "_fetch_tennisdata_year", side_effect=lambda year: frames[year]):
            actual = backtest._load_all_backtest_years()

        self.assertEqual(len(actual), 1)
        self.assertEqual(actual.iloc[0]["_year"], 2024)


class BacktestSignalTests(unittest.TestCase):
    def test_all_edges_applies_sample_thresholds_and_combines_available_signals(self):
        h2h = {"overall": {"total_matches": 4, "a_wins": 3, "b_wins": 1}}
        forms = [
            {"matches": 10, "wins": 8},
            {"matches": 10, "wins": 5},
        ]
        surfaces = [
            {"Hard": {"matches": 20, "wins": 14}},
            {"Hard": {"matches": 20, "wins": 10}},
        ]
        with patch.object(backtest.fetch_data, "compute_h2h", return_value=h2h), \
             patch.object(backtest.fetch_data, "compute_recent_form", side_effect=forms), \
             patch.object(backtest.fetch_data, "compute_surface_stats", side_effect=surfaces):
            actual = backtest._all_edges(pd.DataFrame(), "A", "B", "Hard")

        self.assertEqual(actual["h2h"], 50.0)
        self.assertEqual(actual["form"], 30.0)
        self.assertEqual(actual["surface"], 20.0)
        self.assertAlmostEqual(actual["combined"], 100 / 3)

    def test_all_edges_returns_none_when_samples_are_insufficient(self):
        h2h = {"overall": {"total_matches": 1, "a_wins": 1, "b_wins": 0}}
        forms = [{"matches": 4, "wins": 4}, {"matches": 10, "wins": 5}]
        surfaces = [{"Hard": {"matches": 4, "wins": 4}}, {"Hard": {"matches": 10, "wins": 5}}]
        with patch.object(backtest.fetch_data, "compute_h2h", return_value=h2h), \
             patch.object(backtest.fetch_data, "compute_recent_form", side_effect=forms), \
             patch.object(backtest.fetch_data, "compute_surface_stats", side_effect=surfaces):
            actual = backtest._all_edges(pd.DataFrame(), "A", "B", "Hard")

        self.assertEqual(actual, {"h2h": None, "form": None, "surface": None, "combined": None})


if __name__ == "__main__":
    unittest.main()
