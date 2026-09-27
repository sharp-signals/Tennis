"""Integração offline da fronteira operacional do processo."""

import unittest
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src import main


class OperationalBoundaryTests(unittest.TestCase):
    def test_compact_match_history_builds_player_win_loss_and_sorts(self):
        matches = [
            {"id": 1, "date": "2026-01-01", "player1Id": 10, "player2Id": 20,
             "player1": {"name": "A"}, "player2": {"name": "B"},
             "match_winner": 20, "result": "4-6 3-6", "tournamentId": 99},
            {"id": 2, "date": "2026-02-01", "player1Id": 10, "player2Id": 30,
             "player1": {"name": "A"}, "player2": {"name": "C"},
             "match_winner": 10, "result": "6-2 6-2", "tournamentName": "Dubai"},
        ]
        actual = main._compact_match_history(matches, player_id=10)
        self.assertEqual([item["won"] for item in actual], [True, False])
        self.assertEqual(actual[0]["tournament"], "Dubai")
        self.assertEqual(actual[1]["winner_name"], "B")

    def test_h2h_history_resolves_tournament_name_instead_of_exposing_id(self):
        matches = [{
            "id": 1, "date": "2024-01-01", "player1Id": 10, "player2Id": 20,
            "player1": {"name": "A"}, "player2": {"name": "B"},
            "match_winner": 20, "result": "4-6 3-6", "tournamentId": 15213,
        }]
        with patch.object(main.fetch_data, "get_tournament_info",
                          return_value={"name": "Bad Homburg Open"}) as lookup:
            actual = main._compact_match_history(
                matches, tour="wta", resolve_tournaments=True,
            )

        self.assertEqual(actual[0]["tournament"], "Bad Homburg Open")
        lookup.assert_called_once_with(15213, "wta")

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

    def test_partial_discovery_promotes_success_to_degraded_only(self):
        partial = {"discovery_partial": True}
        complete = {"discovery_partial": False}

        self.assertEqual(
            main._apply_discovery_health_status("success", complete), "success"
        )
        self.assertEqual(
            main._apply_discovery_health_status("success", partial), "degraded"
        )
        self.assertEqual(
            main._apply_discovery_health_status("failed", partial), "failed"
        )
        self.assertEqual(
            main._apply_discovery_health_status("no_eligible_matches", partial),
            "degraded",
        )

    def test_trigger_context_defaults_to_manual_and_accepts_explicit_slot(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(main._trigger_context(), {
                "trigger_slot": "manual", "trigger_source": "manual",
            })
        with patch.dict("os.environ", {
            "FENZOBOT_TRIGGER_SLOT": "06:30",
            "FENZOBOT_TRIGGER_SOURCE": "google_apps_script",
            "GITHUB_RUN_ID": "123",
            "GITHUB_REPOSITORY": "sharp-signals/Tennis",
        }, clear=True):
            context = main._trigger_context()
        self.assertEqual(context["trigger_slot"], "06:30")
        self.assertEqual(context["trigger_source"], "google_apps_script")
        self.assertEqual(context["github_run_id"], "123")
        self.assertTrue(context["github_actions_url"].endswith("/actions/runs/123"))

    def test_failure_persists_api_usage_and_metrics_then_reraises(self):
        metric_entry = {"status": "failed", "phase": "analysis", "rapidapi_calls": 7}
        with patch.object(main, "run", side_effect=RuntimeError("boom")), \
             patch.object(main.fetch_data, "get_rapidapi_call_count", return_value=7), \
             patch.object(main.fetch_data, "get_rapidapi_endpoint_counts", return_value={}), \
             patch.object(main.fetch_data, "get_rapidapi_endpoint_family_counts", return_value={}), \
             patch.object(main.fetch_data, "get_rapidapi_identity_metrics", return_value={}), \
             patch.object(main.fetch_data, "persist_rapidapi_usage") as persist_usage, \
             patch.object(main.run_metrics, "append_run", return_value=metric_entry) as append_run, \
             patch.object(main.run_metrics, "health_alerts", return_value=["execução falhou"]), \
             patch.object(main.dashboard, "build_and_write_best_effort", return_value={"status": "UNAVAILABLE"}), \
             patch.object(
                 main, "send_run_failed_heartbeat",
                 return_value={"status": "FAILED", "reason_code": "SMTP_SEND_FAILED"},
             ) as failure_email:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                main.main()
        failure_email.assert_called_once()
        self.assertEqual(
            main.run_metrics.context_snapshot()["email_delivery"],
            {
                "status": "FAILED",
                "kind": "RUN_FAILED_HEARTBEAT",
                "reason_code": "SMTP_SEND_FAILED",
            },
        )
        persist_usage.assert_called_once_with(status="failed", matches=0)
        append_run.assert_called_once_with(context={
            "rapidapi_calls": 7,
            "rapidapi_calls_by_endpoint": {},
            "rapidapi_calls_by_endpoint_family": {},
            "event_identity": {},
        })

    def test_discovery_outage_is_not_reported_as_no_eligible_matches(self):
        with patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
             patch.object(main.fetch_data, "fetch_resilient_discovery_fixtures", return_value=[]), \
             patch.object(main.fetch_data, "discovery_unavailable", return_value=True), \
             patch.object(main.fetch_data, "flush_tournament_cache"), \
             patch.object(main.fetch_data, "flush_fixtures_cache"):
            with self.assertRaisesRegex(RuntimeError, "DISCOVERY_UNAVAILABLE"):
                main.run()

    def test_valid_empty_core_calendar_finishes_as_no_eligible_matches(self):
        diagnostics = {
            "discovery_sources": {
                "upcoming_discovery": {"status": "SOURCE_UNAVAILABLE", "matches": 0},
                "core_date_fixtures": {"status": "SUCCESS_EMPTY", "matches": 0},
            },
            "discovery_selected_source": "core_date_fixtures",
            "discovery_status": "SUCCESS_EMPTY",
        }
        with patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
             patch.object(main.fetch_data, "fetch_resilient_discovery_fixtures", return_value=[]), \
             patch.object(main.fetch_data, "get_discovery_diagnostics", return_value=diagnostics), \
             patch.object(main.fetch_data, "discovery_unavailable", return_value=False), \
             patch.object(main.fetch_data, "flush_tournament_cache"), \
             patch.object(main.fetch_data, "flush_fixtures_cache"), \
             patch.object(main.fetch_data, "persist_rapidapi_usage") as persist, \
             patch.object(
                 main, "send_no_eligible_heartbeat",
                 return_value={"status": "SENT", "kind": "NO_ELIGIBLE_HEARTBEAT"},
             ) as heartbeat:
            main.run()
        persist.assert_called_once_with(status="no_eligible_matches", matches=0)
        heartbeat.assert_called_once()
        self.assertEqual(
            heartbeat.call_args.kwargs["reason"],
            "nenhum jogo elegível nesta execução",
        )

    def test_partial_discovery_without_eligible_matches_is_degraded(self):
        diagnostics = {
            "discovery_sources": {
                "core_date_fixtures": {
                    "status": "SUCCESS_WITH_MATCHES",
                    "requests": 8,
                    "successful_requests": 7,
                    "unavailable_requests": 1,
                },
            },
            "discovery_selected_source": "core_date_fixtures",
            "discovery_status": "SUCCESS_WITH_MATCHES",
            "discovery_partial": True,
        }
        with patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
             patch.object(
                 main.fetch_data, "fetch_resilient_discovery_fixtures",
                 return_value=[],
             ), \
             patch.object(
                 main.fetch_data, "get_discovery_diagnostics",
                 return_value=diagnostics,
             ), \
             patch.object(main.fetch_data, "discovery_unavailable", return_value=False), \
             patch.object(main.fetch_data, "flush_tournament_cache"), \
             patch.object(main.fetch_data, "flush_fixtures_cache"), \
             patch.object(main.fetch_data, "persist_rapidapi_usage") as persist, \
             patch.object(
                 main, "send_no_eligible_heartbeat",
                 return_value={"status": "SENT", "kind": "NO_ELIGIBLE_HEARTBEAT"},
             ) as heartbeat:
            main.run()

        persist.assert_called_once_with(status="degraded", matches=0)
        self.assertTrue(heartbeat.call_args.args[1]["discovery_partial"])

    def test_zero_after_identity_sends_distinct_heartbeat(self):
        match = self._matches(1, failures=0)[0]
        diagnostics = {
            "discovery_sources": {},
            "discovery_selected_source": "upcoming_discovery",
            "discovery_status": "SUCCESS_WITH_MATCHES",
            "discovery_partial": False,
        }
        with patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
             patch.object(
                 main.fetch_data, "fetch_resilient_discovery_fixtures",
                 return_value=[match],
             ), \
             patch.object(
                 main.fetch_data, "get_discovery_diagnostics",
                 return_value=diagnostics,
             ), \
             patch.object(main, "_deduplicate_matches", side_effect=lambda value: value), \
             patch.object(main, "_filter_matches_in_window", side_effect=lambda value: value), \
             patch.object(main, "_filter_prelive_matches", side_effect=lambda value: value), \
             patch.object(
                 main, "_filter_and_enrich_with_tournament_info",
                 side_effect=lambda value: value,
             ), \
             patch.object(main.fetch_data, "flush_tournament_cache"), \
             patch.object(main.fetch_data, "flush_fixtures_cache"), \
             patch.object(main.fetch_data, "prepare_rapidapi_odds_index"), \
             patch.object(
                 main.fetch_data, "rapidapi_event_integrity",
                 return_value={"status": "rejected", "reason": "MISMATCH"},
             ), \
             patch.object(main.fetch_data, "get_rapidapi_identity_metrics", return_value={}), \
             patch.object(main.fetch_data, "persist_rapidapi_usage") as persist, \
             patch.object(
                 main, "send_no_eligible_heartbeat",
                 return_value={"status": "SENT", "kind": "NO_ELIGIBLE_HEARTBEAT"},
             ) as heartbeat:
            main.run()

        persist.assert_called_once_with(status="no_eligible_matches", matches=0)
        heartbeat.assert_called_once()
        self.assertEqual(
            heartbeat.call_args.kwargs["reason"],
            "nenhum jogo com identidade pré-live válida",
        )

    def test_below_minimum_coverage_does_not_publish_partial_reports(self):
        matches = self._matches(10, failures=3)
        with patch.object(main.fetch_data, "reset_rapidapi_call_count"), \
             patch.object(main.fetch_data, "fetch_resilient_discovery_fixtures", return_value=matches), \
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
            with ExitStack() as stack:
                stack.enter_context(patch.object(main, "SITE_OUTPUT_DIR", directory))
                stack.enter_context(patch.object(main.fetch_data, "reset_rapidapi_call_count"))
                stack.enter_context(patch.object(
                    main.fetch_data, "fetch_resilient_discovery_fixtures", return_value=matches,
                ))
                stack.enter_context(patch.object(
                    main, "_deduplicate_matches", side_effect=lambda value: value,
                ))
                stack.enter_context(patch.object(
                    main, "_filter_matches_in_window", side_effect=lambda value: value,
                ))
                stack.enter_context(patch.object(
                    main, "_filter_and_enrich_with_tournament_info", side_effect=lambda value: value,
                ))
                stack.enter_context(patch.object(main.fetch_data, "flush_tournament_cache"))
                stack.enter_context(patch.object(main.fetch_data, "flush_fixtures_cache"))
                stack.enter_context(patch.object(main.fetch_data, "prepare_rapidapi_odds_index"))
                stack.enter_context(patch.object(
                    main.fetch_data, "rapidapi_budget_exceeded", return_value=False,
                ))
                stack.enter_context(patch.object(main, "_build_match_payload", side_effect=self._payload))
                stack.enter_context(patch.object(main, "analyze_match", return_value={}))
                stack.enter_context(patch.object(
                    main, "_enforce_minimum_flag", side_effect=lambda _payload, result: result,
                ))
                stack.enter_context(patch.object(main, "_factual_key_points", return_value=[]))
                stack.enter_context(patch.object(
                    main.calibration_store, "upsert_snapshots", return_value=9,
                ))
                build_report = stack.enter_context(patch.object(
                    main, "build_report_html", return_value="<html></html>",
                ))
                stack.enter_context(patch.object(main, "_write_site_index"))
                send = stack.enter_context(patch.object(main, "send_message"))
                prepared_email = stack.enter_context(patch.object(
                    main, "prepare_run_report_email", return_value={"today": "2026-09-27", "groups": []},
                ))
                manifest = stack.enter_context(patch.object(
                    main.report_notifications, "write_manifest",
                    return_value=Path(directory) / "manifest.json",
                ))
                heartbeat = stack.enter_context(patch.object(
                    main, "send_no_eligible_heartbeat",
                ))
                stack.enter_context(patch.object(
                    main.fetch_data, "get_rapidapi_call_count", return_value=5,
                ))
                persist_usage = stack.enter_context(patch.object(
                    main.fetch_data, "persist_rapidapi_usage",
                ))
                stack.enter_context(patch.object(
                    main.fetch_data, "get_rapidapi_recorded_today_calls", return_value=5,
                ))
                main.run()
                entry = main.run_metrics.append_run(path=metrics_path)

        self.assertEqual(entry["status"], "degraded")
        self.assertEqual(entry["processed"], 9)
        self.assertEqual(entry["analysis_failed"], 1)
        self.assertEqual(entry["analysis_error_counts"], {"payload:ValueError": 1})
        self.assertEqual(build_report.call_count, 9)
        send.assert_not_called()
        prepared_email.assert_called_once()
        manifest.assert_called_once()
        artifacts = manifest.call_args.kwargs["reports"]
        self.assertEqual(len(artifacts), 9)
        for artifact in artifacts:
            self.assertTrue(artifact["url"].startswith(f"{main.SITE_BASE_URL}/"))
            self.assertTrue(artifact["local_path"].endswith(".html"))
        heartbeat.assert_not_called()
        self.assertEqual(entry["email_delivery"], {
            "status": "NOT_ATTEMPTED", "kind": "REPORTS",
        })
        self.assertEqual(entry["report_publication"]["status"], "PENDING")
        self.assertEqual(entry["report_notification_status"], "REPORTS_DEFERRED")
        persist_usage.assert_called_once_with(status="degraded", matches=9)


if __name__ == "__main__":
    unittest.main()
