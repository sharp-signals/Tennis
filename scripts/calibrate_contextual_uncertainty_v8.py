"""Calibrate uncertainty from the frozen competition-context v8 model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.compare_contextual_family_combinations_v5 import _read_replay
from src.contextual_probability_uncertainty_v8 import (
    calibrate_probability_uncertainty_v8,
)


MODEL_VERSION = "contextual-probability-uncertainty-v8"
COMBINATION_VERSION = "contextual-family-combination-v8-tier-context"


def build_report(combination: dict, replay_input_dir: Path) -> dict:
    results = {}
    for universe in ("atp", "wta"):
        rows = _read_replay(replay_input_dir / f"{universe}.jsonl.gz")
        results[universe] = calibrate_probability_uncertainty_v8(
            rows, universe=universe, combination_contract=combination,
        )
    return {
        "schema_version": 1, "results": results,
        "market_used": False, "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    return {
        "schema_version": 5, "model_version": MODEL_VERSION,
        "combination_model_version": COMBINATION_VERSION,
        "mode": "SHADOW_ONLY",
        "central_probability_policy": "CHRONOLOGICALLY_SELECT_IDENTITY_OR_NONNEGATIVE_PLATT",
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
            for universe, result in report["results"].items()
        },
        "market_used": False, "production_effect": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--combination-contract", type=Path, required=True)
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract-output", type=Path)
    args = parser.parse_args()
    combination = json.loads(args.combination_contract.read_text(encoding="utf-8"))
    report = build_report(combination, args.replay_input_dir)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.contract_output:
        args.contract_output.write_text(json.dumps(build_contract(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({u: r["status"] for u, r in report["results"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
