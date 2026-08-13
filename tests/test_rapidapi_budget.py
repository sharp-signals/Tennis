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

    def test_retry_attempts_each_consume_budget(self) -> None:
        response = unittest.mock.Mock(status_code=429)
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0), \
             patch.object(fetch_data, "_write_rapidapi_checkpoint"):
            with patch.object(fetch_data.requests, "get", return_value=response):
                with patch("time.sleep"):
                    fetch_data._rapidapi_get("https://example.invalid")
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 3)
        self.assertEqual(fetch_data.get_rapidapi_endpoint_counts(), {"": 3})

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


if __name__ == "__main__":
    unittest.main()
