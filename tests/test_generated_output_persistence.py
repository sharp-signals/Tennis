from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import odds_monitor, refresh_observability
from scripts.publish_generated_changes import publish
from scripts.recover_generated_outputs import create_recovery, restore
from scripts.stage_generated_outputs import stage


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def init_repo(root: Path) -> None:
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "data").mkdir()
    (root / "data/run_metrics_log.json").write_text("[]\n", encoding="utf-8")
    git(root, "add", "data/run_metrics_log.json")
    git(root, "commit", "-m", "base")


class GeneratedOutputPersistenceTests(unittest.TestCase):
    def test_real_odds_monitor_cache_writer_stages_and_recovers_event_map_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, artifact, fresh = base / "repo", base / "artifact", base / "fresh"
            root.mkdir(); fresh.mkdir()
            init_repo(root)
            output_dir = root / "data/odds_monitor"
            event_map_path = output_dir / "event_map.json"
            status_path = output_dir / "status.json"
            identity_store = odds_monitor.fetch_data.JsonCacheStore(root / "data/cache")
            identity_path = identity_store.entity_path("rapidapi_event_identity.json")
            now = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
            start = now + timedelta(hours=12)
            entry = {
                "key": "atp:monitor-cache:moneyline:a:na",
                "pregame": {
                    "match_id": "monitor-cache", "snapshot_key": "atp:monitor-cache",
                    "tour": "atp", "commence_time_utc": start.isoformat(),
                    "players": {
                        "a": {"id": 10, "name": "Alpha One"},
                        "b": {"id": 20, "name": "Beta Two"},
                    },
                },
            }
            embedded_event = {
                "eventId": "event-monitor-cache",
                "player1": {"id": 10, "name": "Alpha One", "odd": 1.8},
                "player2": {"id": 20, "name": "Beta Two", "odd": 2.1},
                "status": "scheduled", "startTime": start.isoformat(),
                "_tour": "atp", "_odds_captured_at_utc": now.isoformat(),
                "_odds_endpoint": "synthetic://blocked-network",
                "_raw_payload_sha256": "synthetic-payload-hash",
            }
            synthetic_event = {
                "ok": True, "http_status": 200, "access": "allowed", "error": None,
                "payload": {"event": {
                    "eventId": "event-monitor-cache",
                    "participant1": "Alpha One", "participant2": "Beta Two",
                    "status": "scheduled", "startTime": start.isoformat(),
                }},
            }
            with ExitStack() as stack:
                for target, name, value in (
                    (odds_monitor, "OUTPUT_DIR", output_dir),
                    (odds_monitor, "EVENT_MAP_PATH", event_map_path),
                    (odds_monitor, "STATUS_PATH", status_path),
                    (odds_monitor, "PREMIUM_ENDPOINTS_ENABLED", False),
                    (odds_monitor.fetch_data, "_EVENT_IDENTITY_STORE", identity_store),
                    (odds_monitor.fetch_data, "_EVENT_IDENTITY_PATH", identity_path),
                    (odds_monitor.fetch_data, "_ALL_UPCOMING_EVENTS_CACHE", [embedded_event]),
                    (odds_monitor.fetch_data, "_RAPIDAPI_EVENT_INDEX_READY", set()),
                    (odds_monitor.fetch_data, "_RAPIDAPI_EVENT_INDEX", {}),
                    (odds_monitor.fetch_data, "_RAPIDAPI_EMBEDDED_ODDS", {}),
                ):
                    stack.enter_context(patch.object(target, name, value))
                stack.enter_context(patch.object(odds_monitor, "_utc_now", return_value=now))
                stack.enter_context(patch.object(
                    odds_monitor, "load_open_paper_entries", return_value=[entry],
                ))
                stack.enter_context(patch.object(
                    odds_monitor.fetch_data, "reset_rapidapi_call_count",
                ))
                stack.enter_context(patch.object(
                    odds_monitor.fetch_data, "_get_upcoming_page",
                    side_effect=AssertionError("network blocked"),
                ))
                stack.enter_context(patch.object(
                    odds_monitor.fetch_data, "_fetch_extend_event_bridge_records",
                    side_effect=AssertionError("network fallback blocked"),
                ))
                request = stack.enter_context(patch.object(
                    odds_monitor, "_request", return_value=synthetic_event,
                ))
                stack.enter_context(patch.object(
                    odds_monitor, "_primary_market_observation",
                    return_value={"available": False},
                ))
                stack.enter_context(patch.object(
                    odds_monitor, "_append_snapshot", return_value=False,
                ))
                stack.enter_context(patch.object(
                    odds_monitor, "_persist_market_ledger_best_effort",
                    return_value={"recorded": 0, "errors": []},
                ))
                stack.enter_context(patch.object(odds_monitor.market_ledger, "rotate_archives"))
                stack.enter_context(patch.object(
                    odds_monitor.fetch_data, "persist_rapidapi_usage",
                ))
                status = odds_monitor.run()

            request.assert_called_once()
            self.assertEqual(status["captured_entries"], 1)
            written = json.loads(event_map_path.read_text(encoding="utf-8"))
            self.assertEqual(
                written["events"][entry["key"]]["event_id"], "event-monitor-cache",
            )
            identity_cache = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(
                identity_cache["entries"]["fixture:monitor-cache"]["data"]["event_id"],
                "event-monitor-cache",
            )
            expected = event_map_path.read_bytes()
            expected_identity = identity_path.read_bytes()
            staged = stage(root=root, profile="odds-source")
            self.assertIn("data/odds_monitor/event_map.json", staged)
            self.assertIn("data/odds_monitor/status.json", staged)
            self.assertIn("data/cache/rapidapi_event_identity.json", staged)

            document = create_recovery(
                root=root, target=artifact, profile="odds-source",
                reason="TEST_REAL_MONITOR_CACHE", remote_ref="HEAD",
            )
            recovered = {item["path"] for item in document["files"]}
            self.assertIn("data/odds_monitor/event_map.json", recovered)
            self.assertIn("data/cache/rapidapi_event_identity.json", recovered)
            restore(artifact=artifact, root=fresh)
            self.assertEqual(
                (fresh / "data/odds_monitor/event_map.json").read_bytes(), expected,
            )
            self.assertEqual(
                (fresh / "data/cache/rapidapi_event_identity.json").read_bytes(),
                expected_identity,
            )

    def test_real_observability_writer_stages_and_recovers_market_memory_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, artifact, fresh = base / "repo", base / "artifact", base / "fresh"
            root.mkdir(); fresh.mkdir()
            init_repo(root)
            inputs = {
                "data/calibration_snapshots.json": '{"snapshots":[]}\n',
                "data/paper_trades.json": '{"entries":[]}\n',
                "data/manual_paper_22bet.json": '{}\n',
                "data/paper_integrity_exclusions.json": '{"exclusions":[]}\n',
                "data/validation/market-integrity-exclusions-v1.json": '{"exclusions":[]}\n',
            }
            for relative, value in inputs.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
            git(root, "add", "."); git(root, "commit", "-m", "local observability inputs")

            statuses = refresh_observability.refresh(root)
            self.assertEqual(statuses["market_memory"], "AVAILABLE")
            derived = root / "data/market_ledger/derived/market-memory-v1.json"
            expected = derived.read_bytes()
            staged = stage(root=root, profile="observability")
            self.assertIn("data/market_ledger/derived/market-memory-v1.json", staged)
            # The observability writer may promote a verified manual Sheet
            # aggregate to the authoritative dashboard input.  It must be
            # publishable by this same restricted writer profile.
            (root / "data/manual_paper_22bet_authoritative.json").write_text(
                '{"schema_version":2}\n', encoding="utf-8",
            )
            staged = stage(root=root, profile="observability")
            self.assertIn("data/manual_paper_22bet_authoritative.json", staged)

            document = create_recovery(
                root=root, target=artifact, profile="observability",
                reason="TEST_REAL_OBSERVABILITY", remote_ref="HEAD",
            )
            recovered = {item["path"] for item in document["files"]}
            self.assertIn("data/market_ledger/derived/market-memory-v1.json", recovered)
            restore(artifact=artifact, root=fresh)
            self.assertEqual(
                (fresh / "data/market_ledger/derived/market-memory-v1.json").read_bytes(),
                expected,
            )

    def test_optional_absent_path_does_not_break_explicit_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "data/run_metrics_log.json").write_text('[{"ok":true}]\n', encoding="utf-8")
            self.assertEqual(stage(root=root, profile="bot"), ["data/run_metrics_log.json"])
            self.assertIn("data/run_metrics_log.json", git(root, "diff", "--cached", "--name-only"))

    def test_untracked_bytes_round_trip_without_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, artifact, fresh = base / "repo", base / "artifact", base / "fresh"
            root.mkdir(); fresh.mkdir()
            init_repo(root)
            observation = root / "data/market_ledger/observations/2026-10-01.jsonl"
            observation.parent.mkdir(parents=True)
            value = b'{"observation_id":"one"}\n'
            observation.write_bytes(value)
            document = create_recovery(
                root=root, target=artifact, profile="bot", reason="TEST", remote_ref="HEAD",
            )
            self.assertEqual(document["files"][0]["sha256"], __import__("hashlib").sha256(value).hexdigest())
            restore(artifact=artifact, root=fresh)
            restore(artifact=artifact, root=fresh)
            self.assertEqual((fresh / observation.relative_to(root)).read_bytes(), value)

    def test_validation_is_repeated_after_rebase(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bare, root, recovery = base / "remote.git", base / "repo", base / "recovery"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
            root.mkdir(); init_repo(root)
            git(root, "remote", "add", "origin", str(bare))
            git(root, "push", "-u", "origin", "main")
            (root / "data/run_metrics_log.json").write_text('[{"run":1}]\n', encoding="utf-8")
            git(root, "add", "data/run_metrics_log.json"); git(root, "commit", "-m", "generated")
            counter = base / "counter"
            validator = base / "validator.py"
            validator.write_text(
                "import pathlib,sys\np=pathlib.Path(sys.argv[1]); n=int(p.read_text() or 0) if p.exists() else 0; p.write_text(str(n+1)); raise SystemExit(0 if n==0 else 1)\n",
                encoding="utf-8",
            )
            with self.assertRaises(subprocess.CalledProcessError):
                publish(
                    root=root, profile="bot", title="test", recovery_dir=recovery,
                    validation_command=[sys.executable, str(validator), str(counter)], retries=1,
                )
            self.assertEqual(counter.read_text(), "2")
            manifest = json.loads((recovery / "recovery-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reason_code"], "FORWARD_ONLY_VALIDATION_FAILED_AFTER_REBASE")


if __name__ == "__main__":
    unittest.main()
