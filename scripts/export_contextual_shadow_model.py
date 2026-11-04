"""Export the audited contextual calibration into a small runtime contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contract(calibration_path: Path, uncertainty_path: Path) -> dict[str, Any]:
    calibration, uncertainty = _read(calibration_path), _read(uncertainty_path)
    universes = {}
    for universe in ("atp", "wta", "challenger"):
        family_report = calibration["calibrations"][universe]
        uncertainty_report = uncertainty["results"][universe]
        combination = uncertainty_report["combination_summary"]
        if family_report.get("mode") != "FAMILY_LEVEL_CHRONOLOGICAL_CALIBRATION":
            raise ValueError(f"unexpected family calibration for {universe}")
        if combination.get("status") != "HOLDOUT_SUPPORTED":
            raise ValueError(f"unsupported family combination for {universe}")
        families = {}
        exact_models = combination.get("runtime_family_models") or {}
        if set(exact_models) != set(family_report["families"]):
            raise ValueError(f"exact runtime family models missing for {universe}")
        for name, model in exact_models.items():
            if model.get("status") != "FITTED":
                raise ValueError(f"unfitted runtime family {universe}/{name}")
            families[name] = {
                **model,
                "holdout": family_report["families"][name]["holdout"],
            }
        universes[universe] = {
            "training_source": uncertainty["source_health"][universe],
            "families": families,
            "combination": {
                "intercept": combination["intercept"],
                "coefficients": combination["coefficients"],
                "holdout": combination["holdout"],
                "primary_families": combination["uncertainty_policy"][
                    "primary_families_required_for_operational_readiness"
                ],
            },
            "uncertainty": {
                "confidence_level": uncertainty_report["confidence_level"],
                "supported_probability_range": uncertainty_report[
                    "supported_probability_range"
                ],
                "calibration_model": uncertainty_report["calibration_model"],
            },
        }
    source_hashes = {
        "family_calibration_sha256": _sha(calibration_path),
        "uncertainty_calibration_sha256": _sha(uncertainty_path),
    }
    fingerprint = hashlib.sha256(
        json.dumps({"universes": universes, **source_hashes}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "model_version": "contextual-family-shadow-v1",
        "configuration_fingerprint": fingerprint,
        "mode": "PROSPECTIVE_SHADOW_ONLY",
        "universes": universes,
        "source_hashes": source_hashes,
        "market_used": False,
        "edge_calculated": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--uncertainty", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/models/contextual-family-shadow-v1.json"),
    )
    args = parser.parse_args()
    contract = build_contract(args.calibration, args.uncertainty)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "status": "EXPORTED", "path": str(args.output),
        "fingerprint": contract["configuration_fingerprint"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
