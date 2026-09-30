import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import update_calibration_outcomes as maintenance
from src import forward_only


class SettlementMaintenanceTests(unittest.TestCase):
    def test_batch_rotates_from_durable_cursor(self):
        self.assertEqual(maintenance._batch(["a", "b", "c"], "a", 2), ["b", "c"])
        self.assertEqual(maintenance._batch(["a", "b", "c"], "c", 2), ["a", "b"])
        self.assertEqual(maintenance._batch(["a", "b", "c"], "missing", 2), ["a", "b"])

    def test_new_record_settles_once_and_resume_keeps_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "data/calibration_snapshots.json"
            paper = root / "data/paper_trades.json"
            cache = root / "data/cache/players/1/player.json"
            checkpoint = root / "data/maintenance/settlement-v1.json"
            ledger = root / "data/market_ledger"
            manifest = root / "manifest.json"
            cache.parent.mkdir(parents=True)
            snapshots.parent.mkdir(parents=True, exist_ok=True)
            snapshot = {
                "key": "new", "event_key": "new", "match_id": "new", "tour": "atp",
                "commence_time_utc": "2026-10-02T10:00:00+00:00",
                "analyzed_at_utc": "2026-10-01T08:00:00+00:00",
                "player_a": {"id": 1}, "player_b": {"id": 2},
                "metrics": {}, "outcome": None,
            }
            snapshots.write_text(json.dumps({"schema_version": 1, "snapshots": [snapshot]}), encoding="utf-8")
            paper.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
            cache.write_text(json.dumps({"entries": {"recent_matches": {"data": [{
                "id": "new", "player1Id": 1, "player2Id": 2, "match_winner": 1,
                "result_type": "completed", "result": "6-4 6-4",
                "date": "2026-10-02T10:00:00+00:00",
            }]}}}), encoding="utf-8")
            manifest.write_text(json.dumps({
                "schema_version": 1, "change_id": forward_only.CHANGE_ID,
                "status": "ACTIVE", "effective_from_utc": "2026-09-30T10:00:00+00:00",
                "protected": {
                    "snapshots": {"identity_tokens": [], "records": []},
                    "paper": {"identity_tokens": [], "records": []},
                    "market_ledger": {"identity_tokens": [], "records": []},
                },
            }), encoding="utf-8")
            patches = (
                patch.object(maintenance, "ROOT", root),
                patch.object(maintenance, "SNAPSHOTS_PATH", snapshots),
                patch.object(maintenance, "PAPER_PATH", paper),
                patch.object(maintenance, "LEDGER_ROOT", ledger),
                patch.object(maintenance.market_memory_report, "build_and_write", return_value={"observation_count": 0}),
                patch.object(maintenance.market_ledger, "rotate_archives", return_value=[]),
                patch.object(maintenance.green_strong_validation, "build_and_write", return_value={}),
                patch.object(maintenance.dashboard, "build_and_write_best_effort", return_value={"status": "AVAILABLE"}),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
                first = maintenance.run(
                    checkpoint_path=checkpoint, batch_size=1,
                    manifest_path=manifest,
                )
                second = maintenance.run(
                    checkpoint_path=checkpoint, batch_size=1,
                    manifest_path=manifest,
                )
            self.assertEqual(first["status"], "COMPLETED")
            self.assertEqual(first["phases"]["snapshot_settlement"]["settled"], 1)
            self.assertEqual(second["status"], "NO_ELIGIBLE_WORK")
            self.assertEqual(
                json.loads(checkpoint.read_text(encoding="utf-8"))["cursors"]["snapshots"],
                "new",
            )
            saved = json.loads(snapshots.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["outcome"]["winner_side"], "a")

    def test_no_eligible_work_does_not_rebuild_historic_projections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "data/calibration_snapshots.json"
            paper = root / "data/paper_trades.json"
            checkpoint = root / "data/maintenance/settlement-v1.json"
            snapshots.parent.mkdir(parents=True)
            snapshots.write_text(
                json.dumps({"schema_version": 1, "snapshots": []}), encoding="utf-8",
            )
            paper.write_text(
                json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8",
            )
            with (
                patch.object(maintenance, "ROOT", root),
                patch.object(maintenance, "SNAPSHOTS_PATH", snapshots),
                patch.object(maintenance, "PAPER_PATH", paper),
                patch.object(maintenance.market_memory_report, "build_and_write") as memory,
                patch.object(maintenance.green_strong_validation, "build_and_write") as green,
                patch.object(maintenance.dashboard, "build_and_write_best_effort") as dashboard,
            ):
                report = maintenance.run(checkpoint_path=checkpoint)
            self.assertEqual(report["status"], "NO_ELIGIBLE_WORK")
            memory.assert_not_called()
            green.assert_not_called()
            dashboard.assert_not_called()

    def test_timeout_after_confirmed_batch_keeps_resumable_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "data/calibration_snapshots.json"
            paper = root / "data/paper_trades.json"
            checkpoint = root / "data/maintenance/settlement-v1.json"
            manifest = root / "manifest.json"
            snapshots.parent.mkdir(parents=True)
            snapshots.write_text(json.dumps({
                "schema_version": 1,
                "snapshots": [{
                    "key": "new", "event_key": "new", "match_id": "new", "tour": "atp",
                    "commence_time_utc": "2026-10-02T10:00:00+00:00",
                    "analyzed_at_utc": "2026-10-01T08:00:00+00:00",
                    "player_a": {"id": 1}, "player_b": {"id": 2},
                    "metrics": {}, "outcome": None,
                }],
            }), encoding="utf-8")
            paper.write_text(
                json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8",
            )
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "change_id": forward_only.CHANGE_ID,
                "status": "ACTIVE",
                "effective_from_utc": "2026-09-30T10:00:00+00:00",
                "protected": {
                    "snapshots": {"identity_tokens": [], "records": []},
                    "paper": {"identity_tokens": [], "records": []},
                    "market_ledger": {"identity_tokens": [], "records": []},
                },
            }), encoding="utf-8")

            calls = 0

            def clock():
                nonlocal calls
                calls += 1
                return 0.0 if calls <= 5 else 2.0

            with (
                patch.object(maintenance, "ROOT", root),
                patch.object(maintenance, "SNAPSHOTS_PATH", snapshots),
                patch.object(maintenance, "PAPER_PATH", paper),
                patch.object(maintenance.time, "monotonic", side_effect=clock),
            ):
                report = maintenance.run(
                    checkpoint_path=checkpoint,
                    batch_size=1,
                    deadline_seconds=1,
                    manifest_path=manifest,
                )
            self.assertEqual(report["status"], "TIMED_OUT")
            self.assertEqual(
                json.loads(checkpoint.read_text(encoding="utf-8"))["cursors"]["snapshots"],
                "new",
            )
            self.assertIsNone(
                json.loads(snapshots.read_text(encoding="utf-8"))["snapshots"][0]["outcome"],
            )


if __name__ == "__main__":
    unittest.main()
