import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src import fetch_data, valuebetennis_history as history


class ValuebetennisHistoryTests(unittest.TestCase):
    def test_normalize_preserves_opening_and_closing_and_winner_orientation(self):
        raw = pd.DataFrame([{
            "match_id": 10, "date": "2026-10-01 12:00:00", "tournoi": "ATP Test",
            "categorie": "Main tour", "genre": "atp", "surface": "dur", "tour": 4,
            "joueur1": "Player A", "joueur1_id": 1, "joueur2": "Player B", "joueur2_id": 2,
            "cote1_ouverture": 1.80, "cote2_ouverture": 2.10,
            "cote1_cloture": 1.70, "cote2_cloture": 2.25,
            "vainqueur_id": 2, "score": "4-6 6-7(4)",
        }])
        row = history.normalize_frame(raw).iloc[0]
        self.assertEqual(row["winner_name"], "Player B")
        self.assertEqual(row["score"], "6-4 7-6")
        self.assertEqual(row["opening_winner_odd"], 2.10)
        self.assertEqual(row["closing_winner_odd"], 2.25)
        self.assertEqual(row["PSW"], 2.25)
        self.assertEqual(row["odds_observation"], "closing")
        self.assertEqual(row["surface"], "Hard")
        self.assertFalse(row["indoor"])
        self.assertEqual(row["source_surface"], "dur")

    def test_indoor_surface_is_normalized_without_losing_source_context(self):
        raw = pd.DataFrame([{
            "match_id": 12, "date": "2026-10-01", "tournoi": "ATP Indoor",
            "categorie": "Main tour", "genre": "atp", "surface": "dur intérieur", "tour": 9,
            "joueur1": "Player A", "joueur1_id": 1, "joueur2": "Player B", "joueur2_id": 2,
            "cote1_ouverture": 1.50, "cote2_ouverture": 2.60,
            "cote1_cloture": 1.45, "cote2_cloture": 2.75,
            "vainqueur_id": 1, "score": "6-3 6-4",
        }])

        row = history.normalize_frame(raw).iloc[0]

        self.assertEqual(row["surface"], "Hard")
        self.assertTrue(row["indoor"])
        self.assertEqual(row["source_surface"], "dur intérieur")
        self.assertEqual(fetch_data._normalize_surface_family("dur intérieur"), "hard")
        self.assertEqual(fetch_data.indoor_outdoor_context("dur intérieur"), "indoor")
        self.assertEqual(fetch_data._normalize_surface_family("terre battue"), "clay")

    def test_load_history_migrates_legacy_mojibake_surfaces_in_memory(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory) / history.CACHE_PATTERN.format(year=2026)
            pd.DataFrame([
                {"source_match_id": "1", "surface": "dur int�rieur"},
                {"source_match_id": "2", "surface": "moquette int�rieur"},
            ]).to_csv(cache, index=False, compression="gzip")

            loaded = history.load_history(
                Path(directory), refresh_current=False, current_year=2026,
            ).set_index("source_match_id")

        self.assertEqual(loaded.loc[1, "surface"], "Hard")
        self.assertEqual(loaded.loc[2, "surface"], "Carpet")
        self.assertTrue(bool(loaded.loc[1, "indoor"]))
        self.assertTrue(bool(loaded.loc[2, "indoor"]))
        self.assertEqual(loaded.loc[1, "source_surface"], "dur int�rieur")

    def test_opening_is_labelled_fallback_when_closing_pair_is_missing(self):
        raw = pd.DataFrame([{
            "match_id": 11, "date": "2026-10-01", "tournoi": "Challenger Test",
            "categorie": "Challenger", "genre": "atp", "surface": "dur", "tour": 5,
            "joueur1": "Player A", "joueur1_id": 1, "joueur2": "Player B", "joueur2_id": 2,
            "cote1_ouverture": 1.50, "cote2_ouverture": 2.60,
            "cote1_cloture": None, "cote2_cloture": None,
            "vainqueur_id": 1, "score": "6-3 6-4",
        }])
        row = history.normalize_frame(raw).iloc[0]
        self.assertEqual(row["PSW"], 1.50)
        self.assertEqual(row["odds_observation"], "opening")
        self.assertEqual(row["_history_competition_scope"], "challenger")

    def test_canonical_enrichment_requires_unique_players_and_date(self):
        source = pd.DataFrame([{
            "date": "2026-10-01", "winner_name": "Player A", "loser_name": "Player B",
            "opening_winner_odd": 1.8, "opening_loser_odd": 2.1,
            "closing_winner_odd": 1.7, "closing_loser_odd": 2.25,
            "source_match_id": "10",
        }])
        snapshot = {
            "key": "atp:10", "tour": "atp", "commence_time_utc": "2026-10-01T15:00:00Z",
            "player_a": {"name": "Player B"}, "player_b": {"name": "Player A"},
            "market_odds_decimal": {},
        }
        rows = history.canonical_odds_enrichment([snapshot], source)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["closing_odd_a"], 2.25)
        self.assertEqual(rows[0]["semantics"], "POST_HOC_ENRICHMENT_NOT_ORIGINAL_CAPTURE")
        ambiguous = pd.concat([source, source.assign(source_match_id="11")], ignore_index=True)
        self.assertEqual(history.canonical_odds_enrichment([snapshot], ambiguous), [])

    def test_canonical_enrichment_allows_unique_adjacent_local_date_with_same_tournament(self):
        snapshot = {
            "key": "atp:1", "tour": "atp", "commence_time_utc": "2026-09-02T23:30:00Z",
            "tournament": "U.S. Open - New York",
            "player_a": {"name": "James Duckworth"},
            "player_b": {"name": "Yibing Wu"},
            "market_odds_decimal": {},
        }
        frame = pd.DataFrame([{
            "date": "2026-09-03", "tourney_name": "U.S. Open - New York",
            "winner_name": "Yibing Wu", "loser_name": "James Duckworth",
            "opening_winner_odd": 1.80, "opening_loser_odd": 2.05,
            "closing_winner_odd": 1.74, "closing_loser_odd": 2.22,
            "source_match_id": "9001",
        }])
        result = history.canonical_odds_enrichment([snapshot], frame)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date_delta_days"], 1)
        self.assertEqual(
            result[0]["match_confidence"],
            "exact_players_tournament_adjacent_date_unique",
        )

    def test_adjacent_date_does_not_match_a_different_tournament(self):
        snapshot = {
            "key": "atp:1", "tour": "atp", "commence_time_utc": "2026-09-02T23:30:00Z",
            "tournament": "U.S. Open - New York",
            "player_a": {"name": "A"}, "player_b": {"name": "B"},
            "market_odds_decimal": {},
        }
        frame = pd.DataFrame([{
            "date": "2026-09-03", "tourney_name": "Different Tournament",
            "winner_name": "A", "loser_name": "B", "source_match_id": "2",
        }])
        self.assertEqual(history.canonical_odds_enrichment([snapshot], frame), [])


if __name__ == "__main__":
    unittest.main()
