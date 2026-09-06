import json
import inspect
import tempfile
import unittest
from pathlib import Path

from src import calibration_store, green_strong_validation, market_memory_report
from src import paper_trading
from src.report_html import _mod_green_strong_candidate


def eligible_payload():
    return {
        "match_id": 901,
        "event_key": "wta:901",
        "tour": "WTA",
        "player_a": "Alpha",
        "player_b": "Beta",
        "player_a_id": 1,
        "player_b_id": 2,
        "commence_time_utc": "2026-09-07T12:00:00+00:00",
        "divergencia": {
            "tipo": "direcao",
            "classificacao": {"nivel": 3},
            "indice_evidencia_a": 80,
            "indice_evidencia_b": 20,
            "indice_favorece": "Alpha",
        },
        "report_assessment": {"report_null": False},
        "prelive_decision": {
            "contract_version": "fenzobot-prelive-v1",
            "state": "EDGE_POSITIVE",
            "paper_eligible": True,
            "side": "a",
            "player": "Alpha",
        },
        "pricing": {
            "available": True,
            "candidate_side": "a",
            "model_version": "test-v1",
            "configuration_fingerprint": "abc",
            "market_probability_a": 0.45,
            "market_probability_b": 0.55,
            "sharp_estimate_a": 0.60,
            "sharp_estimate_b": 0.40,
        },
    }


class GreenStrongClassificationTests(unittest.TestCase):
    def classify(self, payload=None, **kwargs):
        return green_strong_validation.classify_snapshot(
            payload or eligible_payload(),
            snapshot_key="wta:901",
            classified_at_utc="2026-09-06T10:00:00+00:00",
            environment={},
            **kwargs,
        )

    def test_exact_contract_is_eligible_without_outcome_or_llm(self):
        result = self.classify()
        self.assertTrue(result["eligible"])
        self.assertEqual(result["status"], "ELIGIBLE")
        self.assertEqual(result["reason_codes"], [])
        self.assertNotIn("outcome", json.dumps(result).lower())
        self.assertNotIn("claude", json.dumps(result).lower())
        self.assertEqual(result["source"]["code_revision"], "UNAVAILABLE")

    def test_each_required_gate_fails_closed(self):
        mutations = (
            (lambda p: p["prelive_decision"].update(state="EDGE_NEGATIVE"), "DECISION_STATE_NOT_EDGE_POSITIVE"),
            (lambda p: p["prelive_decision"].update(state="EDGE_ZERO"), "DECISION_STATE_NOT_EDGE_POSITIVE"),
            (lambda p: p["prelive_decision"].update(state="EDGE_POSITIVE_COVERAGE_INSUFFICIENT"), "DECISION_STATE_NOT_EDGE_POSITIVE"),
            (lambda p: p["prelive_decision"].update(state="REPORT_NULL"), "DECISION_STATE_NOT_EDGE_POSITIVE"),
            (lambda p: p["prelive_decision"].update(paper_eligible=False), "PAPER_NOT_ELIGIBLE"),
            (lambda p: p["divergencia"].update(tipo="alinhamento"), "DIVERGENCE_TYPE_NOT_DIRECTION"),
            (lambda p: p["divergencia"]["classificacao"].update(nivel=2), "DIVERGENCE_LEVEL_NOT_STRONG"),
            (lambda p: p["prelive_decision"].update(side="b", player="Beta"), "SELECTED_SIDE_MISMATCH"),
            (lambda p: p["pricing"].update(available=False), "PRICING_UNAVAILABLE"),
            (lambda p: p["pricing"].update(market_probability_a=None), "PROBABILITIES_UNAVAILABLE"),
            (lambda p: p["pricing"].update(market_probability_a=.80), "PROBABILITIES_INCOHERENT"),
            (lambda p: p["prelive_decision"].update(conflict="test"), "INTEGRITY_CONFLICT"),
        )
        for mutate, reason in mutations:
            with self.subTest(reason=reason):
                payload = eligible_payload()
                mutate(payload)
                result = self.classify(payload)
                self.assertFalse(result["eligible"])
                self.assertEqual(result["status"], "INELIGIBLE")
                self.assertIn(reason, result["reason_codes"])

    def test_non_prospective_is_never_primary_cohort(self):
        result = self.classify(prospective=False)
        self.assertFalse(result["eligible"])
        self.assertIn("NOT_PROSPECTIVE", result["reason_codes"])

    def test_outcome_and_closing_fields_cannot_change_membership(self):
        payload = eligible_payload()
        before = self.classify(payload)
        payload["outcome"] = {"winner_side": "b"}
        payload["closing_market"] = {"a": .01, "b": .99}
        after = self.classify(payload)
        self.assertEqual(before, after)

    def test_classification_at_or_after_start_fails_closed(self):
        result = green_strong_validation.classify_snapshot(
            eligible_payload(), snapshot_key="wta:901",
            classified_at_utc="2026-09-07T12:00:00+00:00", environment={},
        )
        self.assertFalse(result["eligible"])
        self.assertIn("CLASSIFICATION_NOT_PRESTART", result["reason_codes"])

    def test_classifier_introduces_no_api_or_llm_dependency(self):
        source = inspect.getsource(green_strong_validation.classify_snapshot)
        self.assertNotIn("fetch", source.casefold())
        self.assertNotIn("llm", source.casefold())
        self.assertNotIn("outcome", source.casefold())

    def test_snapshot_first_write_wins_and_old_snapshot_is_not_reclassified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.json"
            old = {"key": "old", "analyzed_at_utc": "2026-01-01T00:00:00+00:00", "outcome": None}
            new = calibration_store.build_snapshot(eligible_payload(), analyzed_at_utc="2026-09-06T10:00:00+00:00")
            self.assertEqual(calibration_store.upsert_snapshots([old, new], path), 2)
            changed = dict(new)
            changed["validation"] = {"tampered": True}
            self.assertEqual(calibration_store.upsert_snapshots([changed], path), 0)
            rows = json.loads(path.read_text(encoding="utf-8"))["snapshots"]
            self.assertNotIn("validation", next(row for row in rows if row["key"] == "old"))
            self.assertIn("cohorts", next(row for row in rows if row["key"] == "wta:901")["validation"])

    def test_legacy_first_snapshot_controls_rerun_badge_and_derived_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots_path = root / "snapshots.json"
            legacy = {
                "key": "wta:901", "event_key": "wta:901", "match_id": 901,
                "analyzed_at_utc": "2026-09-01T10:00:00+00:00",
                "commence_time_utc": "2026-09-07T12:00:00+00:00", "outcome": None,
            }
            calibration_store.upsert_snapshots([legacy], snapshots_path)
            rerun_payload = eligible_payload()
            discarded = calibration_store.build_snapshot(
                rerun_payload, analyzed_at_utc="2026-09-06T10:00:00+00:00"
            )
            rerun_payload["validation"] = discarded["validation"]
            self.assertEqual(calibration_store.upsert_snapshots([discarded], snapshots_path), 0)
            persisted = calibration_store.read_snapshots_by_key(["wta:901"], snapshots_path)["wta:901"]
            calibration_store.apply_persisted_validation(rerun_payload, persisted)
            self.assertNotIn("validation", rerun_payload)
            self.assertEqual(_mod_green_strong_candidate(rerun_payload), "")
            memory = market_memory_report.build_report(
                ledger_root=root / "ledger", snapshots_path=snapshots_path,
                paper_path=root / "paper.json",
            )
            derived = green_strong_validation.build_report(memory_report=memory)
            self.assertNotIn("GREEN_STRONG_V1", memory["evaluation_by_cohort"])
            self.assertEqual(derived["metrics"]["sample_size"], 0)


class GreenStrongReportingTests(unittest.TestCase):
    def test_metrics_use_pricing_entry_and_comparable_closing_only(self):
        membership = self._membership()
        row = {
            "snapshot_key": "wta:901", "scheduled_start_utc": "2026-09-07T12:00:00+00:00",
            "tour": "WTA", "match_format": "BO3", "selected_side": "a",
            "selected_side_market_position": "UNDERDOG", "pricing_model_version": "v1",
            "pricing_configuration_fingerprint": "fp", "cohort_code_revision": "sha",
            "cohort_memberships": {"GREEN_STRONG_V1": membership},
            "pricing_market_probabilities": {"a": .45, "b": .55},
            "fenzobot_probabilities": {"a": .60, "b": .40},
            "last_valid_prestart_market_probabilities": {"a": .50, "b": .50},
            "outcome_side": "a",
        }
        report = green_strong_validation.build_report(memory_report={"events": [row]})
        self.assertEqual(report["metrics"]["settled_sample_size"], 1)
        self.assertEqual(report["metrics"]["win_rate_pct"], 100.0)
        self.assertEqual(report["metrics"]["closing_movement"]["average_probability_pp"], 5.0)
        self.assertEqual(report["segments"]["tour"]["WTA"]["sample_size"], 1)

    def test_old_untagged_and_ineligible_rows_are_excluded(self):
        bad = self._membership(); bad["eligible"] = False
        report = green_strong_validation.build_report(memory_report={"events": [
            {"snapshot_key": "old", "cohort_memberships": {}},
            {"snapshot_key": "bad", "cohort_memberships": {"GREEN_STRONG_V1": bad}},
        ]})
        self.assertEqual(report["metrics"]["sample_size"], 0)
        self.assertEqual(len(report["prospective_classifications"]), 1)

    def test_report_badge_only_for_eligible_snapshot(self):
        membership = self._membership()
        html = _mod_green_strong_candidate({"validation": {"cohorts": {"GREEN_STRONG_V1": membership}}})
        self.assertIn("candidato à validação", html)
        membership["eligible"] = False
        self.assertEqual(_mod_green_strong_candidate({"validation": {"cohorts": {"GREEN_STRONG_V1": membership}}}), "")

    def test_underdog_badge_explains_two_manual_legs(self):
        membership = self._membership()
        membership["source"]["market_probabilities"] = {"a": .40, "b": .60}
        html = _mod_green_strong_candidate({"validation": {"cohorts": {"GREEN_STRONG_V1": membership}}})
        self.assertIn("duas legs manuais", html)
        self.assertIn("Moneyline direto + Handicap games positivo", html)
        self.assertIn("nenhuma entrada ou handicap é automático", html)

    @staticmethod
    def _membership():
        return {
            "eligible": True, "validation_id": "valid-1", "selected_side": "a",
            "reason_codes": [], "source": {"snapshot_key": "wta:901"},
        }


class MarketMemoryCohortTests(unittest.TestCase):
    def test_probability_evaluation_is_well_defined_for_empty_and_settled(self):
        self.assertEqual(market_memory_report.evaluate_probabilities([], "p")["sample_size"], 0)
        result = market_memory_report.evaluate_probabilities(
            [{"outcome_side": "a", "p": {"a": .75, "b": .25}}], "p"
        )
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["accuracy_pct"], 100.0)

    def test_technical_paper_ignores_validation_overlay(self):
        payload = eligible_payload()
        payload["snapshot_key"] = "wta:901"
        payload["validation"] = {"cohorts": {"GREEN_STRONG_V1": {"eligible": True}}}
        with_overlay = paper_trading.build_entries(payload)
        payload.pop("validation")
        self.assertEqual(with_overlay, paper_trading.build_entries(payload))

    def test_market_memory_exposes_tagged_cohort_without_tagging_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = calibration_store.build_snapshot(
                eligible_payload(), analyzed_at_utc="2026-09-06T10:00:00+00:00"
            )
            (root / "snapshots.json").write_text(
                json.dumps({"snapshots": [snapshot, {"key": "legacy", "outcome": None}]}),
                encoding="utf-8",
            )
            report = market_memory_report.build_report(
                ledger_root=root / "ledger", snapshots_path=root / "snapshots.json",
                paper_path=root / "paper.json",
            )
            self.assertEqual(report["evaluation_by_cohort"]["GREEN_STRONG_V1"]["sample_size"], 1)
            self.assertIn("GREEN_STRONG_V1", report["events"][0]["cohort_memberships"])
            self.assertNotIn("cohort_memberships", report["events"][1])


if __name__ == "__main__":
    unittest.main()
