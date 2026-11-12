import json
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import build_contextual_shadow_report_preview_v2 as runner
from src import contextual_shadow_report_v2 as report


def observation():
    return {
        "schema_version": 2,
        "observation_id": "obs-1",
        "canonical_match_instance_id": "match-1",
        "tour": "atp",
        "tier": "ATP 500",
        "commence_time_utc": "2026-11-05T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-04T10:00:00+00:00",
        "players": {
            "a": {"id": 1, "name": "alpha player"},
            "b": {"id": 2, "name": "beta player"},
        },
        "competition": {
            "tournament_name": "Test Open",
            "round_stage": "LATE_STAGES",
            "surface": "Hard",
        },
        "contextual_shadow": {
            "model_version": "contextual-family-shadow-v2",
            "configuration_fingerprint": "fingerprint",
            "probability_model_a": 0.62,
            "probability_model_b": 0.38,
            "probability_interval_90_model_a": [0.54, 0.69],
            "fair_odd_model_a": {
                "central": 1.6129, "lower_odd": 1.4493, "upper_odd": 1.8519,
            },
            "fair_odd_model_b": {
                "central": 2.6316, "lower_odd": 2.1739, "upper_odd": 3.2258,
            },
            "families": [
                {
                    "key": "recent_form", "label": "Forma recente ajustada",
                    "probability_model_a": 0.66, "logit_contribution": 0.21,
                    "data_state": "OBSERVED",
                },
                {
                    "key": "matchup_h2h", "label": "Matchup e confronto direto",
                    "probability_model_a": None, "logit_contribution": 0.0,
                    "data_state": "OBSERVED_NONE",
                },
            ],
            "family_coverage": {"observed": 4, "total": 5, "pct": 80.0},
            "surface_context": "hard_indoor",
            "quality_group": "PRIMARY_READY_SECONDARY_GAPS",
            "status": "READY_FOR_PROSPECTIVE_SHADOW",
            "reason_codes": [],
            "calibration_bin_sample": 150,
            "interval_source": "PRIMARY_READY_SECONDARY_GAPS",
            "extrapolation": False,
            "market_used": False,
            "production_effect": False,
        },
        "paper_eligible": False,
        "green_eligible": False,
    }


def market():
    return {
        "observation_id": "obs-1",
        "model_version": "contextual-family-shadow-v2",
        "first_valid_quote_frozen": True,
        "production_effect": False,
        "odds": {"a": 1.9, "b": 2.0},
        "market_probability_devig": {"a": 0.51282051, "b": 0.48717949},
        "overround": 0.02631579,
        "bookmaker": "Test Book",
        "source": "Independent Test Market",
        "captured_at_utc": "2026-11-04T11:00:00+00:00",
    }


def handicap_evidence():
    def line(value):
        return {
            "line": value,
            "total": {"cover": 45, "push": 0, "miss": 35},
            "wins": {"cover": 36, "push": 0, "miss": 4},
            "losses": {"cover": 9, "push": 0, "miss": 31},
        }

    return {
        "observation_id": "obs-1",
        "model_version": "contextual-family-shadow-v2",
        "configuration_fingerprint": "fingerprint",
        "production_effect": False,
        "evidence_version": "contextual-shadow-handicap-evidence-v2.0",
        "handicap_evidence": {
            "format": "bo3",
            "players": {
                "a": {
                    "lines": {
                        "-2": line(-2.0),
                        "-2.5": line(-2.5),
                        "-3": line(-3.0),
                        "-3.5": line(-3.5),
                    },
                },
                "b": {"lines": {}},
            },
        },
    }


def moneyline_evidence():
    player = {
        "general": {
            "all": {"sample": 30, "wins": 19, "win_rate_pct": 63.3},
            "bo3": {"sample": 25, "wins": 16, "win_rate_pct": 64.0},
            "bo5": {"sample": 5, "wins": 3, "win_rate_pct": 60.0},
        },
        "buckets": {
            "1.81-2.00": {
                "all": {"sample": 8, "wins": 5, "win_rate_pct": 62.5},
                "bo3": {"sample": 7, "wins": 5, "win_rate_pct": 71.4},
                "bo5": {"sample": 1, "wins": 0, "win_rate_pct": 0.0},
            },
        },
        "source": "frozen-test",
        "odds_basis": "provider_pair",
    }
    return {
        "observation_id": "obs-1",
        "model_version": "contextual-family-shadow-v2",
        "configuration_fingerprint": "fingerprint",
        "production_effect": False,
        "moneyline_evidence": {
            "players": {"a": player, "b": player},
        },
    }


class ContextualShadowReportTests(unittest.TestCase):
    def test_contract_is_explicitly_non_operational(self):
        contract = report.load_report_contract()
        self.assertEqual(contract["mode"], "SHADOW_PREVIEW_ONLY")
        self.assertTrue(contract["rules"]["market_must_not_enter_model_probability"])
        self.assertTrue(contract["rules"]["handicap_requires_own_line_probability"])
        self.assertTrue(contract["rules"]["no_betting_recommendation"])

    def test_view_model_joins_market_without_recalculating_prediction(self):
        view = report.build_report_view_model(observation(), market())
        self.assertEqual(view["players"]["a"]["probability"], 0.62)
        self.assertAlmostEqual(
            view["players"]["a"]["market"]["probability_edge_pp"],
            10.717949,
        )
        self.assertFalse(view["market"]["used_for_prediction"])
        self.assertFalse(view["isolation"]["paper_eligible"])
        self.assertFalse(view["isolation"]["published_as_operational_report"])
        self.assertEqual(view["tournament_name"], "Test Open")
        self.assertEqual(view["round_stage"], "Fases finais")
        self.assertEqual(
            view["market"]["plausibility"]["status"],
            "OUTSIDE_MODEL_INTERVAL",
        )
        self.assertTrue(
            view["market"]["plausibility"]["requires_manual_review"]
        )

    def test_missing_market_remains_not_available(self):
        view = report.build_report_view_model(observation())
        self.assertFalse(view["market"]["available"])
        self.assertIsNone(view["players"]["a"]["market"]["odd"])
        self.assertIsNone(
            view["players"]["a"]["market"]["probability_edge_pp"]
        )

    def test_observed_none_is_visible_and_not_treated_as_missing_vote(self):
        view = report.build_report_view_model(observation(), market())
        h2h = next(row for row in view["families"] if row["key"] == "matchup_h2h")
        self.assertEqual(h2h["data_state_label"], "Consultado · sem ocorrências")
        self.assertEqual(h2h["direction"], "neutral")
        self.assertEqual(h2h["relative_contribution_pct"], 0.0)

    def test_confirmed_outcome_is_joined_for_validation_only(self):
        outcome = {"observation_id": "obs-1", "winner_side": "b"}
        view = report.build_report_view_model(observation(), market(), outcome)
        self.assertTrue(view["outcome"]["available"])
        self.assertEqual(view["outcome"]["winner_side"], "b")
        self.assertFalse(view["isolation"]["production_effect"])

    def test_html_is_visual_but_contains_no_operational_call_to_action(self):
        html = report.render_report_html(
            report.build_report_view_model(observation(), market())
        )
        self.assertIn("NÚCLEO DE PRICING", html)
        self.assertIn("MAPA DAS FAMÍLIAS", html)
        self.assertIn("SHADOW · SEM DECISÃO", html)
        self.assertIn("mercado nunca entra", html)
        self.assertIn("REVISÃO DE PLAUSIBILIDADE", html)
        self.assertIn("Odd observada", html)
        self.assertNotIn("REGISTAR PAPER", html)
        self.assertNotIn("APOSTAR", html)

    def test_frozen_handicap_evidence_is_rendered_as_human_review_only(self):
        quote = {**market(), "odds": {"a": 1.50, "b": 2.70}}
        prediction = copy.deepcopy(observation())
        prediction["contextual_shadow"].update({
            "probability_model_a": 0.75,
            "probability_model_b": 0.25,
            "probability_interval_90_model_a": [0.70, 0.80],
        })
        view = report.build_report_view_model(
            prediction, quote, None, handicap_evidence()
        )
        self.assertEqual(view["market_review"]["candidate_side"], "a")
        self.assertEqual(view["market_review"]["handicap"]["type"], "negative")
        html = report.render_report_html(view)
        self.assertIn("HANDICAPS DE ALPHA PLAYER · NEGATIVOS", html)
        self.assertIn("cobre quando vence", html)
        self.assertIn("SEM ENTRADA AUTOMÁTICA", html)
        self.assertNotIn("<small>logit</small>", html)

    def test_public_report_hides_internal_trace_and_uses_human_labels(self):
        html = report.render_report_html(
            report.build_report_view_model(observation(), market())
        )
        self.assertNotIn("Contrato e isolamento", html)
        self.assertNotIn("observation_id", html)
        self.assertNotIn("configuration_fingerprint", html)
        self.assertNotIn("contextual_recent_tier_win_credit_v7", html)
        self.assertIn("Vantagem global", html)

    def test_frozen_moneyline_history_shows_general_and_current_band(self):
        view = report.build_report_view_model(
            observation(), market(), None, None, moneyline_evidence()
        )
        history = view["players"]["a"]["moneyline_history"]
        self.assertEqual(history["general"]["sample"], 25)
        self.assertEqual(history["current_band_label"], "1.81-2.00")
        self.assertEqual(history["current_band"]["win_rate_pct"], 71.4)
        html = report.render_report_html(view)
        self.assertIn("WIN RATE MONEYLINE", html)
        self.assertIn("HISTÓRICO NESTA FAIXA DE ODD", html)
        self.assertIn("Dado descritivo", html)

    def test_public_header_names_market_capture_and_limits_handicap_cards(self):
        evidence = handicap_evidence()
        evidence["handicap_evidence"]["players"]["a"]["lines"].update({
            "-4": handicap_evidence()["handicap_evidence"]["players"]["a"]["lines"]["-2"],
            "-4.5": handicap_evidence()["handicap_evidence"]["players"]["a"]["lines"]["-2"],
        })
        prediction = copy.deepcopy(observation())
        prediction["contextual_shadow"].update({
            "probability_model_a": 0.75,
            "probability_model_b": 0.25,
            "probability_interval_90_model_a": [0.70, 0.80],
        })
        html = report.render_report_html(
            report.build_report_view_model(prediction, market(), None, evidence)
        )
        self.assertIn("ODD DE MERCADO CAPTURADA", html)
        self.assertIn("Favorito do modelo", html)
        self.assertIn("Faixa justa do favorito", html)
        self.assertIn("Valor Moneyline", html)
        self.assertNotIn("BENCHMARK DISPONÍVEL", html)
        self.assertNotIn("Ver todas as restantes linhas", html)
        self.assertLessEqual(html.count('class="line-card"'), 5)

    def test_single_family_dependency_is_visible_and_suppresses_markets(self):
        prediction = copy.deepcopy(observation())
        prediction["contextual_shadow"]["family_sensitivity"] = {
            "method": "LEAVE_ONE_FAMILY_OUT",
            "favorite_confirmed": False,
            "dependency_grade": "CRITICAL_DEPENDENCE",
            "dominant_family_if_unstable": "structural_strength",
            "scenarios": [],
        }
        view = report.build_report_view_model(prediction, market())
        self.assertEqual(
            view["market_review"]["status"], "FAVORITE_UNCONFIRMED"
        )
        html = report.render_report_html(view)
        self.assertIn("DEPENDÊNCIA CRÍTICA", html)
        self.assertIn("Mercados não formulados", html)

    def test_balanced_dependency_remains_visible_without_false_fatal_block(self):
        prediction = copy.deepcopy(observation())
        prediction["contextual_shadow"]["family_sensitivity"] = {
            "method": "LEAVE_ONE_FAMILY_OUT",
            "favorite_confirmed": False,
            "dependency_grade": "BALANCED_SENSITIVE",
            "dominant_family_if_unstable": "structural_strength",
            "scenarios": [],
        }
        view = report.build_report_view_model(prediction, market())
        self.assertNotEqual(view["market_review"]["status"], "FAVORITE_UNCONFIRMED")
        html = report.render_report_html(view)
        self.assertIn("JOGO EQUILIBRADO", html)

    def test_authorised_primary_family_lead_is_explained_not_blocked(self):
        prediction = copy.deepcopy(observation())
        prediction["contextual_shadow"]["family_sensitivity"] = {
            "method": "LEAVE_ONE_FAMILY_OUT",
            "favorite_confirmed": False,
            "dependency_grade": "MATERIAL_DEPENDENCE",
            "dominant_family_if_unstable": "structural_strength",
            "lead_authority": {
                "authorised": True, "active_components": 3,
                "aligned_components": 2,
            },
            "scenarios": [],
        }
        view = report.build_report_view_model(prediction, market())
        self.assertNotEqual(view["market_review"]["status"], "FAVORITE_UNCONFIRMED")
        html = report.render_report_html(view)
        self.assertIn("LIDERANÇA PRINCIPAL VÁLIDA", html)
        self.assertIn("evidência sólida", html)

    def test_builder_creates_private_index_reports_and_summary(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            observations = root / "observations.jsonl"
            markets = root / "markets.jsonl"
            outcomes = root / "outcomes.jsonl"
            handicap = root / "contextual_shadow_handicap_evidence-v2.jsonl"
            output = root / "preview"
            observations.write_text(
                json.dumps(observation(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            first_quote = market()
            latest_quote = {
                **market(),
                "captured_at_utc": "2026-11-04T12:00:00+00:00",
                "odds": {"a": 1.85, "b": 2.05},
            }
            markets.write_text(
                json.dumps(first_quote, ensure_ascii=False) + "\n"
                + json.dumps(latest_quote, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            outcomes.write_text("", encoding="utf-8")
            handicap.write_text(
                json.dumps(handicap_evidence(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            summary = runner.build_previews(
                output_dir=output,
                observations_path=observations,
                market_path=markets,
                outcomes_path=outcomes,
            )
            self.assertEqual(summary["reports_built"], 1)
            self.assertEqual(summary["with_market"], 1)
            self.assertEqual(summary["with_handicap_evidence"], 1)
            self.assertEqual(summary["with_moneyline_evidence"], 0)
            self.assertTrue((output / "index.html").exists())
            self.assertTrue((output / "report-obs-1.html").exists())
            html = (output / "report-obs-1.html").read_text(encoding="utf-8")
            self.assertIn("Movimento desde a leitura anterior", html)
            self.assertIn("1.90 → 1.85", html)
            self.assertFalse(summary["isolation"]["operational_reports_published"])

    def test_workflow_builds_and_uploads_preview_without_publishing_it(self):
        workflow = Path(".github/workflows/contextual-shadow-v2.yml").read_text(
            encoding="utf-8"
        )
        build = "python scripts/build_contextual_shadow_report_preview_v2.py"
        publish = "python scripts/stage_generated_outputs.py --profile bot"
        self.assertIn(build, workflow)
        self.assertIn("contextual-shadow-v2-report-preview-${{ github.run_id }}", workflow)
        self.assertLess(workflow.index(build), workflow.index(publish))
        self.assertIn("$RUNNER_TEMP/contextual-shadow-v2-report-preview", workflow)


if __name__ == "__main__":
    unittest.main()
