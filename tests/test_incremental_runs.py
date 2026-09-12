import unittest

from src import incremental_runs


MATCH = {
    "_tour": "wta", "id": 123, "date": "2026-09-14T10:00:00+00:00",
    "player1": {"name": "Alpha"}, "player2": {"name": "Beta"},
}
ODDS = {"Alpha": 1.50, "Beta": 2.70}


class IncrementalRunsTests(unittest.TestCase):
    def test_new_fixture_is_processed(self):
        self.assertEqual(incremental_runs.decide(MATCH, ODDS, None), (True, "new_fixture"))

    def test_valid_unchanged_fixture_is_skipped(self):
        prior = {"status": "AVAILABLE", "odds": ODDS}
        self.assertEqual(
            incremental_runs.decide(MATCH, ODDS, prior),
            (False, "valid_report_unchanged"),
        )

    def test_pending_fixture_returns_when_market_becomes_available(self):
        prior = {"status": "PENDING", "odds": {}}
        self.assertEqual(
            incremental_runs.decide(MATCH, ODDS, prior),
            (True, "pending_market_resolved"),
        )

    def test_material_implied_probability_move_is_reprocessed(self):
        prior = {"status": "AVAILABLE", "odds": ODDS}
        moved = {"Alpha": 1.34, "Beta": 3.25}
        self.assertEqual(
            incremental_runs.decide(MATCH, moved, prior),
            (True, "material_market_move"),
        )

    def test_small_move_does_not_duplicate_a_report(self):
        prior = {"status": "AVAILABLE", "odds": ODDS}
        moved = {"Alpha": 1.48, "Beta": 2.74}
        self.assertEqual(
            incremental_runs.decide(MATCH, moved, prior),
            (False, "valid_report_unchanged"),
        )

