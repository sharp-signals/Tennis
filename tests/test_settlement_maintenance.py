import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_settlement_maintenance as supervisor
from scripts import update_calibration_outcomes as maintenance
from src import forward_only


def _write_active_manifest(path: Path) -> None:
    section = {"count": 0, "identity_tokens": [], "records": [], "weak_alias_contexts": {}}
    document = {
        "schema_version": 1, "change_id": forward_only.CHANGE_ID,
        "status": "ACTIVE", "effective_from_utc": "2026-09-30T10:00:00+00:00",
        "code_commit": "code", "data_base_commit": "data",
        "protected": {
            "snapshots": dict(section), "paper": dict(section), "market_ledger": dict(section),
            "published_reports": {"count": 0, "files": []},
            "exclusions": [], "historic_aggregate_references": [],
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    forward_only.activation_lock_path(path).write_text(json.dumps({
        "schema_version": 1, "change_id": forward_only.CHANGE_ID,
        "effective_from_utc": document["effective_from_utc"],
        "manifest_sha256": forward_only.canonical_sha256(document),
        "code_commit": "code", "data_base_commit": "data",
    }), encoding="utf-8")


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
            _write_active_manifest(manifest)
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
            _write_active_manifest(manifest)

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

    def test_external_supervisor_persists_real_subprocess_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "settlement.json"
            code = (
                "import json,pathlib,time;"
                f"p=pathlib.Path({str(checkpoint)!r});"
                "p.write_text(json.dumps({'schema_version':1,'cursors':{},'last_run':"
                "{'status':'IN_PROGRESS','phases':{'dashboard':{'status':'IN_PROGRESS'}}}}));"
                "time.sleep(10)"
            )
            report = supervisor.supervise(
                command=[sys.executable, "-c", code],
                checkpoint_path=checkpoint,
                timeout_seconds=0.1,
            )
            self.assertEqual(report["status"], "TIMED_OUT")
            self.assertEqual(
                json.loads(checkpoint.read_text(encoding="utf-8"))["last_run"]["status"],
                "TIMED_OUT",
            )
            # A fresh process/workspace reader sees the durable terminal state.
            self.assertEqual(
                maintenance._read_checkpoint(checkpoint)["last_run"]["reason_code"],
                "SETTLEMENT_MAINTENANCE_EXTERNAL_TIMEOUT",
            )
            self.assertEqual(report["phases"]["dashboard"]["status"], "IN_PROGRESS")

    def test_more_candidates_than_batch_is_partial_and_cursor_is_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "data/calibration_snapshots.json"
            paper = root / "data/paper_trades.json"
            checkpoint = root / "data/maintenance/settlement-v1.json"
            snapshots.parent.mkdir(parents=True)
            snapshots.write_text('{"snapshots":[]}\n', encoding="utf-8")
            paper.write_text('{"entries":[]}\n', encoding="utf-8")

            def settle_snapshots(*_args, diagnostics, **_kwargs):
                diagnostics.update({
                    "examined": 1, "last_examined_key": "a", "pending_no_result": 1,
                    "deadline_reached": False, "blocked": {},
                })
                return 0

            def settle_paper(*_args, diagnostics, **_kwargs):
                diagnostics.update({
                    "examined": 0, "last_examined_key": None, "pending_no_result": 0,
                    "deadline_reached": False, "blocked": {},
                })
                return 0

            with (
                patch.object(maintenance, "ROOT", root),
                patch.object(maintenance, "SNAPSHOTS_PATH", snapshots),
                patch.object(maintenance, "PAPER_PATH", paper),
                patch.object(maintenance, "_pending_keys", side_effect=lambda name, *_: ["a", "b"] if name == "snapshots" else []),
                patch.object(maintenance.calibration_store, "settle_from_matches", side_effect=settle_snapshots),
                patch.object(maintenance.paper_trading, "settle_from_matches", side_effect=settle_paper),
            ):
                report = maintenance.run(checkpoint_path=checkpoint, batch_size=1)
            self.assertEqual(report["status"], "PARTIAL")
            self.assertEqual(report["candidates"]["snapshots"], {
                "eligible_pending": 2, "batch_size": 1, "examined": 1,
                "pending_no_result": 1, "remaining_unexamined": 1,
            })
            self.assertEqual(maintenance._read_checkpoint(checkpoint)["cursors"]["snapshots"], "a")
            self.assertEqual(maintenance._batch(["a", "b"], "a", 1), ["b"])

    def test_paper_deadline_with_zero_settlements_and_remaining_work_is_timed_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "data/calibration_snapshots.json"
            paper = root / "data/paper_trades.json"
            checkpoint = root / "data/maintenance/settlement-v1.json"
            snapshots.parent.mkdir(parents=True)
            snapshots.write_text('{"snapshots":[]}\n', encoding="utf-8")
            paper.write_text('{"entries":[]}\n', encoding="utf-8")

            def settle_snapshots(*_args, diagnostics, **_kwargs):
                diagnostics.update({
                    "examined": 0, "pending_no_result": 0,
                    "deadline_reached": False, "blocked": {},
                })
                return 0

            def settle_paper(*_args, diagnostics, **_kwargs):
                diagnostics.update({
                    "examined": 0, "pending_no_result": 0,
                    "deadline_reached": True, "blocked": {},
                })
                return 0

            with (
                patch.object(maintenance, "ROOT", root),
                patch.object(maintenance, "SNAPSHOTS_PATH", snapshots),
                patch.object(maintenance, "PAPER_PATH", paper),
                patch.object(
                    maintenance, "_pending_keys",
                    side_effect=lambda name, *_: [] if name == "snapshots" else ["p1", "p2"],
                ),
                patch.object(
                    maintenance.calibration_store, "settle_from_matches",
                    side_effect=settle_snapshots,
                ),
                patch.object(
                    maintenance.paper_trading, "settle_from_matches",
                    side_effect=settle_paper,
                ),
            ):
                report = maintenance.run(checkpoint_path=checkpoint, batch_size=2)
            self.assertEqual(report["status"], "TIMED_OUT")
            self.assertEqual(report["candidates"]["paper"]["remaining_unexamined"], 2)
            self.assertEqual(report["work"]["examined"], 0)

    def test_child_nonzero_after_in_progress_is_durably_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / "settlement.json"
            metrics = root / "run_metrics.json"
            metrics.write_text('[{"github_run_id":"run-1"}]\n', encoding="utf-8")
            code = (
                "import json,pathlib,sys;"
                f"p=pathlib.Path({str(checkpoint)!r});"
                "p.write_text(json.dumps({'schema_version':1,'cursors':{},'last_run':"
                "{'status':'IN_PROGRESS','phases':{'paper_settlement':{'status':'IN_PROGRESS'}}}}));"
                "sys.exit(7)"
            )
            report = supervisor.supervise(
                command=[sys.executable, "-c", code],
                checkpoint_path=checkpoint,
                timeout_seconds=5,
                metrics_path=metrics,
                github_run_id="run-1",
            )
            self.assertEqual(report["status"], "FAILED")
            self.assertEqual(
                report["reason_code"], "SETTLEMENT_MAINTENANCE_CHILD_NONZERO_EXIT",
            )
            self.assertEqual(
                maintenance._read_checkpoint(checkpoint)["last_run"]["status"], "FAILED",
            )
            persisted = json.loads(metrics.read_text(encoding="utf-8"))[0]
            self.assertEqual(persisted["settlement_maintenance"]["status"], "FAILED")

    def test_rebuild_failure_preserves_settlement_and_resume_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "data/calibration_snapshots.json"
            paper = root / "data/paper_trades.json"
            cache = root / "data/cache/players/1/player.json"
            checkpoint = root / "data/maintenance/settlement-v1.json"
            manifest = root / "manifest.json"
            cache.parent.mkdir(parents=True)
            snapshots.parent.mkdir(parents=True, exist_ok=True)
            snapshots.write_text(json.dumps({"schema_version": 1, "snapshots": [{
                "key": "new", "event_key": "new", "match_id": "new", "tour": "atp",
                "commence_time_utc": "2026-10-02T10:00:00+00:00",
                "analyzed_at_utc": "2026-10-01T08:00:00+00:00",
                "player_a": {"id": 1}, "player_b": {"id": 2},
                "metrics": {}, "outcome": None,
            }]}), encoding="utf-8")
            paper.write_text('{"schema_version":1,"entries":[]}\n', encoding="utf-8")
            cache.write_text(json.dumps({"entries": {"recent_matches": {"data": [{
                "id": "new", "player1Id": 1, "player2Id": 2,
                "match_winner": 1, "result_type": "completed", "result": "6-4 6-4",
                "date": "2026-10-02T10:00:00+00:00",
            }]}}}), encoding="utf-8")
            _write_active_manifest(manifest)
            with (
                patch.object(maintenance, "ROOT", root),
                patch.object(maintenance, "SNAPSHOTS_PATH", snapshots),
                patch.object(maintenance, "PAPER_PATH", paper),
                patch.object(maintenance, "LEDGER_ROOT", root / "data/market_ledger"),
                patch.object(
                    maintenance.market_memory_report, "build_and_write",
                    side_effect=RuntimeError("rebuild failed"),
                ) as rebuild,
            ):
                first = maintenance.run(
                    checkpoint_path=checkpoint, batch_size=1, manifest_path=manifest,
                )
                first_status = first["status"]
                second = maintenance.run(
                    checkpoint_path=checkpoint, batch_size=1, manifest_path=manifest,
                )
            self.assertEqual(first_status, "FAILED")
            self.assertEqual(second["status"], "NO_ELIGIBLE_WORK")
            self.assertEqual(rebuild.call_count, 1)
            saved = json.loads(snapshots.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["outcome"]["winner_side"], "a")


if __name__ == "__main__":
    unittest.main()
