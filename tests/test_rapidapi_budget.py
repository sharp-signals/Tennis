"""Testes offline para o circuit breaker de quota RapidAPI."""

from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import fetch_data


class RapidAPIBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        fetch_data._RAPIDAPI_CALL_COUNT["n"] = 0
        fetch_data._RAPIDAPI_RECORDED_TODAY["n"] = 0
        fetch_data._RAPIDAPI_BUDGET_EXCEEDED["value"] = False
        fetch_data._RAPIDAPI_ENDPOINT_CALLS.clear()
        fetch_data._RAPIDAPI_PURPOSE_CALLS.clear()
        fetch_data._RAPIDAPI_BACKFILL_BUDGET_EXCEEDED["value"] = False

    def test_run_budget_blocks_before_external_request(self) -> None:
        fetch_data._RAPIDAPI_CALL_COUNT["n"] = 2
        with patch.object(fetch_data, "RAPIDAPI_MAX_CALLS_PER_RUN", 2):
            with patch.object(fetch_data.requests, "get") as request:
                with self.assertRaises(fetch_data.RapidAPIBudgetExceeded):
                    fetch_data._rapidapi_get("https://example.invalid")
                request.assert_not_called()
        self.assertTrue(fetch_data.rapidapi_budget_exceeded())

    def test_daily_budget_includes_recorded_calls(self) -> None:
        fetch_data._RAPIDAPI_RECORDED_TODAY["n"] = 9
        with patch.object(fetch_data, "RAPIDAPI_MAX_CALLS_PER_DAY", 10), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"):
            fetch_data._reserve_rapidapi_call()
            with self.assertRaises(fetch_data.RapidAPIBudgetExceeded):
                fetch_data._reserve_rapidapi_call()

    def test_global_hard_guard_remains_4500(self) -> None:
        fetch_data._RAPIDAPI_RECORDED_TODAY["n"] = 4499
        with patch.object(fetch_data, "RAPIDAPI_MAX_CALLS_PER_DAY", 4500), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"):
            fetch_data._reserve_rapidapi_call(purpose="operational")
            with self.assertRaises(fetch_data.RapidAPIBudgetExceeded):
                fetch_data._reserve_rapidapi_call(purpose="operational")
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 1)

    def test_backfill_stops_at_global_ceiling_and_preserves_reserve(self) -> None:
        fetch_data._RAPIDAPI_RECORDED_TODAY["n"] = 2999
        with patch.object(fetch_data, "RAPIDAPI_BACKFILL_GLOBAL_CEILING", 3000), \
             patch.object(fetch_data, "RAPIDAPI_MAX_CALLS_PER_DAY", 4500), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"):
            fetch_data._reserve_rapidapi_call(purpose="backfill")
            with self.assertRaises(fetch_data.RapidAPIBackfillBudgetExceeded):
                fetch_data._reserve_rapidapi_call(purpose="backfill")
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 1)
        self.assertEqual(fetch_data.get_rapidapi_purpose_counts(), {"backfill": 1})
        self.assertTrue(fetch_data.rapidapi_backfill_budget_exceeded())

    def test_operational_calls_count_against_backfill_but_can_use_reserve(self) -> None:
        fetch_data._RAPIDAPI_RECORDED_TODAY["n"] = 2999
        with patch.object(fetch_data, "RAPIDAPI_BACKFILL_GLOBAL_CEILING", 3000), \
             patch.object(fetch_data, "RAPIDAPI_MAX_CALLS_PER_DAY", 4500), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"):
            fetch_data._reserve_rapidapi_call(purpose="operational")
            with self.assertRaises(fetch_data.RapidAPIBackfillBudgetExceeded):
                fetch_data._reserve_rapidapi_call(purpose="backfill")
            fetch_data._reserve_rapidapi_call(purpose="operational")
        self.assertEqual(fetch_data.get_rapidapi_purpose_counts(), {"operational": 2})

    def test_backfill_retries_are_counted_in_shared_accounting(self) -> None:
        response = unittest.mock.Mock(status_code=429, headers={})
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"), \
             patch.object(fetch_data.requests, "get", return_value=response), \
             patch.object(fetch_data.time, "sleep"):
            fetch_data._rapidapi_get("https://example.invalid", rapidapi_purpose="backfill")
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 3)
        self.assertEqual(fetch_data.get_rapidapi_purpose_counts(), {"backfill": 3})

    def test_retry_attempts_each_consume_budget(self) -> None:
        response = unittest.mock.Mock(status_code=429, headers={})
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"):
            with patch.object(fetch_data.requests, "get", return_value=response):
                with patch("time.sleep"):
                    fetch_data._rapidapi_get("https://example.invalid")
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 3)
        self.assertEqual(fetch_data.get_rapidapi_endpoint_counts(), {"": 3})

    def test_transient_http_error_is_retried_then_succeeds(self) -> None:
        unavailable = unittest.mock.Mock(status_code=503, headers={})
        success = unittest.mock.Mock(status_code=200, headers={})
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"), \
             patch.object(fetch_data.requests, "get", side_effect=[unavailable, success]) as request, \
             patch.object(fetch_data.time, "sleep"):
            actual = fetch_data._rapidapi_get("https://example.invalid")
        self.assertIs(actual, success)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 2)

    def test_timeout_is_retried_but_client_error_is_not(self) -> None:
        success = unittest.mock.Mock(status_code=200, headers={})
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"), \
             patch.object(fetch_data.requests, "get", side_effect=[fetch_data.requests.Timeout(), success]) as request, \
             patch.object(fetch_data.time, "sleep"):
            self.assertIs(fetch_data._rapidapi_get("https://example.invalid"), success)
        self.assertEqual(request.call_count, 2)

        self.setUp()
        bad_request = unittest.mock.Mock(status_code=400, headers={})
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"), \
             patch.object(fetch_data.requests, "get", return_value=bad_request) as request:
            self.assertIs(fetch_data._rapidapi_get("https://example.invalid"), bad_request)
        request.assert_called_once()

    def test_retry_after_header_is_respected(self) -> None:
        limited = unittest.mock.Mock(status_code=429, headers={"Retry-After": "7"})
        success = unittest.mock.Mock(status_code=200, headers={})
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"), \
             patch.object(fetch_data.requests, "get", side_effect=[limited, success]), \
             patch.object(fetch_data.time, "sleep") as sleeper:
            fetch_data._rapidapi_get("https://example.invalid")
        sleeper.assert_called_once_with(7.0)

    def test_inflight_checkpoint_survives_crash_and_is_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            usage = Path(directory) / "usage.json"
            inflight = Path(directory) / "inflight.json"
            usage.write_text("[]", encoding="utf-8")
            with patch.object(fetch_data, "RAPIDAPI_USAGE_PATH", str(usage)), \
                 patch.object(fetch_data, "RAPIDAPI_INFLIGHT_PATH", str(inflight)), \
                 patch.object(fetch_data, "RAPIDAPI_CHECKPOINT_EVERY", 2):
                fetch_data.reset_rapidapi_call_count()
                fetch_data._reserve_rapidapi_call()
                fetch_data._reserve_rapidapi_call()
                checkpoint = json.loads(inflight.read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["calls"], 2)
                self.assertEqual(fetch_data._load_recorded_today_calls(), 2)
                entry = fetch_data.persist_rapidapi_usage(status="failed", matches=0)
                self.assertEqual(entry["status"], "failed")
                self.assertFalse(inflight.exists())
                self.assertEqual(json.loads(usage.read_text(encoding="utf-8"))[-1]["calls"], 2)

    def test_success_usage_is_atomic_bounded_and_includes_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            usage = Path(directory) / "usage.json"
            inflight = Path(directory) / "inflight.json"
            usage.write_text(
                json.dumps([{"timestamp": "old", "calls": i} for i in range(365)]),
                encoding="utf-8",
            )
            inflight.write_text("{}", encoding="utf-8")
            fetch_data._RAPIDAPI_CALL_COUNT["n"] = 12
            with patch.object(fetch_data, "RAPIDAPI_USAGE_PATH", str(usage)), \
                 patch.object(fetch_data, "RAPIDAPI_INFLIGHT_PATH", str(inflight)):
                entry = fetch_data.persist_rapidapi_usage(status="degraded", matches=9)
            history = json.loads(usage.read_text(encoding="utf-8"))
        self.assertEqual(len(history), 365)
        self.assertEqual(entry["status"], "degraded")
        self.assertEqual(entry["matches"], 9)
        self.assertEqual(entry["calls"], 12)


if __name__ == "__main__":
    unittest.main()
