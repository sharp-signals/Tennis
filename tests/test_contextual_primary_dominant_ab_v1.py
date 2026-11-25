import hashlib
import json
import unittest
from pathlib import Path

from src.contextual_primary_dominant_ab_v1 import (
    build_observation,
    collect_from_baseline_ledger,
    load_contract,
    predict_candidate,
)


def _contract():
    return {
        "experiment_id": "contextual-primary-dominant-ab-v1",
        "mode": "PROSPECTIVE_SHADOW_AB_ONLY",
        "universe": "atp",
        "prospective_start_utc": "2026-11-26T00:00:00+00:00",
        "baseline_release_id": "FENZOBOT_CONTEXTUAL_2026_11",
        "baseline_configuration_fingerprint": "baseline-current",
        "configuration_fingerprint": "experiment-one",
        "favorite_probability_ceiling": 0.625,
        "candidate": {
            "candidate_id": "candidate-one",
            "logit_bonus": 0.25889783,
        },
        "market_used": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
        "promotion_authorized": False,
    }


def _shadow(*, universe="atp", secondary_dominant=False):
    realized = [0.12, 0.10, 0.03, 0.03, 0.03]
    if secondary_dominant:
        realized = [0.04, 0.04, 0.08, 0.08, 0.08]
    keys = (
        "recent_form", "structural_strength", "surface_conditions",
        "matchup_h2h", "serve_return",
    )
    return {
        "universe": universe,
        "configuration_fingerprint": "baseline-current",
        "probability_model_a": 0.602,
        "families": [
            {
                "key": key,
                "probability_model_a": 0.54,
                "logit_contribution": value,
            }
            for key, value in zip(keys, realized)
        ],
    }


def _baseline(*, shadow=None, analyzed="2027-01-02T10:00:00+00:00"):
    return {
        "observation_id": "baseline-one",
        "canonical_match_instance_id": "match-one",
        "tour": "atp",
        "commence_time_utc": "2027-01-03T10:00:00+00:00",
        "analyzed_at_utc": analyzed,
        "players": {"a": {"name": "A"}, "b": {"name": "B"}},
        "contextual_shadow": shadow or _shadow(),
    }


class ContextualPrimaryDominantABTests(unittest.TestCase):
    def test_committed_contract_is_valid(self):
        contract = load_contract()
        self.assertEqual(contract["universe"], "atp")
        self.assertFalse(contract["production_effect"])
        claimed = contract.pop("configuration_fingerprint")
        material = json.dumps(
            contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()
        self.assertEqual(claimed, hashlib.sha256(material).hexdigest())

    def test_candidate_changes_only_the_eligible_atp_shadow_probability(self):
        result = predict_candidate(_shadow(), _contract())
        self.assertEqual(result["status"], "ELIGIBLE")
        self.assertEqual(result["baseline"]["probability_a"], 0.602)
        self.assertAlmostEqual(result["candidate"]["probability_a"], 0.6621082)
        self.assertAlmostEqual(result["candidate"]["fair_odd_a"], 1.5103)
        self.assertFalse(result["production_effect"])
        self.assertFalse(result["market_used"])

    def test_secondary_dominance_is_recorded_but_never_adjusted(self):
        result = predict_candidate(
            _shadow(secondary_dominant=True), _contract()
        )
        self.assertEqual(result["status"], "NOT_ELIGIBLE")
        self.assertIn("PRIMARY_BLOCK_NOT_DOMINANT", result["reason_codes"])
        self.assertIsNone(result["candidate"])

    def test_only_post_start_atp_baselines_enter_the_experiment(self):
        contract = _contract()
        self.assertIsNone(build_observation(
            _baseline(analyzed="2026-11-25T23:59:59+00:00"), contract
        ))
        wta = _baseline(shadow=_shadow(universe="wta"))
        wta["tour"] = "wta"
        self.assertIsNone(build_observation(wta, contract))
        self.assertTrue(
            build_observation(_baseline(), contract)["experiment"]["eligible"]
        )

    def test_collection_is_append_only_and_deduplicated(self):
        with self.subTest("temporary append-only ledger"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                baseline_path = tmp_path / "baseline.jsonl"
                output_path = tmp_path / "experiment.jsonl"
                baseline_path.write_text(
                    json.dumps(_baseline()) + "\n", encoding="utf-8"
                )
                first = collect_from_baseline_ledger(
                    _contract(),
                    baseline_path=baseline_path,
                    output_path=output_path,
                )
                second = collect_from_baseline_ledger(
                    _contract(),
                    baseline_path=baseline_path,
                    output_path=output_path,
                )
                self.assertEqual(first["observations_added"], 1)
                self.assertEqual(first["status_counts"], {"ELIGIBLE": 1})
                self.assertEqual(second["observations_added"], 0)
                self.assertEqual(
                    len(output_path.read_text(encoding="utf-8").splitlines()), 1
                )

    def test_contract_rejects_any_operational_authorization(self):
        import tempfile

        contract = _contract()
        contract["paper_eligible"] = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "model.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "isolation invariant"):
                load_contract(path)
