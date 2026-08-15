"""Integração offline da fronteira operacional do processo."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import main


class OperationalBoundaryTests(unittest.TestCase):
    @staticmethod
    def _matches(total: int, failures: int) -> list[dict]:
        return [
            {
                "player1": {"name": f"A{i}"},
                "player2": {"name": f"B{i}"},
                "fail": i < failures,
            }
            for i in range(total)
        ]

    @staticmethod
    def _payload(match: dict) -> dict:
        if match["fail"]:
            raise ValueError("dados inválidos para teste")
        player_a = match["player1"]["name"]
        player_b = match["player2"]["name"]
        return {
            "player_a": player_a,
            "player_b": player_b,
            "market_odds_decimal": {player_a: 2.0, player_b: 2.0},
            "divergencia": {
                "classificacao": {"nivel": 0, "texto": "Mercado eficiente"},
                "favorecido": None,
            },
        }

    def test_processing_status_thresholds(self):
        self.assertEqual(main._classify_processing_status(100, 100)[0], "success")
        self.assertEqual(main._classify_processing_status(100, 94)[0], "degraded")
        self.assertEqual(main._classify_processing_status(100, 79)[0], "failed")
        self.assertEqual(
            main._classify_processing_status(0, 0),
            ("no_eligible_matches", 1.0),
        )

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

    def test_below_minimum_coverage_does_not_publish_partial_reports(self):
        matches = self._matches(10, failures=3)
        with patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
             patch.object(main.fetch_data, "fetch_tracked_tournament_fixtures", return_value=matches), \
             patch.object(main, "_deduplicate_matches", side_effect=lambda value: value), \
             patch.object(main, "_filter_matches_in_window", side_effect=lambda value: value), \
             patch.object(main, "_filter_and_enrich_with_tournament_info", side_effect=lambda value: value), \
             patch.object(main.fetch_data, "flush_tournament_cache"), \
             patch.object(main.fetch_data, "flush_fixtures_cache"), \
             patch.object(main.fetch_data, "prepare_rapidapi_odds_index"), \
             patch.object(main.fetch_data, "rapidapi_budget_exceeded", return_value=False), \
             patch.object(main, "_build_match_payload", side_effect=self._payload), \
             patch.object(main, "analyze_match", return_value={}), \
             patch.object(main, "_enforce_minimum_flag", side_effect=lambda _payload, result: result), \
             patch.object(main, "_factual_key_points", return_value=[]), \
             patch.object(main, "build_report_html") as build_report, \
             patch.object(main, "send_message") as send:
            with self.assertRaisesRegex(RuntimeError, "7/10 jogos processados"):
                main.run()
        build_report.assert_not_called()
        send.assert_not_called()

    def test_partial_acceptable_run_is_degraded_and_publishes_valid_matches(self):
        matches = self._matches(10, failures=1)
        with tempfile.TemporaryDirectory() as directory:
            metrics_path = str(Path(directory) / "metrics.json")
            with patch.object(main, "SITE_OUTPUT_DIR", directory), \
                 patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
                 patch.object(main.fetch_data, "fetch_tracked_tournament_fixtures", return_value=matches), \
                 patch.object(main, "_deduplicate_matches", side_effect=lambda value: value), \
                 patch.object(main, "_filter_matches_in_window", side_effect=lambda value: value), \
                 patch.object(main, "_filter_and_enrich_with_tournament_info", side_effect=lambda value: value), \
                 patch.object(main.fetch_data, "flush_tournament_cache"), \
                 patch.object(main.fetch_data, "flush_fixtures_cache"), \
                 patch.object(main.fetch_data, "prepare_rapidapi_odds_index"), \
                 patch.object(main.fetch_data, "rapidapi_budget_exceeded", return_value=False), \
                 patch.object(main, "_build_match_payload", side_effect=self._payload), \
                 patch.object(main, "analyze_match", return_value={}), \
                 patch.object(main, "_enforce_minimum_flag", side_effect=lambda _payload, result: result), \
                 patch.object(main, "_factual_key_points", return_value=[]), \
                 patch.object(main, "build_report_html", return_value="<html></html>") as build_report, \
                 patch.object(main, "_write_site_index"), \
                 patch.object(main, "send_message") as send, \
                 patch.object(main.fetch_data, "get_rapidapi_call_count", return_value=5), \
                 patch.object(main.fetch_data, "persist_rapidapi_usage") as persist_usage, \
                 patch.object(main.fetch_data, "get_rapidapi_recorded_today_calls", return_value=5):
                main.run()
                entry = main.run_metrics.append_run(path=metrics_path)

        self.assertEqual(entry["status"], "degraded")
        self.assertEqual(entry["processed"], 9)
        self.assertEqual(entry["analysis_failed"], 1)
        self.assertEqual(entry["analysis_error_counts"], {"payload:ValueError": 1})
        self.assertEqual(build_report.call_count, 9)
        send.assert_called_once()
        persist_usage.assert_called_once_with(status="degraded", matches=9)


if __name__ == "__main__":
    unittest.main()
