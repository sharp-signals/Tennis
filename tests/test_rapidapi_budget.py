"""Testes offline para o circuit breaker de quota RapidAPI."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src import fetch_data


class RapidAPIBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        fetch_data._RAPIDAPI_CALL_COUNT["n"] = 0
        fetch_data._RAPIDAPI_RECORDED_TODAY["n"] = 0
        fetch_data._RAPIDAPI_BUDGET_EXCEEDED["value"] = False

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
        with patch.object(fetch_data, "RAPIDAPI_MAX_CALLS_PER_DAY", 10):
            fetch_data._reserve_rapidapi_call()
            with self.assertRaises(fetch_data.RapidAPIBudgetExceeded):
                fetch_data._reserve_rapidapi_call()

    def test_retry_attempts_each_consume_budget(self) -> None:
        response = unittest.mock.Mock(status_code=429)
        with patch.object(fetch_data, "RAPIDAPI_MIN_INTERVAL", 0):
            with patch.object(fetch_data.requests, "get", return_value=response):
                with patch("time.sleep"):
                    fetch_data._rapidapi_get("https://example.invalid")
        self.assertEqual(fetch_data.get_rapidapi_call_count(), 3)


if __name__ == "__main__":
    unittest.main()
