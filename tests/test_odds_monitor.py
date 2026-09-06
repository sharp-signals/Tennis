import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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

    def test_recent_odds_marks_old_provider_quote_stale(self):
        captured = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
        provider = captured - timedelta(hours=2)
        result = {
            "payload": {
                "result": {
                    "Full Time Result": {
                        "DraftKings": {
                            "addTime": str(int(provider.timestamp())),
                            "od1": "1.50",
                            "od2": "2.55",
                        }
                    }
                }
            }
        }
        annotated = odds_monitor._annotate_recent_odds(result, captured_at=captured)
        quote = annotated["quote_quality"]["quotes"][0]
        self.assertEqual(quote["freshness"], "STALE")
        self.assertEqual(quote["quote_age_seconds"], 7200)
        self.assertEqual(annotated["quote_quality"]["stale_count"], 1)

    def test_recent_odds_marks_recent_provider_quote_fresh(self):
        captured = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
        provider = captured - timedelta(minutes=5)
        result = {
            "payload": {
                "result": {
                    "Full Time Result": {
                        "Bet365": {
                            "addTime": str(int(provider.timestamp())),
                            "od1": "1.70",
                            "od2": "2.10",
                        }
                    }
                }
            }
        }
        annotated = odds_monitor._annotate_recent_odds(result, captured_at=captured)
        quote = annotated["quote_quality"]["quotes"][0]
        self.assertEqual(quote["freshness"], "FRESH")
        self.assertEqual(quote["quote_age_seconds"], 300)
        self.assertEqual(annotated["quote_quality"]["fresh_count"], 1)

    def test_arbitrage_with_stale_best_odds_is_not_current_eligible(self):
        compare = {
            "quote_quality": {
                "quotes": [
                    {"bookmaker": "BookA", "freshness": "STALE"},
                    {"bookmaker": "BookB", "freshness": "FRESH"},
                ]
            }
        }
        result = {
            "payload": {
                "result": {
                    "arbitrage": True,
                    "bookmakersChecked": 2,
                    "bestOdds": {
                        "outcome1": {"bookmaker": "BookA", "odds": 2.1},
                        "outcome2": {"bookmaker": "BookB", "odds": 2.1},
                    },
                }
            }
        }
        annotated = odds_monitor._annotate_arbitrage(result, compare)
        self.assertEqual(annotated["input_quality"]["status"], "STALE_INPUTS")
        self.assertFalse(annotated["input_quality"]["current_arbitrage_eligible"])

    def test_primary_market_observation_uses_feed_capture_not_provider_freshness(self):
        match = {
            "player1": {"name": "Alpha"},
            "player2": {"name": "Beta"},
        }
        provenance = {
            "source": "RapidAPI Tennis API / embedded upcoming feed",
            "endpoint": "https://example.invalid/upcoming",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with patch.object(
            odds_monitor.fetch_data,
            "fetch_rapidapi_embedded_moneyline_with_provenance",
            return_value=({"Alpha": 1.8, "Beta": 2.0}, provenance),
        ):
            observation = odds_monitor._primary_market_observation(match)
        self.assertTrue(observation["series_eligible"])
        self.assertEqual(observation["odds"], {"Alpha": 1.8, "Beta": 2.0})
        self.assertEqual(observation["freshness"], "OBSERVED_AT_CAPTURE_UNVERIFIED_PROVIDER_TIME")
        self.assertIsNone(observation["quote_age_seconds"])

    def test_append_snapshot_skips_identical_consecutive_payload(self):
        snapshot = {
            "captured_at_utc": "2026-08-29T12:00:00+00:00",
            "paper_key": "atp:1:moneyline:a:na",
            "event_id": "123",
            "market_observation": {"odds": {"A": 1.8, "B": 2.0}},
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

    def test_event_resolution_preserves_verified_provider_order(self):
        start = datetime.now(timezone.utc) + timedelta(hours=12)
        entry = {
            "key": "atp:1:moneyline:a:na",
            "pregame": {
                "match_id": 1, "tour": "atp", "commence_time_utc": start.isoformat(),
                "players": {
                    "a": {"id": 10, "name": "Alpha One"},
                    "b": {"id": 20, "name": "Beta Two"},
                },
            },
        }
        event_map = {"events": {}}
        response = {
            "ok": True, "http_status": 200, "access": "allowed", "error": None,
            "payload": {"event": {
                "eventId": "event-1", "participant1": "Beta Two", "participant2": "Alpha One",
                "status": "scheduled", "startTime": start.isoformat(),
            }},
        }
        with patch.object(odds_monitor, "_request", return_value=response):
            event_id, resolution = odds_monitor._resolve_event(entry, event_map)
        self.assertEqual(event_id, "event-1")
        self.assertEqual(resolution["participant1"], "Beta Two")
        self.assertEqual(event_map["events"][entry["key"]]["identity_mapping_status"], "VERIFIED")

    def test_ledger_normalization_reuses_monitor_payload_without_network_calls(self):
        entry = {
            "key": "atp:1:moneyline:a:na",
            "pregame": {
                "snapshot_key": "atp:1", "match_id": 1, "tour": "atp",
                "commence_time_utc": "2026-09-04T15:00:00+00:00",
                "players": {
                    "a": {"id": 10, "name": "Alpha One"},
                    "b": {"id": 20, "name": "Beta Two"},
                },
            },
        }
        match = odds_monitor._entry_to_match(entry)
        payload = {"result": {"Full Time Result": {
            "Book A": {"od1": "1.70", "od2": "2.20", "addTime": None},
        }}}
        snapshot = {
            "captured_at_utc": "2026-09-04T12:00:00+00:00",
            "event_id": "event-1",
            "event_resolution": {
                "participant1": "Beta Two", "participant2": "Alpha One",
                "identity_mapping_status": "VERIFIED",
            },
            "market_observation": {"available": False},
            "endpoints": {
                "recent_odds": odds_monitor._annotate_recent_odds(
                    {"payload": payload},
                    captured_at=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
                ),
            },
        }
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(odds_monitor, "_request", side_effect=AssertionError("network not allowed")):
            result = odds_monitor._persist_market_ledger_best_effort(
                entry, match, snapshot, ledger_root=Path(tmp),
            )
            observations = odds_monitor.market_ledger.read_observations(root=Path(tmp))
        self.assertEqual(result["recorded"], 1)
        self.assertEqual(observations[0]["selections"][0]["raw_decimal_odd"], 2.2)
        self.assertEqual(observations[0]["selections"][1]["raw_decimal_odd"], 1.7)


if __name__ == "__main__":
    unittest.main()
