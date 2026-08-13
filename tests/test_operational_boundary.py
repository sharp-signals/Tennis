"""Integração offline da fronteira operacional do processo."""

import unittest
from unittest.mock import patch

from src import main


class OperationalBoundaryTests(unittest.TestCase):
    def test_failure_persists_api_usage_and_metrics_then_reraises(self):
        metric_entry = {"status": "failed", "phase": "analysis", "rapidapi_calls": 7}
        with patch.object(main, "run", side_effect=RuntimeError("boom")), \
             patch.object(main.fetch_data, "get_rapidapi_call_count", return_value=7), \
             patch.object(main.fetch_data, "get_rapidapi_endpoint_counts", return_value={}), \
             patch.object(main.fetch_data, "persist_rapidapi_usage") as persist_usage, \
             patch.object(main.run_metrics, "append_run", return_value=metric_entry) as append_run, \
             patch.object(main.run_metrics, "health_alerts", return_value=["execução falhou"]):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                main.main()
        persist_usage.assert_called_once_with(status="failed", matches=0)
        append_run.assert_called_once_with(context={"rapidapi_calls": 7, "rapidapi_calls_by_endpoint": {}})


if __name__ == "__main__":
    unittest.main()
