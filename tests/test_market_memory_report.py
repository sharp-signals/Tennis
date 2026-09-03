import json
import tempfile
import unittest
from pathlib import Path

from src import market_ledger, market_memory_report, paper_trading


class MarketMemoryReportTests(unittest.TestCase):
    def test_report_links_market_and_frozen_sharp_without_recalculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ledger"
            match = {
                "id": 9, "_tour": "wta", "date": "2026-09-03T15:00:00+00:00",
                "player1Id": 1, "player2Id": 2,
                "player1": {"name": "Alpha"}, "player2": {"name": "Beta"},
            }
            base_provenance = {
                "source": "RapidAPI Tennis API / recent-odds",
                "endpoint": "https://provider.test/recent/9",
                "event_id": "e9", "capture_kind": "observed", "bookmaker": "Book",
                "freshness_status": "OBSERVED_AT_CAPTURE", "identity_mapping_status": "VERIFIED",
                "raw_payload_sha256": market_ledger.payload_sha256({"event": 9}),
            }
            entry_provenance = {**base_provenance, "captured_at_utc": "2026-09-03T10:00:00+00:00"}
            close_provenance = {**base_provenance, "captured_at_utc": "2026-09-03T14:00:00+00:00"}
            entry = market_ledger.build_observation(
                match, {"Alpha": 2.1, "Beta": 1.8}, entry_provenance,
                role="OPERATIONAL_PRICING", pipeline="PRELIVE",
            )
            close = market_ledger.build_observation(
                match, {"Alpha": 1.9, "Beta": 1.95}, close_provenance,
                role="SHADOW_MONITOR", pipeline="ODDS_MONITOR",
            )
            market_ledger.append_observation(entry, root=root)
            market_ledger.append_observation(close, root=root)

            snapshots_path = Path(tmp) / "snapshots.json"
            snapshots_path.write_text(json.dumps({"snapshots": [{
                "key": "wta:9", "event_key": "wta:9", "report_id": "r9", "match_id": 9,
                "commence_time_utc": "2026-09-03T15:00:00+00:00",
                "player_a": {"id": 1, "name": "Alpha"}, "player_b": {"id": 2, "name": "Beta"},
                "entry_market_observation_id": entry["observation_id"],
                "pricing": {
                    "available": True, "model_version": "frozen-v1", "configuration_fingerprint": "cfg1",
                    "players": {"a": {"sharp_estimate_pct": 55}, "b": {"sharp_estimate_pct": 45}},
                },
                "outcome": {"winner_side": "a"},
            }]}), encoding="utf-8")
            paper_path = Path(tmp) / "paper.json"
            paper_path.write_text(json.dumps({"entries": [{
                "key": "wta:9:moneyline:a:na", "pregame": {
                    "snapshot_key": "wta:9", "event_key": "wta:9", "selected_side": "a",
                    "commence_time_utc": "2026-09-03T15:00:00+00:00",
                    "entry_market_observation_id": entry["observation_id"],
                }, "settlement": {"result": "WIN"},
            }]}), encoding="utf-8")

            report = market_memory_report.build_report(
                ledger_root=root, snapshots_path=snapshots_path, paper_path=paper_path,
            )
            row = report["events"][0]
            self.assertEqual(row["market_only_prediction"], "b")
            self.assertEqual(row["market_plus_sharp_prediction"], "a")
            self.assertEqual(row["pricing_model_version"], "frozen-v1")
            self.assertEqual(row["last_valid_prestart_market_observation_id"], close["observation_id"])
            self.assertGreater(row["paper"][0]["clv_probability_pp"], 0)
            self.assertEqual(report["evaluation"]["market_only"]["sample_size"], 1)
            self.assertEqual(report["evaluation"]["market_plus_sharp"]["sample_size"], 1)
            self.assertEqual(report["mode"], "SHADOW_ANALYTICS")

    def test_legacy_snapshot_remains_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ledger"
            snapshots = Path(tmp) / "snapshots.json"
            snapshots.write_text(json.dumps({"snapshots": [{
                "key": "atp:old", "commence_time_utc": "2026-01-01T10:00:00+00:00",
                "pricing": None, "outcome": None,
            }]}), encoding="utf-8")
            report = market_memory_report.build_report(
                ledger_root=root, snapshots_path=snapshots, paper_path=Path(tmp) / "missing.json",
            )
            self.assertEqual(report["events"][0]["availability"], {
                "entry_market": "UNAVAILABLE", "closing_market": "UNAVAILABLE",
                "market_plus_sharp": "UNAVAILABLE",
            })

    def test_paper_settlement_continues_when_market_memory_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper_path = Path(tmp) / "paper.json"
            paper_path.write_text(json.dumps({"schema_version": 1, "entries": [{
                "key": "atp:7:moneyline:a:na", "mode": "PAPER",
                "pregame": {
                    "match_id": 7, "selected_side": "a", "market_type": "Moneyline", "odd": 2.0,
                    "players": {"a": {"id": 1}, "b": {"id": 2}},
                    "market_memory_eligible": True, "entry_market_observation_id": "missing",
                }, "settlement": None,
            }]}), encoding="utf-8")
            corrupt_root = Path(tmp) / "ledger"
            corrupt = corrupt_root / "observations" / "2026-09-03.jsonl"
            corrupt.parent.mkdir(parents=True)
            corrupt.write_text("not-json\n", encoding="utf-8")
            settled = paper_trading.settle_from_matches([{
                "id": 7, "match_winner": 1, "result_type": "completed", "result": "6-4 6-4",
            }], paper_path, ledger_root=corrupt_root)
            saved = paper_trading.read_entries(paper_path)[0]
            self.assertEqual(settled, 1)
            self.assertEqual(saved["settlement"]["result"], "WIN")
            self.assertEqual(saved["settlement"]["market_memory_status"], "UNAVAILABLE")
            self.assertIn("MarketLedgerError", saved["settlement"]["market_memory_error"])


if __name__ == "__main__":
    unittest.main()
