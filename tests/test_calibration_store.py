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

    def test_market_observation_link_is_frozen_with_snapshot(self):
        payload = self._payload()
        payload.update({
            "event_key": "atp:m1",
            "entry_market_observation_id": "observation-1",
            "reference_market_observation_ids": ["reference-1"],
            "market_memory_status": "RECORDED",
            "market_memory_eligible": True,
        })
        snapshot = calibration_store.build_snapshot(payload)
        self.assertEqual(snapshot["event_key"], "atp:m1")
        self.assertEqual(snapshot["entry_market_observation_id"], "observation-1")
        self.assertEqual(snapshot["reference_market_observation_ids"], ["reference-1"])
        self.assertTrue(snapshot["market_memory_eligible"])

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

    def test_settlement_falls_back_to_players_and_date_when_api_ids_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshot = calibration_store.build_snapshot(
                self._payload(), analyzed_at_utc="2026-08-16T08:00:00+00:00",
            )
            calibration_store.upsert_snapshots([snapshot], path)
            match = {
                "id": "a-different-endpoint-id", "player1Id": 10, "player2Id": 20,
                "match_winner": 20, "result_type": "completed", "result": "4-6 4-6",
                "date": "2026-08-17T11:00:00Z",
            }
            self.assertEqual(calibration_store.settle_from_matches([match], path), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["outcome"]["winner_side"], "b")

    def test_incomplete_match_is_not_settled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            calibration_store.upsert_snapshots([calibration_store.build_snapshot(self._payload())], path)
            match = {"id": "m1", "match_winner": 10, "result_type": "scheduled"}
            self.assertEqual(calibration_store.settle_from_matches([match], path), 0)

    def test_indicative_odds_are_provisional_below_minimum_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            document = {
                "schema_version": 1,
                "snapshots": [{
                    "metrics": {"divergencia": {
                        "indice_evidencia_a": 72, "indice_evidencia_b": 28,
                    }},
                    "outcome": {"winner_side": "a"},
                }],
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 72, "indice_evidencia_b": 28}, path, min_samples=3,
            )
            self.assertTrue(actual["available"])
            self.assertFalse(actual["calibrated"])
            self.assertTrue(actual["provisional"])
            self.assertEqual(actual["basis"], "historical")
            self.assertEqual(actual["sample_size"], 1)
            self.assertIn("players", actual)

    def test_indicative_odds_have_wide_heuristic_before_first_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            path.write_text(json.dumps({"schema_version": 1, "snapshots": []}), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 90, "indice_evidencia_b": 10}, path,
            )
            self.assertTrue(actual["available"])
            self.assertFalse(actual["calibrated"])
            self.assertEqual(actual["basis"], "heuristic")
            self.assertEqual(actual["sample_size"], 0)
            self.assertGreater(actual["players"]["a"]["odds_high"] - actual["players"]["a"]["odds_low"], 0.5)

    def test_indicative_odds_use_settled_results_and_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshots = []
            for winner in ("a", "a", "b"):
                snapshots.append({
                    "metrics": {"divergencia": {
                        "indice_evidencia_a": 72, "indice_evidencia_b": 28,
                    }},
                    "outcome": {"winner_side": winner},
                })
            path.write_text(json.dumps({"schema_version": 1, "snapshots": snapshots}), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 74, "indice_evidencia_b": 26}, path, min_samples=3,
            )
            self.assertTrue(actual["available"])
            self.assertTrue(actual["calibrated"])
            self.assertEqual(actual["sample_size"], 3)
            self.assertLess(actual["players"]["a"]["odds_low"], actual["players"]["a"]["odds_high"])
            self.assertGreater(actual["players"]["b"]["odds_low"], 1)


if __name__ == "__main__":
    unittest.main()
