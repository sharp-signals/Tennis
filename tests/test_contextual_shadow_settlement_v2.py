import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import settle_contextual_shadow_v2 as runner
from scripts.generated_output_contract import is_allowed
from src import contextual_shadow_settlement_v2 as settlement


def observation(
    key="obs-1", *, status="READY_FOR_PROSPECTIVE_SHADOW",
    probability=0.7, tour="atp", commence="2026-11-01T12:00:00Z",
):
    return {
        "schema_version": 2,
        "observation_id": key,
        "canonical_match_instance_id": f"canonical-{key}",
        "tour": tour,
        "tier": "ATP 500" if tour == "atp" else "WTA 500",
        "commence_time_utc": commence,
        "players": {
            "a": {"id": 10, "name": "Alpha"},
            "b": {"id": 20, "name": "Beta"},
        },
        "contextual_shadow": {
            "model_version": settlement.MODEL_VERSION,
            "configuration_fingerprint": "fingerprint",
            "status": status,
            "quality_group": "PRIMARY_READY_SECONDARY_GAPS",
            "surface_context": "hard_indoor",
            "probability_model_a": probability,
            "probability_model_b": 1 - probability,
            "probability_interval_90_model_a": [
                max(0.01, probability - 0.1),
                min(0.99, probability + 0.1),
            ],
        },
    }


def completed_match(*, winner=10, date="2026-11-01T13:00:00Z", match_id=99):
    return {
        "id": match_id,
        "player1Id": 10,
        "player2Id": 20,
        "match_winner": winner,
        "date": date,
        "result_type": "completed",
        "result": "6-4 6-4",
    }


class ContextualShadowSettlementTests(unittest.TestCase):
    def test_bounded_batch_balances_old_retries_and_recent_results(self):
        rows = [
            observation(
                str(index),
                commence=f"2026-11-{index + 1:02d}T12:00:00Z",
            )
            for index in range(10)
        ]
        selected = runner._bounded_pending_batch(rows, 5)
        self.assertEqual(
            [row["observation_id"] for row in selected],
            ["0", "6", "7", "8", "9"],
        )

    def test_workflow_runs_settlement_before_collection_and_can_publish_outputs(self):
        workflow = Path(
            ".github/workflows/contextual-shadow-v2.yml"
        ).read_text(encoding="utf-8")
        settlement_command = (
            "python scripts/settle_contextual_shadow_v2.py --max-observations 50"
        )
        collection_command = "python scripts/run_contextual_shadow_v2.py"
        self.assertLess(
            workflow.index(settlement_command), workflow.index(collection_command),
        )
        self.assertIn("timeout-minutes: 75", workflow)
        self.assertIn(
            "python scripts/settle_contextual_shadow_v2.py --evaluate-only",
            workflow,
        )
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertTrue(is_allowed(settlement.OUTCOMES_PATH.as_posix(), "bot"))
        self.assertTrue(is_allowed(settlement.EVALUATION_PATH.as_posix(), "bot"))

    def test_confirmed_outcome_requires_exact_pair_time_and_winner(self):
        row = observation()
        self.assertIsNone(settlement.confirmed_outcome(row, [
            {**completed_match(), "player2Id": 30},
        ]))
        self.assertIsNone(settlement.confirmed_outcome(row, [
            completed_match(date="2026-11-05T13:00:00Z"),
        ]))
        self.assertIsNone(settlement.confirmed_outcome(row, [
            completed_match(winner=30),
        ]))
        result = settlement.confirmed_outcome(row, [completed_match(winner=20)])
        self.assertEqual(result["winner_side"], "b")
        self.assertEqual(result["linkage"], "EXACT_PLAYER_IDS_AND_TIME_WINDOW")

    def test_walkover_is_preserved_but_excluded_from_primary_evaluation(self):
        row = observation()
        outcome = settlement.confirmed_outcome(
            row, [{**completed_match(), "result": "W/O"}],
        )
        self.assertEqual(outcome["contest_status"], "WALKOVER")
        self.assertFalse(outcome["primary_evaluation_eligible"])
        result = settlement.build_evaluation([row], [outcome])
        self.assertEqual(result["counts"]["ready_settled"], 0)
        self.assertEqual(
            result["counts"]["settled_excluded_by_reason"], {"WALKOVER": 1},
        )

    def test_ambiguous_equally_close_results_fail_closed(self):
        row = observation()
        self.assertIsNone(settlement.confirmed_outcome(row, [
            completed_match(date="2026-11-01T11:00:00Z", match_id=1),
            completed_match(date="2026-11-01T13:00:00Z", match_id=2),
        ]))

    def test_append_is_idempotent_and_rejects_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.jsonl"
            result = settlement.confirmed_outcome(
                observation(), [completed_match()],
            )
            self.assertEqual(settlement.append_outcomes([result], path), 1)
            self.assertEqual(settlement.append_outcomes([result], path), 0)
            conflict = {**result, "winner_side": "b", "winner_id": 20}
            with self.assertRaisesRegex(ValueError, "CONFLICTING_SHADOW_OUTCOME"):
                settlement.append_outcomes([conflict], path)
            self.assertEqual(len(settlement.read_jsonl(path)), 1)

    def test_evaluation_uses_only_ready_cohort_and_known_metrics(self):
        rows = [
            observation("a", probability=0.8),
            observation("b", probability=0.6, tour="wta"),
            observation("c", status="NOT_OPERATIONALLY_READY"),
        ]
        outcomes = [
            {
                "observation_id": key, "winner_side": side,
                "canonical_match_instance_id": f"canonical-{key}",
                "configuration_fingerprint": "fingerprint",
                "model_version": settlement.MODEL_VERSION,
            }
            for key, side in (("a", "a"), ("b", "b"), ("c", "a"))
        ]
        result = settlement.build_evaluation(rows, outcomes)
        self.assertEqual(result["counts"]["ready_settled"], 2)
        self.assertEqual(
            result["counts"]["settled_excluded_from_primary_metrics"], 1,
        )
        self.assertEqual(result["overall"]["accuracy_pct"], 50.0)
        self.assertEqual(result["overall"]["brier"], 0.2)
        self.assertAlmostEqual(result["overall"]["log_loss"], 0.569717, 6)
        self.assertEqual(result["by_tour"]["atp"]["sample_size"], 1)
        self.assertEqual(result["by_tour"]["wta"]["sample_size"], 1)
        self.assertFalse(result["promotion_authorized"])
        self.assertEqual(result["settlement_audit"]["status"], "HEALTHY")

    def test_evaluation_rejects_orphan_and_wrong_fingerprint(self):
        rows = [observation("a")]
        result = settlement.build_evaluation(rows, [{
            "observation_id": "a",
            "winner_side": "a",
            "canonical_match_instance_id": "canonical-a",
            "configuration_fingerprint": "wrong",
            "model_version": settlement.MODEL_VERSION,
        }, {
            "observation_id": "orphan",
            "winner_side": "b",
        }])
        self.assertEqual(result["evaluation_state"], "CONTRACT_VIOLATION")
        self.assertEqual(result["counts"]["ready_settled"], 0)
        self.assertEqual(
            {item["code"] for item in result["settlement_audit"]["violations"]},
            {"FINGERPRINT_MISMATCH", "ORPHAN_OR_MISSING_OBSERVATION_ID"},
        )

    def test_runner_settles_without_rewriting_prediction_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations_path = root / "observations.jsonl"
            outcomes_path = root / "outcomes.jsonl"
            evaluation_path = root / "evaluation.json"
            original = json.dumps(observation(), sort_keys=True) + "\n"
            observations_path.write_text(original, encoding="utf-8")
            with patch.object(
                runner.fetch_data, "fetch_player_recent_matches",
                return_value=[completed_match()],
            ) as fetch:
                report = runner.settle(
                    observations_path=observations_path,
                    outcomes_path=outcomes_path,
                    evaluation_path=evaluation_path,
                )
            self.assertEqual(report["outcomes_added"], 1)
            self.assertEqual(report["ready_settled"], 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(
                observations_path.read_text(encoding="utf-8"), original,
            )
            self.assertTrue(evaluation_path.exists())
            self.assertFalse(
                (root / "contextual_shadow_market-v2.jsonl").exists()
            )

    def test_evaluate_only_makes_no_result_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observations_path = root / "observations.jsonl"
            observations_path.write_text(
                json.dumps(observation()) + "\n", encoding="utf-8",
            )
            with patch.object(
                runner.fetch_data, "fetch_player_recent_matches",
            ) as fetch:
                report = runner.settle(
                    observations_path=observations_path,
                    outcomes_path=root / "outcomes.jsonl",
                    evaluation_path=root / "evaluation.json",
                    evaluate_only=True,
                )
            fetch.assert_not_called()
            self.assertTrue(report["evaluate_only"])
            self.assertEqual(report["pending_examined"], 0)
            self.assertEqual(report["market_observations"], 0)

    def test_cli_parser_accepts_evaluate_only(self):
        report = {"status": "COMPLETED"}
        with (
            patch("sys.argv", ["settle_contextual_shadow_v2.py", "--evaluate-only"]),
            patch.object(runner, "settle", return_value=report) as settle,
            patch("builtins.print") as output,
        ):
            self.assertEqual(runner.main(), 0)
        settle.assert_called_once_with(max_observations=50, evaluate_only=True)
        output.assert_called_once()


if __name__ == "__main__":
    unittest.main()

