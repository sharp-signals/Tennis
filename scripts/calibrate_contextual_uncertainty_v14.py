"""Calibrate uncertainty from the frozen consensus-hierarchy v14 model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.compare_contextual_family_combinations_v5 import _read_replay
from src.contextual_family_combination_v14 import MODEL_VERSION as COMBINATION_VERSION
from src.contextual_probability_uncertainty_v14 import (
    MODEL_VERSION,
    calibrate_probability_uncertainty_v14,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--combination-contract", type=Path, required=True)
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    combination = json.loads(args.combination_contract.read_text(encoding="utf-8"))
    results = {}
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        _augment_h2h_candidates(rows)
        results[universe] = calibrate_probability_uncertainty_v14(
            rows, universe=universe, combination_contract=combination,
        )
    contract = {
        "schema_version": 6,
        "model_version": MODEL_VERSION,
        "combination_model_version": COMBINATION_VERSION,
        "mode": "SHADOW_ONLY",
        "central_probability_policy": (
            "CHRONOLOGICALLY_SELECT_IDENTITY_OR_NONNEGATIVE_PLATT"
        ),
        "fair_odd_formula": {
            "central": "1 / calibrated_probability",
            "lower_odd": "1 / probability_upper_bound",
            "upper_odd": "1 / probability_lower_bound",
        },
        "universes": {
            universe: {key: result[key] for key in (
                "status", "central_calibrator", "confidence_level",
                "supported_probability_range", "calibration_model", "test_summary",
            )}
            for universe, result in results.items()
        },
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value["status"] for key, value in results.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
