import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import odds_monitor


class OddsMonitorTests(unittest.TestCase):
    def test_load_open_paper_entries_only_keeps_future_unsettled_moneyline(self):
        now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        future = (now + timedelta(hours=6)).isoformat()
        past = (now - timedelta(hours=1)).isoformat()
        document = {
            "entries": [
                {
                    "key": "keep",
                    "mode": "PAPER",
                    "pregame": {"market_type": "Moneyline", "commence_time_utc": future},
                    "settlement": None,
                },
                {
                    "key": "settled",
                    "mode": "PAPER",
                    "pregame": {"market_type": "Moneyline", "commence_time_utc": future},
                    "settlement": {"result": "WIN"},
                },
                {
                    "key": "past",
                    "mode": "PAPER",
                    "pregame": {"market_type": "Moneyline", "commence_time_utc": past},
                    "settlement": None,
                },
                {
                    "key": "handicap",
                    "mode": "PAPER",
                    "pregame": {"market_type": "Handicap", "commence_time_utc": future},
                    "settlement": None,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            selected = odds_monitor.load_open_paper_entries(path, now=now)
        self.assertEqual([entry["key"] for entry in selected], ["keep"])

    def test_extract_event_id_prefers_explicit_event_id(self):
        payload = {"success": True, "data": {"player": {"id": 12}, "eventId": 3815731}}
        self.assertEqual(odds_monitor.extract_event_id(payload), "3815731")

    def test_extract_event_id_accepts_event_shaped_id(self):
        payload = {
            "success": True,
            "event": {
                "id": "3700653",
                "participant1": "Alpha",
                "participant2": "Beta",
                "status": "Upcoming",
            },
        }
        self.assertEqual(odds_monitor.extract_event_id(payload), "3700653")

    def test_append_snapshot_skips_identical_consecutive_payload(self):
        snapshot = {
            "captured_at_utc": "2026-08-29T12:00:00+00:00",
            "paper_key": "atp:1:moneyline:a:na",
            "event_id": "123",
            "endpoints": {"recent_odds": {"ok": True, "payload": {"x": 1}}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            first = odds_monitor._append_snapshot(dict(snapshot), output_dir=output)
            second = odds_monitor._append_snapshot(dict(snapshot), output_dir=output)
            lines = (output / "2026-08-29.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
