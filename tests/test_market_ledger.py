import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src import market_ledger


class MarketLedgerTests(unittest.TestCase):
    def match(self):
        return {
            "id": 77,
            "_tour": "atp",
            "date": "2026-09-03T15:00:00+00:00",
            "tournamentId": 10,
            "tournament_name": "Test Open",
            "player1Id": 1,
            "player2Id": 2,
            "player1": {"id": 1, "name": "Alpha One"},
            "player2": {"id": 2, "name": "Beta Two"},
        }

    def provenance(self, captured="2026-09-03T10:00:00+00:00", bookmaker="Book A"):
        return {
            "source": "RapidAPI Tennis API / recent-odds",
            "endpoint": "https://provider.test/recent/77",
            "event_id": "event-77",
            "captured_at_utc": captured,
            "capture_kind": "rapidapi_response_observed_at_capture",
            "provider_timestamp": "2026-09-03T09:59:00+00:00",
            "provider_timestamp_status": "unreliable_for_freshness",
            "bookmaker": bookmaker,
            "freshness_status": "OBSERVED_AT_CAPTURE",
            "identity_mapping_status": "VERIFIED",
            "raw_payload_sha256": market_ledger.payload_sha256({"raw": 1}),
        }

    def observation(self, captured="2026-09-03T10:00:00+00:00", odds=None, bookmaker="Book A"):
        return market_ledger.build_observation(
            self.match(),
            odds or {"Alpha One": 1.8, "Beta Two": 2.1},
            self.provenance(captured, bookmaker),
            role="OPERATIONAL_PRICING",
            pipeline="PRELIVE",
        )

    def test_schema_contains_identity_raw_odds_devig_and_provenance(self):
        observation = self.observation()
        self.assertEqual(observation["event"]["event_key"], "atp:77")
        self.assertEqual(observation["event"]["scheduled_start_utc"], "2026-09-03T15:00:00+00:00")
        self.assertEqual(observation["source"]["bookmaker"], "Book A")
        self.assertEqual(observation["selections"][0]["raw_decimal_odd"], 1.8)
        self.assertAlmostEqual(sum(item["devig_probability"] for item in observation["selections"]), 1.0)
        self.assertTrue(observation["provenance"]["raw_payload_sha256"])
        self.assertTrue(observation["eligibility"]["clv"])

    def test_append_is_idempotent_but_later_capture_is_new_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.observation()
            later = self.observation(captured="2026-09-03T11:00:00+00:00")
            self.assertTrue(market_ledger.append_observation(first, root=root))
            self.assertFalse(market_ledger.append_observation(first, root=root))
            self.assertTrue(market_ledger.append_observation(later, root=root))
            self.assertEqual(len(market_ledger.read_observations(root=root)), 2)

    def test_concurrent_retry_writes_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observation = self.observation()
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(
                    lambda _: market_ledger.append_observation(observation, root=root),
                    range(16),
                ))
            self.assertEqual(results.count(True), 1)
            self.assertEqual(len(market_ledger.read_observations(root=root)), 1)

    def test_missing_bookmaker_and_stale_quotes_are_recorded_but_clv_ineligible(self):
        no_book = self.observation(bookmaker=None)
        stale_provenance = self.provenance()
        stale_provenance["freshness_status"] = "STALE"
        stale = market_ledger.build_observation(
            self.match(), {"Alpha One": 1.8, "Beta Two": 2.1}, stale_provenance,
            role="SHADOW_MONITOR", pipeline="ODDS_MONITOR",
        )
        self.assertFalse(no_book["eligibility"]["clv"])
        self.assertIn("BOOKMAKER_UNAVAILABLE", no_book["eligibility"]["reasons"])
        self.assertFalse(stale["eligibility"]["clv"])
        self.assertIn("FRESHNESS_STALE", stale["eligibility"]["reasons"])

    def test_poststart_quote_never_counts_as_closing(self):
        poststart = self.observation(captured="2026-09-03T15:00:00+00:00")
        self.assertEqual(poststart["capture"]["prestart_status"], "NOT_PRESTART")
        self.assertFalse(poststart["eligibility"]["clv"])

    def test_closing_requires_later_same_provider_endpoint_and_bookmaker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = self.observation()
            other_book = self.observation(captured="2026-09-03T12:30:00+00:00", bookmaker="Book B")
            closing = self.observation(
                captured="2026-09-03T14:30:00+00:00",
                odds={"Alpha One": 1.6, "Beta Two": 2.4},
            )
            for item in (entry, other_book, closing):
                market_ledger.append_observation(item, root=root)
            pregame = {
                "event_key": "atp:77",
                "entry_market_observation_id": entry["observation_id"],
                "commence_time_utc": "2026-09-03T15:00:00+00:00",
                "selected_side": "a",
            }
            result = market_ledger.clv_for_pregame(pregame, root=root)
            self.assertEqual(result["closing_market_observation_id"], closing["observation_id"])
            self.assertGreater(result["clv_probability_pp"], 0)
            self.assertGreater(result["clv_price_pct"], 0)

    def test_entry_without_a_later_quote_keeps_clv_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = self.observation()
            market_ledger.append_observation(entry, root=root)
            self.assertIsNone(market_ledger.clv_for_pregame({
                "event_key": "atp:77", "entry_market_observation_id": entry["observation_id"],
                "commence_time_utc": "2026-09-03T15:00:00+00:00", "selected_side": "a",
            }, root=root))

    def test_rescheduled_observation_is_not_mixed_with_original_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = self.observation()
            rescheduled_match = self.match()
            rescheduled_match["date"] = "2026-09-03T18:00:00+00:00"
            rescheduled = market_ledger.build_observation(
                rescheduled_match, {"Alpha One": 1.6, "Beta Two": 2.4},
                self.provenance("2026-09-03T14:00:00+00:00"),
                role="SHADOW_MONITOR", pipeline="ODDS_MONITOR",
            )
            market_ledger.append_observation(entry, root=root)
            market_ledger.append_observation(rescheduled, root=root)
            self.assertIsNone(market_ledger.last_comparable_prestart({
                "event_key": "atp:77", "entry_market_observation_id": entry["observation_id"],
                "commence_time_utc": "2026-09-03T15:00:00+00:00",
            }, root=root))

    def test_best_effort_failure_never_raises(self):
        with patch.object(market_ledger, "append_observation", side_effect=OSError("disk full")):
            result = market_ledger.record_market_batch_best_effort(
                self.match(), {"Alpha One": 1.8, "Beta Two": 2.1}, self.provenance(),
                role="OPERATIONAL_PRICING", pipeline="PRELIVE",
            )
        self.assertEqual(result["status"], "INELIGIBLE")
        self.assertIsNone(result["entry_observation_id"])
        self.assertIn("disk full", " ".join(result["errors"]))

    def test_rotation_compresses_closed_days_and_preserves_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_match = self.match()
            old_match["date"] = "2026-07-02T15:00:00+00:00"
            old = market_ledger.build_observation(
                old_match,
                {"Alpha One": 1.8, "Beta Two": 2.1},
                self.provenance("2026-07-02T10:00:00+00:00"),
                role="OPERATIONAL_PRICING", pipeline="PRELIVE",
            )
            market_ledger.append_observation(old, root=root)
            archived = market_ledger.rotate_archives(
                root=root, retention_days=30, today=date(2026, 9, 3),
            )
            self.assertEqual(archived, ["2026-07-02"])
            self.assertFalse((root / "observations" / "2026-07-02.jsonl").exists())
            self.assertTrue((root / "archive" / "2026" / "07" / "2026-07-02.jsonl.gz").exists())
            self.assertEqual(market_ledger.read_observations(root=root)[0]["observation_id"], old["observation_id"])
            self.assertFalse(market_ledger.append_observation(old, root=root))

    def test_corrupt_jsonl_is_reported_and_never_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "observations" / "2026-09-03.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text('{"broken":\n', encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(market_ledger.MarketLedgerError):
                market_ledger.read_observations(root=root)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
