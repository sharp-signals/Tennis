import copy
import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts import validate_forward_only
from src import calibration_store, forward_only, market_ledger, paper_trading


T0 = "2026-09-30T10:00:00+00:00"


def active_manifest(path: Path, *, snapshots=(), paper=(), ledger=()):
    protected = {}
    for collection, records in (
        ("snapshots", snapshots), ("paper", paper), ("market_ledger", ledger),
    ):
        records = list(records)
        protected[collection] = {
            "count": len(records),
            "records": [{
                "identity": forward_only.record_key(collection, item),
                "sha256": forward_only.canonical_sha256(item),
            } for item in records],
            "identity_tokens": sorted(set().union(*(
                forward_only.identity_tokens(collection, item) for item in records
            )) if records else []),
            "weak_alias_contexts": {
                alias: sorted({
                    forward_only.canonical_identity(collection, item)
                    for item in records
                    if alias in forward_only.weak_aliases(collection, item)
                })
                for alias in sorted(set().union(*(
                    forward_only.weak_aliases(collection, item) for item in records
                )) if records else [])
            },
        }
    protected["published_reports"] = {"count": 0, "files": []}
    protected["exclusions"] = []
    protected["historic_aggregate_references"] = []
    document = {
        "schema_version": 1,
        "change_id": forward_only.CHANGE_ID,
        "status": "ACTIVE",
        "effective_from_utc": T0,
        "code_commit": "code",
        "data_base_commit": "data",
        "protected": protected,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    forward_only.activation_lock_path(path).write_text(json.dumps({
        "schema_version": 1,
        "change_id": forward_only.CHANGE_ID,
        "effective_from_utc": T0,
        "manifest_sha256": forward_only.canonical_sha256(document),
        "code_commit": "code",
        "data_base_commit": "data",
    }), encoding="utf-8")


def snapshot(key, *, start="2026-10-01T10:00:00+00:00", analyzed="2026-09-30T09:00:00+00:00"):
    return {
        "key": key,
        "event_key": key,
        "match_id": key,
        "tour": "atp",
        "commence_time_utc": start,
        "analyzed_at_utc": analyzed,
        "player_a": {"id": 1, "name": "A"},
        "player_b": {"id": 2, "name": "B"},
        "metrics": {},
        "outcome": None,
    }


def completed(match_id, *, date="2026-10-01T10:00:00+00:00"):
    return {
        "id": match_id,
        "player1Id": 1,
        "player2Id": 2,
        "match_winner": 1,
        "result_type": "completed",
        "result": "6-4 6-4",
        "date": date,
    }


class ForwardOnlyStabilityTests(unittest.TestCase):
    def test_protected_pending_snapshot_for_future_event_never_settles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "snapshots.json"
            manifest = root / "manifest.json"
            old = snapshot("old-future")
            store.write_text(json.dumps({"schema_version": 1, "snapshots": [old]}), encoding="utf-8")
            active_manifest(manifest, snapshots=[old])
            details = {}
            count = calibration_store.settle_from_matches(
                [completed("old-future")], store,
                protection_manifest_path=manifest, diagnostics=details,
            )
            self.assertEqual(count, 0)
            self.assertIsNone(calibration_store._read(store)["snapshots"][0]["outcome"])
            self.assertEqual(details["blocked"], {"PROTECTED_AT_T0": 1})

    def test_new_ex_ante_snapshot_settles_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "snapshots.json"
            manifest = root / "manifest.json"
            active_manifest(manifest)
            new = snapshot(
                "new", start="2026-10-02T10:00:00+00:00",
                analyzed="2026-10-01T08:00:00+00:00",
            )
            self.assertEqual(calibration_store.upsert_snapshots(
                [new], store, protection_manifest_path=manifest,
            ), 1)
            result = completed("new", date="2026-10-02T10:00:00+00:00")
            self.assertEqual(calibration_store.settle_from_matches(
                [result], store, protection_manifest_path=manifest,
            ), 1)
            self.assertEqual(calibration_store.settle_from_matches(
                [result], store, protection_manifest_path=manifest,
            ), 0)

    def test_old_event_ingested_after_t0_and_missing_time_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "snapshots.json"
            manifest = root / "manifest.json"
            active_manifest(manifest)
            old_event = snapshot(
                "late-ingest", start="2026-09-29T10:00:00+00:00",
                analyzed="2026-10-01T08:00:00+00:00",
            )
            missing = snapshot("missing-time")
            missing["commence_time_utc"] = None
            details = {}
            self.assertEqual(calibration_store.upsert_snapshots(
                [old_event, missing], store,
                protection_manifest_path=manifest, diagnostics=details,
            ), 0)
            self.assertEqual(details["blocked"], {
                "EVENT_NOT_AFTER_FORWARD_ONLY_BOUNDARY": 1,
                "EVENT_TIME_UNAVAILABLE": 1,
            })

    def test_alias_cannot_duplicate_protected_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "snapshots.json"
            manifest = root / "manifest.json"
            old = snapshot("old-key")
            old["canonical_match_instance_id"] = "canonical-1"
            active_manifest(manifest, snapshots=[old])
            alias = copy.deepcopy(old)
            alias.update({
                "key": "new-presentation-key",
                "event_key": "new-presentation-key",
                "analyzed_at_utc": "2026-10-01T08:00:00+00:00",
                "commence_time_utc": "2026-10-02T10:00:00+00:00",
            })
            self.assertEqual(calibration_store.upsert_snapshots(
                [alias], store, protection_manifest_path=manifest,
            ), 0)

    def test_paper_protection_and_new_settlement_share_same_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / "paper.json"
            manifest = root / "manifest.json"
            old = {
                "key": "old:moneyline:a:na", "settlement": None,
                "pregame": {
                    "event_key": "old", "match_id": "old", "tour": "atp",
                    "commence_time_utc": "2026-10-01T10:00:00+00:00",
                    "analyzed_at_utc": "2026-09-30T09:00:00+00:00",
                    "players": {"a": {"id": 1}, "b": {"id": 2}},
                    "selected_side": "a", "market_type": "Moneyline", "odd": 2.0,
                },
            }
            new = copy.deepcopy(old)
            new["key"] = "new:moneyline:a:na"
            new["pregame"].update({
                "event_key": "new", "match_id": "new",
                "commence_time_utc": "2026-10-02T10:00:00+00:00",
                "analyzed_at_utc": "2026-10-01T08:00:00+00:00",
            })
            store.write_text(json.dumps({"schema_version": 1, "entries": [old, new]}), encoding="utf-8")
            active_manifest(manifest, paper=[old])
            count = paper_trading.settle_from_matches(
                [completed("old"), completed("new", date="2026-10-02T10:00:00+00:00")],
                store, protection_manifest_path=manifest, ledger_root=root / "ledger",
            )
            self.assertEqual(count, 1)
            entries = paper_trading.read_entries(store)
            self.assertIsNone(entries[0]["settlement"])
            self.assertEqual(entries[1]["settlement"]["result"], "WIN")

    def test_market_observation_for_pre_t0_event_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            active_manifest(manifest)
            observation = {
                "observation_id": "obs",
                "event": {
                    "event_key": "event", "scheduled_start_utc": "2026-09-29T10:00:00+00:00",
                },
                "capture": {"captured_at_utc": "2026-10-01T08:00:00+00:00"},
            }
            with self.assertRaisesRegex(market_ledger.MarketLedgerError, "EVENT_NOT_AFTER"):
                market_ledger.append_observation(
                    observation, root=root / "ledger", protection_manifest_path=manifest,
                )

    def test_validator_detects_mutation_without_changing_protected_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            old = snapshot("old")
            (root / "data/calibration_snapshots.json").write_text(json.dumps({
                "schema_version": 1, "snapshots": [old],
            }), encoding="utf-8")
            (root / "data/paper_trades.json").write_text(json.dumps({
                "schema_version": 1, "entries": [],
            }), encoding="utf-8")
            (root / "data/market_ledger/observations").mkdir(parents=True)
            (root / "data/market_ledger/archive").mkdir(parents=True)
            manifest = root / "manifest.json"
            active_manifest(manifest, snapshots=[old])
            with patch.object(validate_forward_only, "ROOT", root):
                self.assertEqual(validate_forward_only.validate(manifest, root=root), [])
                changed = copy.deepcopy(old)
                changed["metrics"] = {"rewritten": True}
                (root / "data/calibration_snapshots.json").write_text(json.dumps({
                    "schema_version": 1, "snapshots": [changed],
                }), encoding="utf-8")
                self.assertIn(
                    "snapshots:old:PROTECTED_RECORD_MUTATED",
                    validate_forward_only.validate(manifest, root=root),
                )

    def test_present_invalid_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("{not-json", encoding="utf-8")
            boundary = forward_only.load_boundary(manifest)
            self.assertTrue(boundary.fail_closed)
            self.assertFalse(boundary.new_record_eligibility("snapshots", snapshot("x"))[0])
            self.assertEqual(
                validate_forward_only.validate(manifest, root=Path(tmp)),
                ["ACTIVATION_MANIFEST_INVALID"],
            )

    def test_missing_manifest_after_lock_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            forward_only.activation_lock_path(manifest).write_text("{}", encoding="utf-8")
            boundary = forward_only.load_boundary(manifest)
            self.assertTrue(boundary.fail_closed)
            self.assertEqual(boundary.reason_code, "ACTIVATION_MANIFEST_MISSING_AFTER_ACTIVATION")

    def test_removing_manifest_and_lock_after_ratification_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            manifest = root / "data/governance/manifest.json"
            manifest.parent.mkdir(parents=True)
            active_manifest(manifest)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "activation"], cwd=root, check=True, capture_output=True)
            manifest.unlink()
            forward_only.activation_lock_path(manifest).unlink()
            boundary = forward_only.load_boundary(manifest)
            self.assertTrue(boundary.fail_closed)
            self.assertEqual(boundary.reason_code, "ACTIVATION_MANIFEST_MISSING_AFTER_ACTIVATION")

    def test_wrong_version_and_incomplete_active_inventory_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 999, "change_id": forward_only.CHANGE_ID,
            }), encoding="utf-8")
            self.assertEqual(
                forward_only.load_boundary(manifest).reason_code,
                "ACTIVATION_MANIFEST_CONTRACT_MISMATCH",
            )
            manifest.write_text(json.dumps({
                "schema_version": 1, "change_id": forward_only.CHANGE_ID,
                "status": "ACTIVE", "effective_from_utc": T0, "protected": {},
            }), encoding="utf-8")
            self.assertEqual(
                forward_only.load_boundary(manifest).reason_code,
                "ACTIVATION_INVENTORY_SNAPSHOTS_MISSING",
            )

    def test_coherent_manifest_and_lock_replacement_cannot_move_ratified_t0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            manifest = root / "data/governance/manifest.json"
            manifest.parent.mkdir(parents=True)
            active_manifest(manifest, snapshots=[snapshot("protected")])
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "ratify T0"], cwd=root, check=True, capture_output=True)

            replacement = json.loads(manifest.read_text(encoding="utf-8"))
            replacement["effective_from_utc"] = "2026-10-01T10:00:00+00:00"
            replacement["protected"]["snapshots"] = {
                "count": 0, "records": [], "identity_tokens": [],
                "weak_alias_contexts": {},
            }
            manifest.write_text(json.dumps(replacement), encoding="utf-8")
            lock_path = forward_only.activation_lock_path(manifest)
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock.update({
                "effective_from_utc": replacement["effective_from_utc"],
                "manifest_sha256": forward_only.canonical_sha256(replacement),
            })
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "replace both coherently"], cwd=root, check=True, capture_output=True)

            boundary = forward_only.load_boundary(manifest)
            self.assertTrue(boundary.fail_closed)
            self.assertEqual(boundary.reason_code, "ACTIVATION_RATIFIED_ANCHOR_MISMATCH")
            self.assertEqual(
                validate_forward_only.validate(manifest, root=root),
                ["ACTIVATION_RATIFIED_ANCHOR_MISMATCH"],
            )

    def test_reused_legacy_id_with_distinct_canonical_instance_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            old = snapshot("provider-reused")
            old["canonical_match_instance_id"] = "canonical-old"
            active_manifest(manifest, snapshots=[old])
            new = snapshot(
                "provider-reused", start="2026-10-04T10:00:00+00:00",
                analyzed="2026-10-03T08:00:00+00:00",
            )
            new["canonical_match_instance_id"] = "canonical-new"
            boundary = forward_only.load_boundary(manifest)
            # The per-collection primary key still protects the exact old record.
            new["key"] = "new-storage-key"
            self.assertEqual(
                boundary.new_record_eligibility("snapshots", new),
                (True, "FORWARD_ONLY_ELIGIBLE"),
            )

    def test_reused_numeric_id_in_distinct_tour_and_players_is_not_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            old = snapshot("old-storage")
            old.update({"event_key": "legacy-event", "match_id": 77})
            old.pop("canonical_match_instance_id", None)
            active_manifest(manifest, snapshots=[old])
            new = snapshot(
                "new-storage", start="2026-10-04T10:00:00+00:00",
                analyzed="2026-10-03T08:00:00+00:00",
            )
            new.update({
                "event_key": "new-event", "match_id": 77, "tour": "wta",
                "canonical_match_instance_id": "canonical-new",
                "player_a": {"id": 31, "name": "C"},
                "player_b": {"id": 42, "name": "D"},
            })
            self.assertEqual(
                forward_only.load_boundary(manifest).new_record_eligibility("snapshots", new),
                (True, "FORWARD_ONLY_ELIGIBLE"),
            )

    def test_legacy_without_canonical_does_not_contaminate_distinct_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            old = snapshot("old-storage")
            old.update({"event_key": "old-event", "match_id": 77})
            active_manifest(manifest, snapshots=[old])
            new = snapshot(
                "new-storage", start="2026-10-05T10:00:00+00:00",
                analyzed="2026-10-04T08:00:00+00:00",
            )
            new.update({
                "event_key": "new-event", "match_id": 77,
                "canonical_match_instance_id": "canonical-new",
                "player_a": {"id": 7, "name": "New A"},
                "player_b": {"id": 8, "name": "New B"},
            })
            self.assertEqual(
                forward_only.load_boundary(manifest).new_record_eligibility("snapshots", new),
                (True, "FORWARD_ONLY_ELIGIBLE"),
            )

    def test_context_free_reused_id_remains_explicitly_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            old = {"key": "old", "match_id": 77, "outcome": None}
            active_manifest(manifest, snapshots=[old])
            new = {
                "key": "new", "match_id": 77,
                "canonical_match_instance_id": "canonical-new",
                "commence_time_utc": "2026-10-05T10:00:00+00:00",
                "analyzed_at_utc": "2026-10-04T08:00:00+00:00",
                "outcome": None,
            }
            allowed, reason = forward_only.load_boundary(manifest).new_record_eligibility(
                "snapshots", new,
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "PROTECTED_IDENTITY_AMBIGUOUS")

    def test_protected_instance_cannot_reappear_through_paper_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            old = snapshot("old")
            old["canonical_match_instance_id"] = "canonical-one"
            active_manifest(manifest, snapshots=[old])
            paper = {
                "key": "new-leg", "canonical_match_instance_id": "canonical-one",
                "pregame": {
                    "canonical_match_instance_id": "canonical-one", "event_key": "other-alias",
                    "match_id": "other-alias", "tour": "atp",
                    "commence_time_utc": "2026-10-02T10:00:00+00:00",
                    "analyzed_at_utc": "2026-10-01T08:00:00+00:00",
                    "players": {"a": {"id": 1}, "b": {"id": 2}},
                },
            }
            allowed, reason = forward_only.load_boundary(manifest).new_record_eligibility(
                "paper", paper,
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "PROTECTED_IDENTITY_ALIAS")


if __name__ == "__main__":
    unittest.main()
