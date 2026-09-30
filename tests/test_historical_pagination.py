"""Pagination, cache, resume and quota tests for CHANGE-2026-09-01-022."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import fetch_data
from src.historical_acquisition import (
    HistoricalAcquirer,
    SOURCE,
    SOURCE_VERSION,
    normalize_past_match,
)
from src.historical_warehouse import HistoricalWarehouse, make_cache_key


def match_row(match_id: int, *, date: str | None = None, odds: bool = False) -> dict:
    row = {
        "id": match_id,
        "date": date or f"2025-01-{(match_id % 28) + 1:02d}T12:00:00Z",
        "player1Id": 1,
        "player1Name": "A",
        "player2Id": match_id + 100,
        "player2Name": f"B{match_id}",
        "match_winner": 1,
        "result": "6-4 6-4",
    }
    if odds:
        row.update({"odd1": 1.8, "odd2": 2.1})
    return row


def page_payload(page: int, ids: list[int], *, has_next: bool) -> dict:
    return {
        "data": [match_row(match_id) for match_id in ids],
        "page": page,
        "pageNo": page,
        "pageSize": 10,
        "hasNextPage": has_next,
    }


class HistoricalPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.warehouse = HistoricalWarehouse(Path(self.temp.name) / "warehouse.sqlite3")
        fetch_data._RAPIDAPI_PURPOSE_CALLS.clear()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def response(payload: dict) -> Mock:
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    def provider(self, payloads: dict[int, dict], *, fail_page: int | None = None):
        def request(*_args, **kwargs):
            page = int(kwargs["params"]["page"])
            fetch_data._RAPIDAPI_PURPOSE_CALLS["backfill"] = (
                fetch_data._RAPIDAPI_PURPOSE_CALLS.get("backfill", 0) + 1
            )
            if page == fail_page:
                raise RuntimeError(f"page {page} failed")
            return self.response(payloads[page])

        return request

    def test_page_one_with_next_calls_page_two_and_exhausts_source(self) -> None:
        payloads = {
            1: page_payload(1, [1, 2], has_next=True),
            2: page_payload(2, [3], has_next=False),
        }
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)) as request:
            result = acquirer.acquire_player_past_match_pages("atp", 1)
        self.assertEqual([call.kwargs["params"] for call in request.call_args_list], [{"page": 1}, {"page": 2}])
        self.assertEqual(result["stop_reason"], "source_exhausted")
        self.assertTrue(result["source_exhausted"])
        self.assertEqual(result["unique_matches"], 3)
        self.assertEqual(self.warehouse.table_count("matches"), 3)

    def test_empty_page_terminates(self) -> None:
        acquirer = HistoricalAcquirer(self.warehouse)
        payloads = {1: page_payload(1, [], has_next=True)}
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)):
            result = acquirer.acquire_player_past_match_pages("wta", 2)
        self.assertEqual(result["stop_reason"], "empty_page")
        self.assertTrue(result["source_exhausted"])

    def test_max_pages_is_limit_not_source_exhaustion(self) -> None:
        acquirer = HistoricalAcquirer(self.warehouse)
        payloads = {1: page_payload(1, [1], has_next=True)}
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)):
            result = acquirer.acquire_player_past_match_pages("atp", 1, max_pages=1)
        state = self.warehouse.get_backfill_state("past_matches:atp:1")
        self.assertEqual(result["stop_reason"], "max_pages")
        self.assertFalse(result["source_exhausted"])
        self.assertEqual(state["status"], "limit_reached")
        self.assertEqual(HistoricalAcquirer._parse_cursor(state["cursor"])["page"], 2)

    def test_max_records_resumes_inside_cached_page(self) -> None:
        acquirer = HistoricalAcquirer(self.warehouse)
        payloads = {1: page_payload(1, [1, 2, 3], has_next=False)}
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)) as request:
            first = acquirer.acquire_player_past_match_pages("atp", 1, max_records=2)
            second = acquirer.acquire_player_past_match_pages("atp", 1, max_records=2)
        self.assertEqual(len(first["match_ids"]), 2)
        self.assertEqual(len(second["match_ids"]), 1)
        request.assert_called_once()
        state = self.warehouse.get_backfill_state("past_matches:atp:1")
        self.assertEqual(state["status"], "source_exhausted")

    def test_repeated_page_is_detected_even_if_id_order_changes(self) -> None:
        payloads = {
            1: page_payload(1, [1, 2], has_next=True),
            2: page_payload(2, [2, 1], has_next=True),
        }
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)):
            result = acquirer.acquire_player_past_match_pages("atp", 1, max_pages=5)
        self.assertEqual(result["stop_reason"], "repeated_page")
        self.assertEqual(self.warehouse.get_backfill_state("past_matches:atp:1")["status"], "failed")

    def test_cached_page_one_then_uncached_page_two_costs_one_call(self) -> None:
        page_one_key = make_cache_key(
            SOURCE, "getPlayerPastMatches", {"tour": "atp", "player_id": 1, "page": 1},
            source_version=SOURCE_VERSION,
        )
        self.warehouse.put_raw_response(
            cache_key=page_one_key,
            source=SOURCE,
            endpoint="getPlayerPastMatches",
            params={"tour": "atp", "player_id": 1, "page": 1},
            status=200,
            payload=page_payload(1, [1], has_next=True),
            source_version=SOURCE_VERSION,
        )
        payloads = {2: page_payload(2, [2], has_next=False)}
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)) as request:
            result = acquirer.acquire_player_past_match_pages("atp", 1, resume=False)
        request.assert_called_once()
        self.assertEqual(result["cache_hits"], 1)
        self.assertEqual(result["calls_made"], 1)

    def test_rerun_of_all_cached_pages_makes_zero_calls(self) -> None:
        payloads = {
            1: page_payload(1, [1], has_next=True),
            2: page_payload(2, [2], has_next=False),
        }
        first = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)):
            first.acquire_player_past_match_pages("atp", 1)
        second = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get") as request:
            result = second.acquire_player_past_match_pages("atp", 1, resume=False)
        request.assert_not_called()
        self.assertEqual(result["cache_hits"], 2)
        self.assertEqual(result["calls_made"], 0)

    def test_cache_keys_differ_by_page(self) -> None:
        first = make_cache_key(
            SOURCE, "getPlayerPastMatches", {"tour": "atp", "player_id": 1, "page": 1},
            source_version=SOURCE_VERSION,
        )
        second = make_cache_key(
            SOURCE, "getPlayerPastMatches", {"tour": "atp", "player_id": 1, "page": 2},
            source_version=SOURCE_VERSION,
        )
        self.assertNotEqual(first, second)

    def test_failure_on_page_four_resumes_at_four_without_requesting_one_to_three(self) -> None:
        payloads = {
            1: page_payload(1, [1], has_next=True),
            2: page_payload(2, [2], has_next=True),
            3: page_payload(3, [3], has_next=True),
            4: page_payload(4, [4], has_next=False),
        }
        first = HistoricalAcquirer(self.warehouse)
        with patch(
            "src.historical_acquisition.fetch_data._rapidapi_get",
            side_effect=self.provider(payloads, fail_page=4),
        ):
            failed = first.acquire_player_past_match_pages("atp", 1)
        self.assertEqual(failed["stop_reason"], "failed")
        state = self.warehouse.get_backfill_state("past_matches:atp:1")
        self.assertEqual(HistoricalAcquirer._parse_cursor(state["cursor"])["page"], 4)

        second = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)) as request:
            resumed = second.acquire_player_past_match_pages("atp", 1)
        self.assertEqual([call.kwargs["params"] for call in request.call_args_list], [{"page": 4}])
        self.assertEqual(resumed["stop_reason"], "source_exhausted")

    def test_legacy_numeric_cursor_is_migrated_safely(self) -> None:
        self.warehouse.set_backfill_state("past_matches:atp:1", "limit_reached", cursor="2")
        payloads = {1: page_payload(1, [1, 2, 3], has_next=False)}
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)):
            result = acquirer.acquire_player_past_match_pages("atp", 1)
        self.assertEqual(len(result["match_ids"]), 1)
        cursor = json.loads(self.warehouse.get_backfill_state("past_matches:atp:1")["cursor"])
        self.assertEqual(cursor["version"], 2)

    def test_cross_page_duplicate_is_not_duplicated_in_matches(self) -> None:
        payloads = {
            1: page_payload(1, [1, 2], has_next=True),
            2: page_payload(2, [2, 3], has_next=False),
        }
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)):
            result = acquirer.acquire_player_past_match_pages("atp", 1)
        self.assertEqual(result["raw_records"], 4)
        self.assertEqual(result["unique_matches"], 3)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.warehouse.table_count("matches"), 3)

    def test_max_calls_stops_and_preserves_page_cursor(self) -> None:
        payloads = {1: page_payload(1, [1], has_next=True)}
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get", side_effect=self.provider(payloads)) as request:
            result = acquirer.acquire_player_past_match_pages("atp", 1, max_calls=1)
        request.assert_called_once()
        self.assertEqual(result["stop_reason"], "max_calls")
        state = self.warehouse.get_backfill_state("past_matches:atp:1")
        self.assertEqual(state["status"], "budget_reached")
        self.assertEqual(HistoricalAcquirer._parse_cursor(state["cursor"])["page"], 2)

    def test_shared_ceiling_exception_preserves_cursor(self) -> None:
        acquirer = HistoricalAcquirer(self.warehouse)
        with patch(
            "src.historical_acquisition.fetch_data._rapidapi_get",
            side_effect=fetch_data.RapidAPIBackfillBudgetExceeded("ceiling 3000"),
        ):
            result = acquirer.acquire_player_past_match_pages("wta", 2, max_calls=24)
        self.assertEqual(result["stop_reason"], "budget_reached")
        state = self.warehouse.get_backfill_state("past_matches:wta:2")
        self.assertEqual(state["status"], "budget_reached")
        self.assertEqual(HistoricalAcquirer._parse_cursor(state["cursor"])["page"], 1)

    def test_temporal_classes_remain_conservative(self) -> None:
        normalized = normalize_past_match(
            match_row(1, odds=True), tour="atp", cache_key="cache", fetched_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(normalized["identity_temporal_class"], "EXACT_EX_ANTE")
        self.assertEqual(normalized["outcome_temporal_class"], "EX_POST_ONLY")
        self.assertEqual(normalized["ranking_temporal_class"], "UNAVAILABLE")
        self.assertTrue(normalized["quotes"])
        self.assertTrue(all(quote["temporal_class"] == "UNAVAILABLE" for quote in normalized["quotes"]))


if __name__ == "__main__":
    unittest.main()
