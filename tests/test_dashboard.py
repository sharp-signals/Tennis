"""Contrato do Fenzobot Control Dashboard read-only."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import dashboard, report_html, run_metrics


NOW = "2026-09-06T20:00:00+00:00"
RID_GREEN = "11111111111111111111"
RID_YELLOW = "22222222222222222222"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def snapshot(report_id: str, key: str, flag: str, *, outcome=None, green=False):
    value = {
        "key": key,
        "report_id": report_id,
        "commence_time_utc": "2026-09-06T18:00:00+00:00",
        "player_a": {"name": f"Alpha {report_id[0]}"},
        "player_b": {"name": f"Beta {report_id[0]}"},
        "analysis": {"flag": flag},
        "outcome": outcome,
        "metrics": {},
    }
    if green:
        value["validation"] = {"cohorts": {"GREEN_STRONG_V1": {"eligible": True}}}
    return value


def summary(total=0, settled=0, pending=0, wins=0, losses=0, units=None, roi=None, odd=None):
    return {
        "total_entries": total,
        "settled": settled,
        "pending": pending,
        "wins": wins,
        "losses": losses,
        "pushes": 0,
        "win_rate_pct": round(100 * wins / (wins + losses), 2) if wins + losses else None,
        "units": units,
        "roi_pct": roi,
        "average_odd": odd,
    }


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _report(
        self,
        filename: str,
        title: str,
        *,
        color: str | None = None,
        decision_state: str | None = None,
    ) -> Path:
        path = self.root / "docs/relatorios" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        marker = (
            f'<meta name="{report_html.REPORT_COLOR_META_NAME}" content="{color}">'
            if color is not None else ""
        )
        decision = ""
        if decision_state is not None:
            label, css_class, ball, _color = report_html.REPORT_DECISION_PRESENTATION[decision_state]
            decision = (
                f'<section class="decision-box {css_class}"><div class="decision-head">'
                f'<span>{ball}</span><b>{label}</b></div></section>'
            )
        path.write_text(
            f"<!doctype html><head>{marker}<title>{title}</title></head><body>{decision}</body>",
            encoding="utf-8",
        )
        return path

    def _base_sources(self) -> None:
        snapshots = [
            snapshot(RID_GREEN, "atp:1", "🟢", outcome={"winner_side": "a"}),
            snapshot(RID_YELLOW, "wta:2", "🟡", green=True),
        ]
        write_json(self.root / "data/calibration_snapshots.json", {
            "snapshots": snapshots, "updated_at_utc": NOW,
        })
        write_json(self.root / "data/paper_trades.json", {"schema_version": 1, "entries": [{
            "key": "paper-1",
            "pregame": {"report_id": RID_GREEN, "snapshot_key": "atp:1", "market_type": "Moneyline", "odd": 2.0},
            "settlement": {"result": "WIN", "pnl_units": 1.0},
        }], "updated_at_utc": NOW})
        manual_summary = summary(3, 2, 1, 1, 1, units=0.5, roi=25.0, odd=1.9)
        write_json(self.root / "data/manual_paper_22bet.json", {
            "schema_version": 1,
            "source": {"synced_at_utc": NOW, "reference_bookmaker": "22Bet"},
            "summary": manual_summary,
            "by_market": {"Moneyline": manual_summary},
            "by_side": {"UNDERDOG": manual_summary},
        })
        green_metrics = {
            "sample_size": 1,
            "settled_sample_size": 0,
            "average_selected_market_probability": 0.44,
            "average_selected_fenzobot_probability": 0.61,
            "win_rate_pct": None,
            "market": {"sample_size": 0, "accuracy_pct": None, "brier_score": None, "log_loss": None},
            "fenzobot": {"sample_size": 0, "accuracy_pct": None, "brier_score": None, "log_loss": None},
            "paired_delta": {"brier": None, "log_loss": None},
            "closing_market_comparable": 0,
            "closing_movement": {"average_probability_pp": None, "median_probability_pp": None, "positive_direction_pct": None},
        }
        write_json(self.root / "data/validation/green-strong-v1.json", {
            "generated_at_utc": NOW,
            "claims": "EXPERIMENTAL_NOT_VALIDATED",
            "metrics": green_metrics,
            "eligible_observations": [{"snapshot_key": "wta:2"}],
            "guerra_selection_v1": {"status": "UNAVAILABLE"},
        })
        market_eval = {"sample_size": 1, "accuracy_pct": 100.0, "brier_score": 0.16, "log_loss": 0.51}
        write_json(self.root / "data/market_ledger/derived/market-memory-v1.json", {
            "generated_at_utc": NOW,
            "claims": "EXPERIMENTAL_NOT_VALIDATED",
            "observation_count": 2,
            "events": [{
                "event_key": "atp:1",
                "entry_market_probabilities": {"a": 0.4, "b": 0.6},
                "last_valid_prestart_market_probabilities": {"a": 0.45, "b": 0.55},
            }],
            "evaluation": {"market_only": market_eval, "market_plus_sharp": market_eval},
        })
        ledger = self.root / "data/market_ledger/observations/2026-09-06.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"record_type": "MARKET_OBSERVATION", "observation_id": str(i), "capture": {"captured_at_utc": NOW}, "event": {"event_key": "atp:1"}}
            for i in range(2)
        ]
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        write_json(self.root / "data/run_metrics_log.json", [{
            "timestamp": NOW, "status": "success", "phase": "complete", "eligible": 2,
            "processed": 2, "analysis_failed": 0, "reports_failed": 0,
            "rapidapi_calls": 10, "llm_calls": 0, "llm_estimated_cost_usd": 0,
            "duration_seconds": 12.5,
        }])
        self._report(f"alpha-vs-beta-2026-09-06-{RID_GREEN}.html", "Alpha vs Beta")
        self._report(f"gamma-vs-delta-2026-09-06-{RID_YELLOW}.html", "Gamma vs Delta")

    def build(self):
        return dashboard.build_dashboard(root=self.root, generated_at_utc=NOW)

    def test_build_without_any_source_uses_unavailable_not_artificial_zero(self):
        result = self.build()
        self.assertEqual(result["global"]["total_reports"], None)
        self.assertEqual(result["global"]["total_snapshots"], None)
        self.assertEqual(result["market_memory"]["total_observations"], None)
        self.assertEqual(result["system_health"]["status"], "UNKNOWN")

    def test_snapshot_totals_and_settled_are_counted(self):
        self._base_sources()
        result = self.build()
        self.assertEqual(result["global"]["total_snapshots"], 2)
        self.assertEqual(result["global"]["settled_snapshots"], 1)

    def test_pending_snapshot_does_not_count_as_settled(self):
        self._base_sources()
        self.assertEqual(self.build()["report_history"]["snapshot_universe"], {"total": 2, "settled": 1})

    def test_colors_do_not_conflate_green_strong(self):
        self._base_sources()
        result = self.build()
        self.assertEqual(result["global"]["report_colors"]["GREEN"], 1)
        self.assertEqual(result["global"]["report_colors"]["YELLOW"], 1)
        self.assertEqual(result["global"]["green_strong_candidates"], 1)
        self.assertTrue(result["days"][0]["reports"][1]["green_strong"])

    def test_green_strong_zero_is_explicit_and_html_explains_no_conclusion(self):
        self._base_sources()
        path = self.root / "data/validation/green-strong-v1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["metrics"]["sample_size"] = 0
        value["eligible_observations"] = []
        write_json(path, value)
        result = self.build()
        self.assertEqual(result["green_strong_v1"]["sample"]["candidates"], 0)
        self.assertIn("N=0 — acumulação prospetiva iniciada", dashboard.render_dashboard_html(result))

    def test_green_strong_metrics_are_copied_without_recalculation(self):
        self._base_sources()
        path = self.root / "data/validation/green-strong-v1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["metrics"].update({
            "win_rate_pct": 37.12,
            "market": {"sample_size": 7, "brier_score": 0.271234, "log_loss": 0.812345},
            "fenzobot": {"sample_size": 7, "brier_score": 0.251111, "log_loss": 0.799999},
            "paired_delta": {"brier": -0.020123, "log_loss": -0.012346},
        })
        write_json(path, value)
        panel = self.build()["green_strong_v1"]
        self.assertEqual(panel["forecast"]["observed_win_rate_pct"], 37.12)
        self.assertEqual(panel["proper_scoring"]["market_brier"], 0.271234)
        self.assertEqual(panel["proper_scoring"]["delta_log_loss"], -0.012346)

    def test_guerra_selection_is_allowlisted_aggregate_only(self):
        self._base_sources()
        path = self.root / "data/validation/green-strong-v1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["guerra_selection_v1"] = {
            "status": "AVAILABLE", "eligible_green_strong": 5, "selected_candidates": 2,
            "selection_rate_pct": 40.0, "paper_entries": 3, "summary": summary(3, 2, 1, 2, 0),
            "snapshot_keys": ["PRIVATE-KEY"], "names": ["PRIVATE-NAME"], "notes": "PRIVATE-NOTE",
        }
        write_json(path, value)
        result = self.build()
        serialized = json.dumps(result)
        self.assertEqual(result["guerra_selection_v1"]["selected_candidates"], 2)
        self.assertNotIn("PRIVATE-KEY", serialized)
        self.assertNotIn("PRIVATE-NAME", serialized)
        self.assertNotIn("PRIVATE-NOTE", serialized)

    def test_underdog_pair_completeness_is_copied(self):
        self._base_sources()
        path = self.root / "data/validation/green-strong-v1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["guerra_selection_v1"] = {
            "status": "AVAILABLE", "summary": {},
            "underdog_pair_completeness": {
                "underdog_selected_candidates": 4,
                "complete_moneyline_positive_handicap_pairs": 2,
                "moneyline_only": 1, "positive_handicap_only": 1,
                "incomplete_or_unrecognized": 0,
            },
        }
        write_json(path, value)
        pair = self.build()["guerra_selection_v1"]["underdog_pair_completeness"]
        self.assertEqual(pair["complete_moneyline_positive_handicap_pairs"], 2)
        self.assertEqual(pair["positive_handicap_only"], 1)

    def test_paper_universes_remain_separate(self):
        self._base_sources()
        result = self.build()
        self.assertEqual(result["paper_technical"]["total_entries"], 1)
        self.assertEqual(result["paper_22bet"]["total_entries"], 3)

    def test_market_observation_count_uses_existing_derived_metric(self):
        self._base_sources()
        result = self.build()
        self.assertEqual(result["market_memory"]["total_observations"], 2)
        self.assertEqual(result["market_memory"]["observations_by_day"][-1]["observations"], 2)

    def test_closing_coverage_uses_only_comparable_closing(self):
        self._base_sources()
        path = self.root / "data/market_ledger/derived/market-memory-v1.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["events"].append({"event_key": "wta:2", "entry_market_probabilities": {"a": 0.5, "b": 0.5}})
        write_json(path, value)
        market = self.build()["market_memory"]
        self.assertEqual(market["events_with_comparable_closing"], 1)
        self.assertEqual(market["closing_coverage_pct"], 50.0)

    def test_system_health_reuses_existing_alerts(self):
        self._base_sources()
        path = self.root / "data/run_metrics_log.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value[-1]["rapidapi_calls"] = 700
        write_json(path, value)
        with patch.dict(os.environ, {"ALERT_RAPIDAPI_CALLS": "600"}):
            panel = self.build()["system_health"]
        self.assertEqual(panel["status"], "DEGRADED")
        self.assertEqual(panel["alerts"], run_metrics.health_alerts(value[-1]))

    def test_failed_run_has_failed_status(self):
        self._base_sources()
        path = self.root / "data/run_metrics_log.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value[-1]["status"] = "failed"
        write_json(path, value)
        self.assertEqual(self.build()["system_health"]["status"], "FAILED")

    def test_unrecognized_or_missing_run_status_is_unknown(self):
        self._base_sources()
        path = self.root / "data/run_metrics_log.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value[-1]["status"] = "future-state"
        write_json(path, value)
        result = self.build()["system_health"]
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["recent_runs"][-1]["status"], "UNKNOWN")
        value[-1].pop("status")
        write_json(path, value)
        self.assertEqual(self.build()["system_health"]["status"], "UNKNOWN")

    def test_legacy_report_is_listed_without_fuzzy_linkage(self):
        self._base_sources()
        self._report("alpha-vs-beta-2026-09-05.html", "Alpha 1 vs Beta 1")
        legacy = next(row for day in self.build()["days"] for row in day["reports"] if row["date"] == "2026-09-05")
        self.assertEqual(legacy["linkage"], "LEGACY_UNLINKED")
        self.assertEqual(legacy["color"], "UNAVAILABLE")
        self.assertIsNone(legacy["scheduled_start_utc"])

    def test_report_id_linkage_is_exact(self):
        self._base_sources()
        report = next(row for row in self.build()["days"][0]["reports"] if row["title"] == "Alpha 1 vs Beta 1")
        self.assertEqual(report["linkage"], "EXACT_REPORT_ID")
        self.assertEqual(report["color"], "GREEN")
        self.assertTrue(report["paper_technical"])

    def test_exact_report_id_has_priority_over_self_described_color(self):
        self._base_sources()
        path = self.root / "docs/relatorios" / f"alpha-vs-beta-2026-09-06-{RID_GREEN}.html"
        path.unlink()
        self._report(path.name, "Alpha vs Beta", color="RED")
        report = next(row for row in self.build()["days"][0]["reports"] if row["title"] == "Alpha 1 vs Beta 1")
        self.assertEqual(report["linkage"], "EXACT_REPORT_ID")
        self.assertEqual(report["color"], "GREEN")

    def test_rerun_with_new_report_id_uses_self_described_canonical_color(self):
        self._base_sources()
        self._report("alpha-vs-beta-2026-09-06-33333333333333333333.html", "Alpha rerun", color="RED")
        rerun = next(row for row in self.build()["days"][0]["reports"] if row["title"] == "Alpha rerun")
        self.assertEqual(rerun["linkage"], "SELF_DESCRIBED_REPORT")
        self.assertEqual(rerun["color"], "RED")
        self.assertFalse(rerun["green_strong"])
        self.assertFalse(rerun["paper_technical"])

    def test_known_historical_dom_contract_is_not_a_css_class_shortcut(self):
        self._base_sources()
        self._report(
            "known-vs-contract-2026-09-05-44444444444444444444.html",
            "Known contract",
            decision_state="EDGE_NEGATIVE",
        )
        known = next(row for day in self.build()["days"] for row in day["reports"] if row["title"] == "Known contract")
        self.assertEqual(known["linkage"], "HISTORICAL_DOM_CONTRACT")
        self.assertEqual(known["color"], "RED")
        self.assertFalse(known["green_strong"])
        self.assertFalse(known["paper_technical"])

        fake = self._report("fake-vs-class-2026-09-05.html", "Fake class")
        fake.write_text(
            '<!doctype html><title>Fake class</title><section class="decision-box negative">not canonical</section>',
            encoding="utf-8",
        )
        fake_row = next(row for day in self.build()["days"] for row in day["reports"] if row["title"] == "Fake class")
        self.assertEqual(fake_row["linkage"], "LEGACY_UNLINKED")
        self.assertEqual(fake_row["color"], "UNAVAILABLE")

    def test_supported_report_markers_reduce_unavailable_without_inference(self):
        self._base_sources()
        for index, color in enumerate(("GREEN", "YELLOW", "RED", "GREEN", "RED")):
            self._report(
                f"marked-{index}-vs-player-2026-09-05-{index + 5:020x}.html",
                f"Marked {index}",
                color=color,
            )
        self._report("unknown-vs-player-2026-09-05.html", "Unknown legacy")
        day = next(item for item in self.build()["days"] if item["date"] == "2026-09-05")
        self.assertEqual(day["counts"]["UNAVAILABLE"], 1)
        self.assertLess(day["counts"]["UNAVAILABLE"], day["counts"]["reports"] / 2)
        self.assertEqual(day["counts"]["GREEN_STRONG"], 0)
        self.assertEqual(day["counts"]["PAPER_TECHNICAL"], 0)

    def test_private_sheet_fields_never_enter_outputs(self):
        self._base_sources()
        os.environ["DASHBOARD_TEST_SECRET"] = "SECRET-MUST-NOT-LEAK"
        try:
            result = self.build()
            rendered = dashboard.render_dashboard_html(result)
        finally:
            os.environ.pop("DASHBOARD_TEST_SECRET", None)
        self.assertNotIn("SECRET-MUST-NOT-LEAK", json.dumps(result))
        self.assertNotIn("SECRET-MUST-NOT-LEAK", rendered)

    def test_script_json_escapes_script_termination(self):
        value = {"title": "</script><script>alert(1)</script>"}
        rendered = dashboard.render_dashboard_html({
            "generated_at_utc": NOW, "days": [], "global": {}, "source_freshness": {},
            "report_history": {}, "green_strong_v1": {}, "guerra_selection_v1": {},
            "market_memory": {}, "paper_technical": {}, "paper_22bet": {}, "system_health": {},
            **value,
        })
        self.assertNotIn("</script><script>alert(1)</script>", rendered)

    def test_generation_makes_no_network_or_llm_call(self):
        self._base_sources()
        with patch("socket.create_connection", side_effect=AssertionError("network")), patch(
            "src.analyze.analyze_match", side_effect=AssertionError("llm")
        ) as llm:
            result = self.build()
        self.assertEqual(result["mode"], "READ_ONLY_DERIVED_DASHBOARD")
        llm.assert_not_called()

    def test_best_effort_boundary_swallows_dashboard_failure(self):
        with patch("src.dashboard.build_and_write", side_effect=RuntimeError("boom")):
            status = dashboard.build_and_write_best_effort(root=self.root)
        self.assertEqual(status["status"], "UNAVAILABLE")
        self.assertIn("RuntimeError", status["error"])

    def test_report_links_resolve_to_existing_files(self):
        self._base_sources()
        for day in self.build()["days"]:
            for report in day["reports"]:
                filename = report["url"].split("/")[-1]
                self.assertTrue((self.root / "docs/relatorios" / filename).exists())

    def test_build_and_write_generates_dashboard_route_and_contract(self):
        self._base_sources()
        result = dashboard.build_and_write(root=self.root, generated_at_utc=NOW)
        self.assertTrue((self.root / "docs/dashboard/index.html").exists())
        saved = json.loads((self.root / "data/dashboard/fenzobot-dashboard-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["change_id"], dashboard.CHANGE_ID)
        self.assertEqual(saved["semantic_fingerprint"], result["semantic_fingerprint"])

    def test_html_contains_global_day_toggle_and_sidebar(self):
        self._base_sources()
        rendered = dashboard.render_dashboard_html(self.build())
        self.assertIn('id="global-toggle"', rendered)
        self.assertIn('id="day-toggle"', rendered)
        self.assertIn("Histórico de relatórios", rendered)

    def test_sidebar_groups_days_descending(self):
        self._base_sources()
        self._report("old-vs-report-2026-09-05.html", "Old vs Report")
        days = self.build()["days"]
        self.assertEqual([day["date"] for day in days], ["2026-09-06", "2026-09-05"])

    def test_rendering_and_filters_do_not_mutate_data(self):
        self._base_sources()
        result = self.build()
        before = copy.deepcopy(result)
        rendered = dashboard.render_dashboard_html(result)
        self.assertEqual(result, before)
        self.assertIn("data-filter", rendered)

    def test_missing_individual_source_degrades_only_its_panel(self):
        self._base_sources()
        (self.root / "data/manual_paper_22bet.json").unlink()
        result = self.build()
        self.assertEqual(result["paper_22bet"]["status"], "UNAVAILABLE")
        self.assertEqual(result["paper_technical"]["status"], "AVAILABLE")
        self.assertEqual(result["market_memory"]["status"], "AVAILABLE")

    def test_invalid_source_is_nd_not_zero(self):
        self._base_sources()
        (self.root / "data/calibration_snapshots.json").write_text("not-json", encoding="utf-8")
        result = self.build()
        self.assertIsNone(result["global"]["total_snapshots"])
        self.assertEqual(result["source_freshness"]["snapshots"]["status"], "INVALID")

    def test_semantic_noop_preserves_generated_timestamp(self):
        self._base_sources()
        first = dashboard.build_and_write(root=self.root, generated_at_utc=NOW)
        second = dashboard.build_and_write(root=self.root, generated_at_utc="2026-09-06T21:00:00+00:00")
        self.assertEqual(second["generated_at_utc"], first["generated_at_utc"])

    def test_public_dashboard_contains_no_snapshot_keys(self):
        self._base_sources()
        serialized = json.dumps(self.build())
        self.assertNotIn('"snapshot_key"', serialized)
        self.assertNotIn("atp:1", serialized)


if __name__ == "__main__":
    unittest.main()
