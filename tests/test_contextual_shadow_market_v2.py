import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import capture_contextual_shadow_market_v2 as runner
from scripts.generated_output_contract import is_allowed
from src import contextual_shadow_market_v2 as market
from src import contextual_shadow_settlement_v2 as settlement


def observation(key="obs-1", *, tour="atp"):
    return {
        "schema_version": 2,
        "observation_id": key,
        "canonical_match_instance_id": f"canonical-{key}",
        "tour": tour,
        "tier": "ATP 500" if tour == "atp" else "WTA 500",
        "commence_time_utc": "2099-11-05T12:00:00+00:00",
        "analyzed_at_utc": "2026-11-04T10:00:00+00:00",
        "players": {
            "a": {"id": 10, "name": "Alpha"},
            "b": {"id": 20, "name": "Beta"},
        },
        "contextual_shadow": {
            "model_version": settlement.MODEL_VERSION,
            "configuration_fingerprint": "fingerprint",
            "status": "READY_FOR_PROSPECTIVE_SHADOW",
            "quality_group": "PRIMARY_READY_SECONDARY_GAPS",
            "surface_context": "hard_indoor",
            "probability_model_a": 0.6,
            "probability_model_b": 0.4,
            "probability_interval_90_model_a": [0.52, 0.68],
        },
    }


def fixture(*, date="2099-11-05T12:00:00+00:00"):
    return {
        "id": 99,
        "_tour": "atp",
        "date": date,
        "player1Id": 20,
        "player2Id": 10,
        "player1": {"id": 20, "name": "Beta"},
        "player2": {"id": 10, "name": "Alpha"},
        "tournament_name": "Paris Masters",
    }


def provenance(*, captured="2026-11-04T10:01:00+00:00"):
    return {
        "source": "Test bookmaker feed",
        "endpoint": "https://example.invalid/odds",
        "event_id": "event-99",
        "captured_at_utc": captured,
        "provider_timestamp": captured,
        "bookmaker": "Book A",
        "raw_payload_sha256": "abc",
        "operational_pricing_eligible": True,
    }


class ContextualShadowMarketTests(unittest.TestCase):
    def test_fixture_link_requires_exact_ids_tour_and_time(self):
        row = observation()
        self.assertEqual(market.match_fixture(row, [fixture()])["id"], 99)
        self.assertIsNone(market.match_fixture(row, [{
            **fixture(), "player1Id": 30,
        }]))
        self.assertIsNone(market.match_fixture(row, [{
            **fixture(), "_tour": "wta",
        }]))
        self.assertIsNone(market.match_fixture(row, [fixture(
            date="2099-11-05T18:00:00+00:00",
        )]))

    def test_market_quote_is_oriented_and_frozen_after_prediction(self):
        row = observation()
        result = market.build_market_observation(
            row, fixture(), {"Beta": 2.5, "Alpha": 1.6}, provenance(),
        )
        self.assertEqual(result["odds"], {"a": 1.6, "b": 2.5})
        self.assertAlmostEqual(
            sum(result["market_probability_devig"].values()), 1.0, 7,
        )
        self.assertTrue(result["first_valid_quote_frozen"])
        self.assertFalse(result["production_effect"])
        self.assertIsNone(market.build_market_observation(
            row, fixture(), {"Beta": 2.5, "Alpha": 1.6},
            provenance(captured="2026-11-04T09:59:00+00:00"),
        ))

    def test_changed_quote_is_appended_without_rewriting_first(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.jsonl"
            first = market.build_market_observation(
                observation(), fixture(), {"Beta": 2.5, "Alpha": 1.6},
                provenance(),
            )
            later = {
                **first,
                "market_observation_id": "later",
                "odds": {"a": 1.7, "b": 2.3},
            }
            self.assertEqual(market.append_markets([first], path), 1)
            self.assertEqual(market.append_markets([later], path), 1)
            self.assertEqual(market.append_markets([later], path), 0)
            saved = market.read_markets(path)
            self.assertEqual(saved[0]["odds"], {"a": 1.6, "b": 2.5})
            self.assertEqual(saved[1]["odds"], {"a": 1.7, "b": 2.3})

    def test_evaluation_uses_first_valid_quote_when_later_snapshot_exists(self):
        row = observation()
        first = market.build_market_observation(
            row, fixture(), {"Beta": 2.5, "Alpha": 1.6}, provenance(),
        )
        later = market.build_market_observation(
            row, fixture(), {"Beta": 2.3, "Alpha": 1.7},
            provenance(captured="2026-11-04T11:01:00+00:00"),
        )
        outcome = {
            "observation_id": "obs-1", "winner_side": "a",
            "canonical_match_instance_id": "canonical-obs-1",
            "configuration_fingerprint": "fingerprint",
            "model_version": settlement.MODEL_VERSION,
        }
        result = settlement.build_evaluation([row], [outcome], [later, first])
        self.assertEqual(result["market_audit"]["status"], "HEALTHY")
        self.assertEqual(result["counts"]["ready_settled_with_market"], 1)

    def test_evaluation_joins_frozen_market_only_after_result(self):
        row = observation()
        quote = market.build_market_observation(
            row, fixture(), {"Beta": 2.5, "Alpha": 1.6}, provenance(),
        )
        outcome = {
            "observation_id": "obs-1",
            "winner_side": "a",
            "canonical_match_instance_id": "canonical-obs-1",
            "configuration_fingerprint": "fingerprint",
            "model_version": settlement.MODEL_VERSION,
        }
        result = settlement.build_evaluation([row], [outcome], [quote])
        self.assertEqual(result["market_audit"]["status"], "HEALTHY")
        self.assertEqual(result["counts"]["ready_settled_with_market"], 1)
        self.assertEqual(result["market_benchmark"]["sample_size"], 1)
        self.assertEqual(
            result["validation_gate"]["status"], "INSUFFICIENT_SAMPLE",
        )
        self.assertFalse(result["validation_gate"]["automatic_promotion"])

    def test_market_audit_rejects_pre_prediction_capture(self):
        row = observation()
        quote = market.build_market_observation(
            row, fixture(), {"Beta": 2.5, "Alpha": 1.6}, provenance(),
        )
        quote["captured_at_utc"] = "2026-11-04T09:59:00+00:00"
        result = settlement.build_evaluation([row], [], [quote])
        self.assertEqual(result["market_audit"]["status"], "CONTRACT_VIOLATION")
        self.assertEqual(
            result["market_audit"]["violations"][0]["code"],
            "MARKET_NOT_POST_PREDICTION_PRESTART",
        )

    def test_capture_runner_has_no_operational_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations_path = root / "observations.jsonl"
            market_path = root / "market.jsonl"
            summary_path = root / "summary.json"
            observations_path.write_text(
                json.dumps(observation()) + "\n", encoding="utf-8",
            )
            frozen = market.build_market_observation(
                observation(), fixture(), {"Beta": 2.5, "Alpha": 1.6},
                provenance(),
            )
            with (
                patch.object(
                    runner.fetch_data, "fetch_resilient_discovery_fixtures",
                    return_value=[fixture()],
                ),
                patch.object(runner.fetch_data, "prepare_the_odds_market_index"),
                patch.object(runner.fetch_data, "prepare_rapidapi_odds_index"),
                patch.object(
                    runner.fetch_data,
                    "fetch_the_odds_moneyline_with_provenance",
                    return_value=({"Beta": 2.5, "Alpha": 1.6}, provenance()),
                ),
                patch.object(runner, "build_market_observation", return_value=frozen),
                patch.object(runner.fetch_data, "flush_tournament_cache"),
                patch.object(runner.fetch_data, "flush_fixtures_cache"),
                patch.object(runner.fetch_data, "persist_rapidapi_usage"),
                patch.object(
                    runner.fetch_data, "get_rapidapi_call_count", return_value=0,
                ),
            ):
                report = runner.capture(
                    observations_path=observations_path,
                    market_path=market_path,
                    summary_path=summary_path,
                )
            self.assertEqual(report["market_quotes_added"], 1)
            self.assertFalse(report["isolation"]["market_used_for_prediction"])
            self.assertFalse(report["isolation"]["paper_created"])
            self.assertTrue(summary_path.exists())

    def test_capture_falls_back_to_rapidapi_when_odds_api_has_no_finals_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations_path = root / "observations.jsonl"
            market_path = root / "market.jsonl"
            summary_path = root / "summary.json"
            finals_observation = observation()
            finals_observation["tier"] = "Finals"
            finals_fixture = {
                **fixture(),
                "tier": "Finals",
                "tournament_name": "Nitto ATP Finals - Turin",
            }
            observations_path.write_text(
                json.dumps(finals_observation) + "\n", encoding="utf-8",
            )
            rapid_provenance = {
                **provenance(),
                "source": "RapidAPI Tennis API / recent-odds",
            }
            with (
                patch.object(
                    runner.fetch_data, "fetch_resilient_discovery_fixtures",
                    return_value=[finals_fixture],
                ),
                patch.object(runner.fetch_data, "prepare_the_odds_market_index"),
                patch.object(runner.fetch_data, "prepare_rapidapi_odds_index"),
                patch.object(
                    runner.fetch_data,
                    "fetch_the_odds_moneyline_with_provenance",
                    return_value=(None, None),
                ),
                patch.object(
                    runner.fetch_data,
                    "fetch_rapidapi_recent_moneyline_with_provenance",
                    return_value=(
                        {"Beta": 2.5, "Alpha": 1.6}, rapid_provenance,
                    ),
                ),
                patch.object(runner.fetch_data, "flush_tournament_cache"),
                patch.object(runner.fetch_data, "flush_fixtures_cache"),
                patch.object(runner.fetch_data, "persist_rapidapi_usage"),
                patch.object(
                    runner.fetch_data, "get_rapidapi_call_count", return_value=0,
                ),
            ):
                report = runner.capture(
                    observations_path=observations_path,
                    market_path=market_path,
                    summary_path=summary_path,
                )

            self.assertEqual(report["market_quotes_added"], 1)
            self.assertEqual(
                report["source_counts"],
                {"RapidAPI Tennis API / recent-odds": 1},
            )

    def test_capture_uses_verified_upcoming_feed_as_third_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations_path = root / "observations.jsonl"
            market_path = root / "market.jsonl"
            summary_path = root / "summary.json"
            observations_path.write_text(
                json.dumps(observation()) + "\n", encoding="utf-8",
            )
            feed_provenance = {
                **provenance(),
                "source": "RapidAPI Tennis API / pre-match match-winner feed",
                "bookmaker": None,
                "bookmaker_attribution": "NOT_EXPOSED_BY_PROVIDER_FEED",
            }
            with (
                patch.object(
                    runner.fetch_data, "fetch_resilient_discovery_fixtures",
                    return_value=[fixture()],
                ),
                patch.object(runner.fetch_data, "prepare_the_odds_market_index"),
                patch.object(runner.fetch_data, "prepare_rapidapi_odds_index"),
                patch.object(
                    runner.fetch_data,
                    "fetch_the_odds_moneyline_with_provenance",
                    return_value=(None, None),
                ),
                patch.object(
                    runner.fetch_data,
                    "fetch_rapidapi_recent_moneyline_with_provenance",
                    return_value=(None, None),
                ),
                patch.object(
                    runner.fetch_data,
                    "fetch_rapidapi_upcoming_operational_moneyline_with_provenance",
                    return_value=(
                        {"Beta": 2.5, "Alpha": 1.6}, feed_provenance,
                    ),
                ),
                patch.object(runner.fetch_data, "flush_tournament_cache"),
                patch.object(runner.fetch_data, "flush_fixtures_cache"),
                patch.object(runner.fetch_data, "persist_rapidapi_usage"),
                patch.object(
                    runner.fetch_data, "get_rapidapi_call_count", return_value=0,
                ),
            ):
                report = runner.capture(
                    observations_path=observations_path,
                    market_path=market_path,
                    summary_path=summary_path,
                )

            self.assertEqual(report["market_quotes_added"], 1)
            self.assertEqual(report["source_counts"], {
                "RapidAPI Tennis API / pre-match match-winner feed": 1,
            })
            stored = json.loads(market_path.read_text(encoding="utf-8"))
            self.assertEqual(
                stored["bookmaker"],
                "RapidAPI pre-match feed (casa não identificada)",
            )

    def test_workflow_orders_prediction_before_market_and_evaluation(self):
        workflow = Path(".github/workflows/contextual-shadow-v2.yml").read_text(
            encoding="utf-8",
        )
        prediction = "python scripts/run_contextual_shadow_v2.py"
        benchmark = "python scripts/capture_contextual_shadow_market_v2.py"
        evaluation = "python scripts/settle_contextual_shadow_v2.py --evaluate-only"
        self.assertLess(workflow.index(prediction), workflow.index(benchmark))
        self.assertLess(workflow.index(benchmark), workflow.index(evaluation))
        self.assertIn("THE_ODDS_API_ENABLED: \"1\"", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertTrue(is_allowed(market.MARKET_PATH.as_posix(), "bot"))


if __name__ == "__main__":
    unittest.main()
