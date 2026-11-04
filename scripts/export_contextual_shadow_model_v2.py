"""Export the hierarchical combination and uncertainty as runtime v2."""

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


def build_contract(
    combination_path: Path, uncertainty_path: Path,
) -> dict[str, Any]:
    combination = _read(combination_path)
    uncertainty = _read(uncertainty_path)
    if combination.get("market_used") is not False:
        raise ValueError("combination contract is not market-free")
    if uncertainty.get("market_used") is not False:
        raise ValueError("uncertainty contract is not market-free")
    universes = {}
    for universe in ("atp", "wta"):
        combined = combination["universes"][universe]
        calibrated = uncertainty["universes"][universe]
        if combined.get("status") != "HIERARCHY_SUPPORTED":
            raise ValueError(f"unsupported hierarchy: {universe}")
        if calibrated.get("status") != "UNCERTAINTY_CALIBRATED_FOR_SHADOW":
            raise ValueError(f"unsupported uncertainty: {universe}")
        universes[universe] = {
            "family_profiles": combined["family_profiles"],
            "families": combined["runtime_family_models"],
            "combination": {
                "intercept": combined["intercept"],
                "coefficients": combined["coefficients"],
                "hierarchy": combined["hierarchy"],
                "primary_families": combined["hierarchy"]["primary"],
            },
            "uncertainty": {
                "central_calibrator": calibrated["central_calibrator"],
                "confidence_level": calibrated["confidence_level"],
                "supported_probability_range": calibrated[
                    "supported_probability_range"
                ],
                "calibration_model": calibrated["calibration_model"],
            },
        }
    source_hashes = {
        "combination_sha256": _sha(combination_path),
        "uncertainty_sha256": _sha(uncertainty_path),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {"universes": universes, **source_hashes}, sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "schema_version": 2,
        "model_version": "contextual-family-shadow-v2",
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
    parser.add_argument("--combination", type=Path, required=True)
    parser.add_argument("--uncertainty", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/models/contextual-family-shadow-v2.json"),
    )
    args = parser.parse_args()
    contract = build_contract(args.combination, args.uncertainty)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "EXPORTED",
        "path": str(args.output),
        "fingerprint": contract["configuration_fingerprint"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
