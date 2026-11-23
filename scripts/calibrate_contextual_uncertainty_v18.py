"""Calibrate uncertainty from the frozen unanimous-consensus v18 model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.compare_contextual_family_combinations_v5 import _read_replay
from src.contextual_family_combination_v18 import MODEL_VERSION as COMBINATION_VERSION
from src.contextual_probability_uncertainty_v18 import (
    MODEL_VERSION,
    calibrate_probability_uncertainty_v18,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--combination-contract", type=Path, required=True)
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--frozen-wta-contract", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    combination = json.loads(args.combination_contract.read_text(encoding="utf-8"))
    results = {}
    for universe in ("atp",):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        _augment_h2h_candidates(rows)
        results[universe] = calibrate_probability_uncertainty_v18(
            rows, universe=universe, combination_contract=combination,
        )
    if args.frozen_wta_contract is None:
        rows = _read_replay(args.replay_input_dir / "wta.jsonl.gz")
        _augment_h2h_candidates(rows)
        results["wta"] = calibrate_probability_uncertainty_v18(
            rows, universe="wta", combination_contract=combination,
        )
        frozen_wta = None
    else:
        frozen_contract = json.loads(
            args.frozen_wta_contract.read_text(encoding="utf-8"),
        )
        if frozen_contract.get("model_version") != MODEL_VERSION:
            raise ValueError("expected contextual uncertainty v18 frozen WTA contract")
        frozen_wta = frozen_contract["universes"]["wta"]

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
    if frozen_wta is not None:
        contract["universes"]["wta"] = frozen_wta
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    statuses = {key: value["status"] for key, value in results.items()}
    if frozen_wta is not None:
        statuses["wta"] = frozen_wta["status"]
    print(json.dumps(statuses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
