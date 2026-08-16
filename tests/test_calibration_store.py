import json
import tempfile
import unittest
from pathlib import Path

from src import calibration_store


class CalibrationStoreTests(unittest.TestCase):
    def _payload(self):
        return {
            "match_id": "m1", "tour": "atp", "tournament_id": 8,
            "player_a_id": 10, "player_b_id": 20,
            "player_a": "A", "player_b": "B",
            "commence_time_utc": "2026-08-17T10:00:00+00:00",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "pressure_profile_a": {"matches": 20, "break_points_saved_pct": 65.0},
        }

    def test_duplicate_run_preserves_original_pre_match_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            first = calibration_store.build_snapshot(self._payload(), analyzed_at_utc="2026-08-16T08:00:00+00:00")
            changed = self._payload()
            changed["market_odds_decimal"] = {"A": 1.5, "B": 2.7}
            second = calibration_store.build_snapshot(changed, analyzed_at_utc="2026-08-16T09:00:00+00:00")
            self.assertEqual(calibration_store.upsert_snapshots([first], path), 1)
            self.assertEqual(calibration_store.upsert_snapshots([second], path), 0)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
            self.assertEqual(saved[0]["market_odds_decimal"]["A"], 1.8)

    def test_settlement_updates_only_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshot = calibration_store.build_snapshot(self._payload(), analyzed_at_utc="2026-08-16T08:00:00+00:00")
            calibration_store.upsert_snapshots([snapshot], path)
            match = {"id": "m1", "match_winner": 20, "result_type": "completed", "result": "4-6 6-3 6-2"}
            self.assertEqual(calibration_store.settle_from_matches([match], path), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["outcome"]["winner_side"], "b")
            self.assertEqual(saved["metrics"], snapshot["metrics"])
            self.assertEqual(calibration_store.settle_from_matches([match], path), 0)

    def test_incomplete_match_is_not_settled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            calibration_store.upsert_snapshots([calibration_store.build_snapshot(self._payload())], path)
            match = {"id": "m1", "match_winner": 10, "result_type": "scheduled"}
            self.assertEqual(calibration_store.settle_from_matches([match], path), 0)


if __name__ == "__main__":
    unittest.main()
