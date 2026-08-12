"""Testes da telemetria operacional persistente."""

from __future__ import annotations

import json
import tempfile
import unittest
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

    def test_invalid_metric_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_metrics.increment("", 1)
        with self.assertRaises(ValueError):
            run_metrics.increment("llm_calls", -1)


if __name__ == "__main__":
    unittest.main()
