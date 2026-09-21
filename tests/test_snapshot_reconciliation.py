import json
import tempfile
import unittest
from pathlib import Path

from src import (
    calibration_store,
    market_integrity,
    paper_trading,
    snapshot_identity,
    snapshot_reconciliation,
)


def payload(*, match_id=861, a_id=1, b_id=2, a="Old A", b="Old B"):
    return {
        "match_id": match_id,
        "tour": "wta",
        "tournament_id": 10,
        "commence_time_utc": "2026-09-20T12:00:00+00:00",
        "player_a_id": a_id,
        "player_b_id": b_id,
        "player_a": a,
        "player_b": b,
        "odds_operational_pricing_eligible": True,
        "odds_source_contract_version": market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
        "odds_source_contract_fingerprint": market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
        "pricing": {
            "available": True,
            "odds_source_contract_version": market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
            "odds_source_contract_fingerprint": market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
        },
        "prelive_decision": {
            "paper_eligible": True,
            "paper_markets": [{
                "market_type": "Moneyline", "side": "a", "player": a, "odd": 2.0,
            }],
        },
    }


class SnapshotIdentityContainmentTests(unittest.TestCase):
    def test_reused_provider_id_is_typed_and_blocks_validation_and_paper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.json"
            original = calibration_store.build_snapshot(payload(), analyzed_at_utc="2026-09-19T09:00:00+00:00")
            self.assertEqual(calibration_store.upsert_snapshots([original], path), 1)

            current_payload = payload(a_id=3, b_id=4, a="New A", b="New B")
            candidate = calibration_store.build_snapshot(current_payload, analyzed_at_utc="2026-09-20T09:00:00+00:00")
            self.assertEqual(candidate["key"], original["key"])
            self.assertEqual(calibration_store.upsert_snapshots([candidate], path), 0)
            persisted = calibration_store.read_snapshots_by_key([candidate["key"]], path)[candidate["key"]]
            linkage = calibration_store.apply_persisted_validation(current_payload, persisted)

            self.assertEqual(linkage["status"], "COLLISION")
            self.assertEqual(linkage["reason_code"], "PROVIDER_MATCH_ID_REUSED")
            self.assertEqual(linkage["detail_reason_code"], "SNAPSHOT_IDENTITY_COLLISION")
            self.assertNotIn("validation", current_payload)
            self.assertEqual(paper_trading.build_entries(current_payload), [])
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["player_a"]["id"], 1)

    def test_same_real_match_rerun_preserves_first_write_and_reuses_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots.json"
            first_payload = payload()
            first = calibration_store.build_snapshot(first_payload, analyzed_at_utc="2026-09-20T08:00:00+00:00")
            rerun = calibration_store.build_snapshot(first_payload, analyzed_at_utc="2026-09-20T09:00:00+00:00")
            self.assertEqual(calibration_store.upsert_snapshots([first], path), 1)
            self.assertEqual(calibration_store.upsert_snapshots([rerun], path), 0)
            persisted = calibration_store.read_snapshots_by_key([first["key"]], path)[first["key"]]
            linkage = calibration_store.apply_persisted_validation(first_payload, persisted)
            self.assertEqual(linkage["status"], "LINKED")
            self.assertIn("validation", first_payload)
            self.assertEqual(persisted["report_id"], first["report_id"])

    def test_settlement_same_id_with_different_players_does_not_settle(self):
        completed_collision = {
            "id": 861,
            "player1Id": 3,
            "player2Id": 4,
            "match_winner": 3,
            "result_type": "completed",
            "date": "2026-09-20T12:00:00+00:00",
            "result": "6-4 6-4",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots.json"
            original_payload = payload()
            snapshot = calibration_store.build_snapshot(original_payload, analyzed_at_utc="2026-09-20T08:00:00+00:00")
            calibration_store.upsert_snapshots([snapshot], snapshots)
            self.assertEqual(calibration_store.settle_from_matches([completed_collision], snapshots), 0)
            self.assertIsNone(calibration_store.read_snapshots_by_key([snapshot["key"]], snapshots)[snapshot["key"]]["outcome"])

            paper_path = root / "paper.json"
            original_payload.update({
                "snapshot_key": snapshot["key"], "report_id": snapshot["report_id"],
                "analyzed_at_utc": snapshot["analyzed_at_utc"],
            })
            paper_trading.append_entries(paper_trading.build_entries(original_payload), paper_path)
            self.assertEqual(paper_trading.settle_from_matches([completed_collision], paper_path), 0)
            self.assertIsNone(paper_trading.read_entries(paper_path)[0]["settlement"])

    def test_time_and_tournament_are_deterministic_context_guards(self):
        base = payload()
        snapshot = calibration_store.build_snapshot(base, analyzed_at_utc="2026-09-20T08:00:00+00:00")
        later = dict(base, commence_time_utc="2026-09-23T12:01:00+00:00")
        comparison = snapshot_identity.compare(later, snapshot)
        self.assertEqual(comparison["status"], snapshot_identity.COLLISION)
        self.assertEqual(comparison["conflict"], "COMMENCE_TIME_OUTSIDE_TOLERANCE")
        other_tournament = dict(base, tournament_id=11)
        self.assertEqual(
            snapshot_identity.compare(other_tournament, snapshot)["conflict"],
            "TOURNAMENT_ID_MISMATCH",
        )


class SnapshotCoverageReconciliationTests(unittest.TestCase):
    def test_week_fixture_fully_explains_100_versions_67_matchups_and_65_identities(self):
        reports = []
        for index in range(100):
            reports.append({
                "date": "2026-09-21",
                "linkage": "EXACT_REPORT_ID" if index < 2 else "SELF_DESCRIBED_REPORT",
                "self_described": index >= 2,
            })
        days = [{"date": "2026-09-21", "counts": {"reports": 100, "matchups": 67}}]
        snapshots = []
        matches = []
        for index in range(65):
            key = f"wta:{800 + index}"
            same = index < 2
            current_names = [f"Current A {index}", f"Current B {index}"]
            stored_names = current_names if same else [f"Old A {index}", f"Old B {index}"]
            snapshots.append({
                "key": key,
                "tour": "wta",
                "player_a": {"name": stored_names[0]},
                "player_b": {"name": stored_names[1]},
                "analyzed_at_utc": "2026-09-19T10:00:00+00:00" if same else "2026-08-20T10:00:00+00:00",
                "outcome": {"winner_side": "a"} if index == 0 else None,
            })
            matches.append({
                "match_key": str(800 + index), "tour": "wta", "players": current_names,
            })
        runs = [{
            "timestamp": "2026-09-20T17:00:00+00:00",
            "event_identity": {"matches": matches},
        }]
        result = snapshot_reconciliation.build(
            reports=reports,
            days=days,
            snapshots=snapshots,
            runs=runs,
            generated_at_utc="2026-09-21T12:00:00+00:00",
        )
        counts = result["counts"]
        self.assertEqual(counts["report_versions"], 100)
        self.assertEqual(counts["matchups_observed"], 67)
        self.assertEqual(counts["duplicate_report_versions"], 33)
        self.assertEqual(counts["linked_exact_versions"], 2)
        self.assertEqual(counts["self_described_versions"], 98)
        self.assertEqual(counts["eligible_run_identities"], 65)
        self.assertEqual(counts["snapshot_identity_matches"], 2)
        self.assertEqual(counts["provider_match_id_collisions"], 63)
        self.assertEqual(counts["eligible_without_snapshot"], 63)
        self.assertEqual(counts["snapshots_created"], 2)
        self.assertEqual(counts["snapshots_settled"], 1)
        self.assertEqual(result["conversion"]["eligible_to_snapshot_pct"], 3.08)
        self.assertTrue(result["integrity"]["eligible_identities_reconciled"])
        self.assertTrue(result["integrity"]["versions_reconciled"])
        self.assertTrue(result["integrity"]["no_backfill"])
        self.assertEqual(result["absence_reason_codes"]["PROVIDER_MATCH_ID_REUSED"], 63)
        self.assertEqual(result["absence_reason_codes"]["DUPLICATE_REPORT_VERSION"], 33)
        self.assertEqual(result["absence_reason_codes"]["OBSERVED_MATCHUP_WITHOUT_IDENTITY_TELEMETRY"], 2)


if __name__ == "__main__":
    unittest.main()
