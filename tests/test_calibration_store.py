import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import calibration_store, match_identity_v2


class CalibrationStoreTests(unittest.TestCase):
    @staticmethod
    def _accuracy_snapshot(
        key, *, winner="a", tournament_coverage=None, odd_a=2.0, odd_b=2.0,
    ):
        snapshot = {
            "key": key,
            "tier": "Challenger 125",
            "metrics": {"divergencia": {
                "indice_evidencia_a": 80,
                "indice_evidencia_b": 20,
                "classificacao": {"nivel": 3},
                "mercado_favorece": "B",
                "indice_favorece": "A",
                "player_a": "A",
                "player_b": "B",
            }},
            "outcome": {"winner_side": winner},
            "market_odds_decimal": {"A": odd_a, "B": odd_b},
        }
        if tournament_coverage is not None:
            snapshot["tournament_coverage"] = tournament_coverage
        return snapshot

    def _payload(self):
        return {
            "match_id": "m1", "tour": "atp", "tournament_id": 8,
            "player_a_id": 10, "player_b_id": 20,
            "player_a": "A", "player_b": "B",
            "commence_time_utc": "2026-08-17T10:00:00+00:00",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "pressure_profile_a": {"matches": 20, "break_points_saved_pct": 65.0},
        }

    def test_duplicate_run_preserves_original_pre_match_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            first = calibration_store.build_snapshot(self._payload(), analyzed_at_utc="2026-08-16T08:00:00+00:00")
            changed = self._payload()
            changed["market_odds_decimal"] = {"A": 1.5, "B": 2.7}
            second = calibration_store.build_snapshot(changed, analyzed_at_utc="2026-08-16T09:00:00+00:00")
            self.assertEqual(calibration_store.upsert_snapshots([first], path), 1)
            self.assertEqual(calibration_store.upsert_snapshots([second], path), 0)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
            self.assertEqual(saved[0]["market_odds_decimal"]["A"], 1.8)

    def test_market_observation_link_is_frozen_with_snapshot(self):
        payload = self._payload()
        payload.update({
            "event_key": "atp:m1",
            "entry_market_observation_id": "observation-1",
            "reference_market_observation_ids": ["reference-1"],
            "market_memory_status": "RECORDED",
            "market_memory_eligible": True,
        })
        snapshot = calibration_store.build_snapshot(payload)
        self.assertEqual(snapshot["event_key"], "atp:m1")
        self.assertEqual(snapshot["entry_market_observation_id"], "observation-1")
        self.assertEqual(snapshot["reference_market_observation_ids"], ["reference-1"])
        self.assertTrue(snapshot["market_memory_eligible"])

    def test_settlement_updates_only_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshot = calibration_store.build_snapshot(self._payload(), analyzed_at_utc="2026-08-16T08:00:00+00:00")
            calibration_store.upsert_snapshots([snapshot], path)
            match = {
                "id": "m1", "player1Id": 10, "player2Id": 20,
                "match_winner": 20, "result_type": "completed", "result": "4-6 6-3 6-2",
            }
            self.assertEqual(calibration_store.settle_from_matches([match], path), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["outcome"]["winner_side"], "b")
            self.assertEqual(saved["metrics"], snapshot["metrics"])
            self.assertEqual(calibration_store.settle_from_matches([match], path), 0)

    def test_experimental_challenger_snapshot_is_persisted_and_settled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            payload = self._payload()
            payload.update({
                "tier": "Challenger 125",
                "tournament_coverage": {"mode": "EXPERIMENTAL_REPORT_ONLY"},
            })
            snapshot = calibration_store.build_snapshot(
                payload, analyzed_at_utc="2026-08-16T08:00:00+00:00"
            )
            self.assertEqual(calibration_store.upsert_snapshots([snapshot], path), 1)
            match = {
                "id": "m1", "player1Id": 10, "player2Id": 20,
                "match_winner": 20, "result_type": "completed", "result": "4-6 4-6",
            }
            self.assertEqual(calibration_store.settle_from_matches([match], path), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["tournament_coverage"]["mode"], "EXPERIMENTAL_REPORT_ONLY")
            self.assertEqual(saved["outcome"]["winner_side"], "b")

    def test_settlement_falls_back_to_players_and_date_when_api_ids_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshot = calibration_store.build_snapshot(
                self._payload(), analyzed_at_utc="2026-08-16T08:00:00+00:00",
            )
            calibration_store.upsert_snapshots([snapshot], path)
            match = {
                "id": "a-different-endpoint-id", "player1Id": 10, "player2Id": 20,
                "match_winner": 20, "result_type": "completed", "result": "4-6 4-6",
                "date": "2026-08-17T11:00:00Z",
            }
            self.assertEqual(calibration_store.settle_from_matches([match], path), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]
            self.assertEqual(saved["outcome"]["winner_side"], "b")

    def test_canonical_settlement_consults_only_same_player_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshot = calibration_store.build_snapshot(self._payload())
            snapshot.update({
                "identity_schema_version": match_identity_v2.SCHEMA_VERSION,
                "canonical_match_instance_id": "canonical-1",
            })
            calibration_store.upsert_snapshots([snapshot], path)
            relevant = {
                "id": "m1", "player1Id": 10, "player2Id": 20,
                "match_winner": 10, "result_type": "completed", "result": "6-4 6-4",
            }
            unrelated = {
                "id": "other", "player1Id": 30, "player2Id": 40,
                "match_winner": 30, "result_type": "completed", "result": "6-4 6-4",
            }
            with patch.object(
                calibration_store.match_identity_v2,
                "resolve_existing",
                return_value={"canonical_match_instance_id": "canonical-1"},
            ) as resolve:
                self.assertEqual(
                    calibration_store.settle_from_matches([unrelated, relevant], path), 1,
                )
            self.assertEqual(resolve.call_count, 1)
            self.assertEqual(resolve.call_args.args[0]["id"], "m1")

    def test_incomplete_match_is_not_settled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            calibration_store.upsert_snapshots([calibration_store.build_snapshot(self._payload())], path)
            match = {"id": "m1", "match_winner": 10, "result_type": "scheduled"}
            self.assertEqual(calibration_store.settle_from_matches([match], path), 0)

    def test_indicative_odds_are_provisional_below_minimum_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            document = {
                "schema_version": 1,
                "snapshots": [{
                    "metrics": {"divergencia": {
                        "indice_evidencia_a": 72, "indice_evidencia_b": 28,
                    }},
                    "outcome": {"winner_side": "a"},
                }],
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 72, "indice_evidencia_b": 28}, path, min_samples=3,
            )
            self.assertTrue(actual["available"])
            self.assertFalse(actual["calibrated"])
            self.assertTrue(actual["provisional"])
            self.assertEqual(actual["basis"], "historical")
            self.assertEqual(actual["sample_size"], 1)
            self.assertIn("players", actual)

    def test_indicative_odds_have_wide_heuristic_before_first_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            path.write_text(json.dumps({"schema_version": 1, "snapshots": []}), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 90, "indice_evidencia_b": 10}, path,
            )
            self.assertTrue(actual["available"])
            self.assertFalse(actual["calibrated"])
            self.assertEqual(actual["basis"], "heuristic")
            self.assertEqual(actual["sample_size"], 0)
            self.assertGreater(actual["players"]["a"]["odds_high"] - actual["players"]["a"]["odds_low"], 0.5)

    def test_indicative_odds_use_settled_results_and_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshots = []
            for winner in ("a", "a", "b"):
                snapshots.append({
                    "metrics": {"divergencia": {
                        "indice_evidencia_a": 72, "indice_evidencia_b": 28,
                    }},
                    "outcome": {"winner_side": winner},
                })
            path.write_text(json.dumps({"schema_version": 1, "snapshots": snapshots}), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 74, "indice_evidencia_b": 26}, path, min_samples=3,
            )
            self.assertTrue(actual["available"])
            self.assertTrue(actual["calibrated"])
            self.assertEqual(actual["sample_size"], 3)
            self.assertLess(actual["players"]["a"]["odds_low"], actual["players"]["a"]["odds_high"])
            self.assertGreater(actual["players"]["b"]["odds_low"], 1)

    def test_standard_accuracy_excludes_explicit_experiment_but_keeps_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            standard = [
                self._accuracy_snapshot(f"atp:{index}")
                for index in range(10)
            ]
            experimental = self._accuracy_snapshot(
                "atp:experimental",
                winner="b",
                tournament_coverage={"mode": "EXPERIMENTAL_REPORT_ONLY"},
            )
            path.write_text(json.dumps({
                "schema_version": 1,
                "snapshots": standard + [experimental],
            }), encoding="utf-8")
            accuracy = calibration_store.compute_system_accuracy(path)
            self.assertEqual(accuracy["divergencia"]["total"], 10)
            self.assertEqual(accuracy["divergencia"]["acertos"], 10)
            self.assertEqual(accuracy["divergencia"]["odds_retorno"]["roi_pct"], 100.0)

            legacy = [
                self._accuracy_snapshot(f"legacy:{index}")
                for index in range(10)
            ]
            path.write_text(json.dumps({
                "schema_version": 1,
                "snapshots": legacy,
            }), encoding="utf-8")
            legacy_accuracy = calibration_store.compute_system_accuracy(path)
            self.assertEqual(legacy_accuracy["divergencia"]["total"], 10)

    def test_accuracy_keeps_return_by_regime_separate_and_uses_frozen_odd(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            aligned = []
            for index in range(10):
                snapshot = self._accuracy_snapshot(
                    f"aligned:{index}",
                    winner="a" if index < 7 else "b",
                    odd_a=1.5,
                )
                divergence = snapshot["metrics"]["divergencia"]
                divergence["classificacao"] = {"nivel": 0}
                divergence["mercado_favorece"] = "A"
                divergence["indice_favorece"] = "A"
                aligned.append(snapshot)
            divergent = [
                self._accuracy_snapshot(
                    f"divergent:{index}",
                    winner="a" if index < 5 else "b",
                    odd_a=2.5,
                )
                for index in range(10)
            ]
            path.write_text(json.dumps({
                "schema_version": 1,
                "snapshots": aligned + divergent,
            }), encoding="utf-8")

            accuracy = calibration_store.compute_system_accuracy(path)
            alignment = accuracy["alinhamento_forte"]["odds_retorno"]
            divergence = accuracy["divergencia"]["odds_retorno"]

            self.assertEqual(alignment["odds_sample_size"], 10)
            self.assertEqual(alignment["average_odd"], 1.5)
            self.assertEqual(alignment["break_even_pct"], 66.7)
            self.assertEqual(alignment["roi_pct"], 5.0)
            self.assertEqual(divergence["odds_sample_size"], 10)
            self.assertEqual(divergence["average_odd"], 2.5)
            self.assertEqual(divergence["roi_pct"], 25.0)

    def test_alignment_minimum_odd_excludes_lower_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            snapshots = []
            for index in range(10):
                snapshot = self._accuracy_snapshot(
                    f"eligible:{index}",
                    winner="a" if index < 6 else "b",
                    odd_a=1.25,
                )
                divergence = snapshot["metrics"]["divergencia"]
                divergence["classificacao"] = {"nivel": 0}
                divergence["mercado_favorece"] = "A"
                divergence["indice_favorece"] = "A"
                snapshots.append(snapshot)
            for index in range(2):
                snapshot = self._accuracy_snapshot(
                    f"lower:{index}", winner="a", odd_a=1.24,
                )
                divergence = snapshot["metrics"]["divergencia"]
                divergence["classificacao"] = {"nivel": 0}
                divergence["mercado_favorece"] = "A"
                divergence["indice_favorece"] = "A"
                snapshots.append(snapshot)
            path.write_text(json.dumps({
                "schema_version": 1, "snapshots": snapshots,
            }), encoding="utf-8")

            accuracy = calibration_store.compute_system_accuracy(path)
            filtered = accuracy["alinhamento_odd_min_125"]
            self.assertEqual(accuracy["alinhamento_forte"]["total"], 12)
            self.assertEqual(filtered["minimum_odd"], 1.25)
            self.assertEqual(filtered["total"], 10)
            self.assertEqual(filtered["acertos"], 6)
            self.assertEqual(filtered["taxa_pct"], 60.0)
            self.assertEqual(filtered["odds_retorno"]["odds_sample_size"], 10)

    def test_experimental_outcome_does_not_change_standard_indicative_odds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            standard = [
                self._accuracy_snapshot("atp:1", winner="a"),
                self._accuracy_snapshot("atp:2", winner="a"),
                self._accuracy_snapshot("atp:3", winner="b"),
            ]
            path.write_text(json.dumps({
                "schema_version": 1,
                "snapshots": standard,
            }), encoding="utf-8")
            divergence = {"indice_evidencia_a": 82, "indice_evidencia_b": 18}
            baseline = calibration_store.estimate_indicative_odds(
                divergence, path, min_samples=3
            )
            standard.append(self._accuracy_snapshot(
                "atp:experimental",
                winner="b",
                tournament_coverage={"mode": "EXPERIMENTAL_REPORT_ONLY"},
            ))
            path.write_text(json.dumps({
                "schema_version": 1,
                "snapshots": standard,
            }), encoding="utf-8")
            with_experiment = calibration_store.estimate_indicative_odds(
                divergence, path, min_samples=3
            )
            self.assertEqual(with_experiment, baseline)
            self.assertEqual(with_experiment["sample_size"], 3)

    def test_quarantined_snapshot_is_excluded_from_calibration_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots = root / "snapshots.json"
            exclusions = root / "exclusions.json"
            snapshots.write_text(json.dumps({"schema_version": 1, "snapshots": [
                {"key": "atp:1241", "metrics": {"divergencia": {
                    "indice_evidencia_a": 72, "indice_evidencia_b": 28,
                }}, "outcome": {"winner_side": "a"}},
                {"key": "atp:2", "metrics": {"divergencia": {
                    "indice_evidencia_a": 72, "indice_evidencia_b": 28,
                }}, "outcome": {"winner_side": "b"}},
            ]}), encoding="utf-8")
            exclusions.write_text(json.dumps({"exclusions": [{
                "snapshot_key": "atp:1241", "reason_code": "MARKET_BOUNDARY_SENTINEL",
            }]}), encoding="utf-8")
            actual = calibration_store.estimate_indicative_odds(
                {"indice_evidencia_a": 72, "indice_evidencia_b": 28}, snapshots,
                min_samples=3, exclusions_path=exclusions,
            )
        self.assertEqual(actual["sample_size"], 1)


if __name__ == "__main__":
    unittest.main()
