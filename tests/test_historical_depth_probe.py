"""Depth-probe reporting, semantic audit and zero-LLM tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.historical_capability_audit import _summarize
from scripts.historical_depth_probe import run_depth_probe


class HistoricalDepthProbeTests(unittest.TestCase):
    def test_audit_separates_field_temporal_uses(self) -> None:
        summary = _summarize(
            "getPlayerPastMatches", "atp",
            {"data": [{"id": 1, "date": "2025-01-01", "odd1": 1.8}], "hasNextPage": True},
            False,
        )
        self.assertEqual(summary["temporal_uses"]["match_identity_temporal_use"], "EXACT_EX_ANTE")
        self.assertEqual(summary["temporal_uses"]["result_temporal_use"], "EX_POST_ONLY")
        self.assertEqual(summary["temporal_uses"]["odds_temporal_use"], "UNAVAILABLE")
        self.assertEqual(summary["temporal_uses"]["ranking_temporal_use"], "UNAVAILABLE")

    def test_depth_probe_fails_closed_if_paid_llm_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {"LLM_MODE": "anthropic", "LLM_POLICY": "always", "ALLOW_PAID_LLM": "1"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                run_depth_probe(
                    warehouse_path=Path(temp) / "warehouse.sqlite3",
                    output_dir=Path(temp) / "output",
                )

    def test_normal_no_key_probe_makes_no_anthropic_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {"LLM_MODE": "disabled", "LLM_POLICY": "never", "ALLOW_PAID_LLM": "0"},
            clear=False,
        ), patch("scripts.historical_depth_probe.fetch_data.RAPIDAPI_KEY", ""), patch(
            "src.analyze.analyze_match"
        ) as anthropic_path:
            report = run_depth_probe(
                warehouse_path=Path(temp) / "warehouse.sqlite3",
                output_dir=Path(temp) / "output",
            )
        anthropic_path.assert_not_called()
        self.assertEqual(report["status"], "not_run")


if __name__ == "__main__":
    unittest.main()
