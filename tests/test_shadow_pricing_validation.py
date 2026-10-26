import tempfile
import unittest
from pathlib import Path

from src import pricing_validation, shadow_pricing_store


def row(obs="one", analyzed="2026-10-01T08:00:00+00:00", model="m1", fingerprint="f1"):
    pricing = {"available": True, "economic_estimate_available": True,
               "model_version": model, "configuration_fingerprint": fingerprint,
               "sharp_estimate_a": .60, "sharp_estimate_b": .40,
               "market_probability_a": .55, "market_probability_b": .45,
               "market_odd_a": 1.9, "market_odd_b": 2.1}
    return {"schema_version": 1, "observation_id": obs,
            "canonical_match_instance_id": "match-1", "event_key": "match-1",
            "tour": "atp", "tier": "ATP 500", "commence_time_utc": "2026-10-01T12:00:00+00:00",
            "analyzed_at_utc": analyzed, "model_version": model,
            "configuration_fingerprint": fingerprint,
            "orientation": {"a": {"player_id": "1", "market_odd": 1.9},
                            "b": {"player_id": "2", "market_odd": 2.1}},
            "pricing": pricing}


class ShadowPricingValidationTests(unittest.TestCase):
    def test_append_is_versioned_and_idempotent(self):
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            path = Path(tmp) / "shadow.jsonl"
            self.assertEqual(shadow_pricing_store.append_observations([row(), row()], path), 1)
            self.assertEqual(shadow_pricing_store.append_observations([row()], path), 0)
            second = row("two", model="m2")
            self.assertEqual(shadow_pricing_store.append_observations([second], path), 1)
            self.assertEqual(len(shadow_pricing_store.read_observations(path)), 2)

    def test_first_valid_is_strictly_pregame_per_version(self):
        late = row("late", "2026-10-01T13:00:00+00:00")
        rerun = row("rerun", "2026-10-01T09:00:00+00:00")
        selected = shadow_pricing_store.first_valid_by_match_and_version([rerun, late, row()])
        self.assertEqual([item["observation_id"] for item in selected], ["one"])

    def test_walk_forward_is_paired_and_never_auto_promotes(self):
        rows = []
        outcomes = {}
        for i in range(10):
            item = row(str(i), f"2026-10-{i+1:02d}T08:00:00+00:00")
            item["canonical_match_instance_id"] = item["event_key"] = f"match-{i}"
            item["commence_time_utc"] = f"2026-10-{i+1:02d}T12:00:00+00:00"
            rows.append(item); outcomes[f"match-{i}"] = "a" if i % 2 == 0 else "b"
        report = pricing_validation.walk_forward(rows, outcomes)
        self.assertEqual(report["holdout_size"], 3)
        self.assertFalse(report["promotion_gate"]["passed"])
        self.assertEqual(report["overall"]["model"]["n"], report["overall"]["market"]["n"])


if __name__ == "__main__":
    unittest.main()
