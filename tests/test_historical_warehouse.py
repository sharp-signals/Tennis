"""Offline cache, schema and resume tests for CHANGE-2026-09-01-021."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.historical_acquisition import HistoricalAcquirer, SOURCE, SOURCE_VERSION
from src import fetch_data
from src.historical_warehouse import CorruptCachedPayload, HistoricalWarehouse, make_cache_key


class HistoricalWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.warehouse = HistoricalWarehouse(Path(self.temp.name) / "warehouse.sqlite3")
        fetch_data._RAPIDAPI_PURPOSE_CALLS.clear()

    @staticmethod
    def counted_response(response):
        fetch_data._RAPIDAPI_PURPOSE_CALLS["backfill"] = (
            fetch_data._RAPIDAPI_PURPOSE_CALLS.get("backfill", 0) + 1
        )
        return response

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_cache_key_is_deterministic_for_parameter_order(self) -> None:
        first = make_cache_key(SOURCE, "x", {"b": 2, "a": 1}, source_version=SOURCE_VERSION)
        second = make_cache_key(SOURCE, "x", {"a": 1, "b": 2}, source_version=SOURCE_VERSION)
        self.assertEqual(first, second)

    def test_second_acquisition_is_cache_hit_and_costs_zero_calls(self) -> None:
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [{
            "id": 11, "date": "2025-01-02T12:00:00Z", "player1Id": 1,
            "player1Name": "A", "player2Id": 2, "player2Name": "B",
            "match_winner": 1, "result": "6-4 6-4", "odd1": 1.8, "odd2": 2.1,
        }]}
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=lambda *a, **k: self.counted_response(response)) as request:
            first, _, first_hit = acquirer.fetch_json("getPlayerPastMatches", "https://example.invalid", {"player_id": 1})
            second, _, second_hit = acquirer.fetch_json("getPlayerPastMatches", "https://example.invalid", {"player_id": 1})
        self.assertEqual(first, second)
        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        request.assert_called_once()
        self.assertEqual(acquirer.metrics.calls_made, 1)
        self.assertEqual(acquirer.metrics.calls_avoided_via_cache, 1)

    def test_empty_dynamic_response_is_not_cached_permanently(self) -> None:
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": []}
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=lambda *a, **k: self.counted_response(response)) as request:
            acquirer.fetch_json("getPlayerPastMatches", "https://example.invalid", {"player_id": 1})
            acquirer.fetch_json("getPlayerPastMatches", "https://example.invalid", {"player_id": 1})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.warehouse.table_count("raw_responses"), 0)

    def test_corrupt_cached_payload_is_rejected(self) -> None:
        acquirer = HistoricalAcquirer(self.warehouse)
        key = make_cache_key(SOURCE, "x", {"a": 1}, source_version=SOURCE_VERSION)
        self.warehouse.put_raw_response(
            cache_key=key, source=SOURCE, endpoint="x", params={"a": 1}, status=200,
            payload={"ok": True}, source_version=SOURCE_VERSION,
        )
        with self.warehouse.connect() as connection:
            connection.execute("UPDATE raw_responses SET payload_json='{}' WHERE cache_key=?", (key,))
        with self.assertRaises(CorruptCachedPayload):
            self.warehouse.get_raw_response(key)

    def test_resume_skips_completed_player_item(self) -> None:
        self.warehouse.set_backfill_state("past_matches:atp:1", "completed")
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch.object(acquirer, "fetch_json") as fetch:
            self.assertEqual(acquirer.acquire_player_past_matches("atp", 1, resume=True), [])
        fetch.assert_not_called()

    def test_partial_batch_resumes_from_cached_cursor(self) -> None:
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": [
            {"id": index, "date": f"2025-01-0{index}T12:00:00Z", "player1Id": 1,
             "player1Name": "A", "player2Id": index + 10, "player2Name": f"B{index}",
             "match_winner": 1, "result": "6-4 6-4"}
            for index in (1, 2, 3)
        ]}
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", return_value=response) as request:
            first = acquirer.acquire_player_past_matches("atp", 1, max_records=2)
            second = acquirer.acquire_player_past_matches("atp", 1, max_records=2)
            third = acquirer.acquire_player_past_matches("atp", 1, max_records=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertEqual(third, [])
        request.assert_called_once()
        state = self.warehouse.get_backfill_state("past_matches:atp:1")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["cursor"], "3")


if __name__ == "__main__":
    unittest.main()
