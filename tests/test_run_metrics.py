"""Testes da telemetria operacional persistente."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src import run_metrics


class RunMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        run_metrics.reset()

    def test_increment_and_snapshot(self) -> None:
        run_metrics.increment("llm_calls")
        run_metrics.increment("llm_input_tokens", 120)
        self.assertEqual(
            run_metrics.snapshot(),
            {"llm_calls": 1, "llm_input_tokens": 120},
        )

    def test_append_is_atomic_and_retains_bounded_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.json"
            path.write_text(json.dumps([{"old": i} for i in range(4)]), encoding="utf-8")
            run_metrics.increment("llm_calls", 2)
            with patch.object(run_metrics, "MAX_HISTORY_ENTRIES", 3):
                entry = run_metrics.append_run(path=str(path), context={"processed": 5})
            history = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(history), 3)
        self.assertEqual(entry["llm_calls"], 2)
        self.assertEqual(history[-1]["processed"], 5)

    def test_concurrent_appends_preserve_every_entry_and_clean_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.json"

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(
                    lambda run_id: run_metrics.append_run(
                        path=str(path), context={"run_id": run_id},
                    ),
                    range(20),
                ))

            history = json.loads(path.read_text(encoding="utf-8"))
            temporary_files = list(path.parent.glob(f".{path.name}.*.tmp"))

        self.assertEqual({entry["run_id"] for entry in history}, set(range(20)))
        self.assertEqual(temporary_files, [])

    def test_non_object_history_entries_are_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.json"
            path.write_text(json.dumps([None, "broken", {"valid": True}]), encoding="utf-8")

            run_metrics.append_run(path=str(path), context={"current": True})
            history = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(history[0], {"valid": True})
        self.assertTrue(history[1]["current"])

    def test_invalid_metric_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_metrics.increment("", 1)
        with self.assertRaises(ValueError):
            run_metrics.increment("llm_calls", -1)

    def test_context_duration_and_cost_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.json"
            run_metrics.update_context(status="failed", phase="analysis")
            run_metrics.increment("llm_input_tokens", 1_000_000)
            with patch.dict("os.environ", {"LLM_PRICE_INPUT_PER_MTOK": "2"}):
                entry = run_metrics.append_run(path=str(path))
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["phase"], "analysis")
        self.assertEqual(entry["llm_estimated_cost_usd"], 2.0)
        self.assertGreaterEqual(entry["duration_seconds"], 0)

    def test_health_alerts_cover_cost_fallbacks_and_failures(self) -> None:
        alerts = run_metrics.health_alerts({
            "status": "failed", "phase": "analysis", "rapidapi_calls": 700,
            "llm_calls": 10, "llm_fallbacks": 3, "reports_failed": 1,
            "eligible": 10, "analysis_failed": 2,
            "llm_estimated_cost_usd": 2.0,
        })
        self.assertEqual(len(alerts), 6)
        self.assertTrue(any("RapidAPI" in alert for alert in alerts))
        self.assertTrue(any("2/10" in alert for alert in alerts))

    def test_cache_failures_are_visible_in_health_alerts(self) -> None:
        alerts = run_metrics.health_alerts({
            "llm_cache_invalid": 2,
            "llm_cache_write_failures": 1,
        })

        self.assertTrue(any("cache LLM inválida: 2" in alert for alert in alerts))
        self.assertTrue(any("gravar cache LLM: 1" in alert for alert in alerts))

    def test_invalid_numeric_configuration_falls_back_safely(self) -> None:
        metrics = {"llm_input_tokens": 1_000_000, "llm_output_tokens": "invalid"}
        environment = {
            "LLM_PRICE_INPUT_PER_MTOK": "not-a-number",
            "LLM_PRICE_OUTPUT_PER_MTOK": "nan",
            "ALERT_RAPIDAPI_CALLS": "broken",
            "ALERT_LLM_FALLBACK_RATE": "broken",
            "ALERT_LLM_COST_USD": "broken",
        }

        with patch.dict("os.environ", environment):
            self.assertEqual(run_metrics.estimate_llm_cost_usd(metrics), 3.0)
            alerts = run_metrics.health_alerts({
                "rapidapi_calls": "700",
                "llm_calls": "invalid",
                "llm_estimated_cost_usd": "2.5",
            })

        self.assertTrue(any("RapidAPI" in alert for alert in alerts))
        self.assertTrue(any("$2.5000" in alert for alert in alerts))


if __name__ == "__main__":
    unittest.main()
