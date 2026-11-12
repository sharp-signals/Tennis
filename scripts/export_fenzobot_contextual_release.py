"""Export one globally named, auditable Fenzobot contextual release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


GLOBAL_RELEASE_ID = "FENZOBOT_CONTEXTUAL_2026_11"
RELEASE_SLUG = "fenzobot-contextual-2026-11"
RUNTIME_GENERATION = 10
COMBINATION_VERSION = "contextual-family-combination-v8-tier-context"
CALIBRATION_VERSION = "contextual-probability-uncertainty-v8"
ACCEPTED_HISTORICAL_RELEASES = [
    {
        "runtime_generation": 3,
        "configuration_fingerprint": (
            "05a0303b93ca8a5abc5edb3adcec235749737c54597a47333bb5bad67e2c707a"
        ),
    },
    {
        "runtime_generation": 4,
        "configuration_fingerprint": (
            "287e02c8e3d1a0b6223892b00b4fc15d2b8bd0d8afaf924f8e494fde080bde6c"
        ),
    },
    {
        "runtime_generation": 5,
        "configuration_fingerprint": (
            "41df43bc2a05673dfbe66bbf3f8afd3c6c51b60ae74a199e9615951cf59e7b1a"
        ),
    },
    {
        "runtime_generation": 6,
        "configuration_fingerprint": (
            "9f370e4364c8d44232b3f3004c9cd651c40e474ed046f877ef3ee7fc34683a52"
        ),
    },
    {
        "runtime_generation": 7,
        "configuration_fingerprint": (
            "22e57c8c9c3d4aa90e21733353e324336437af52a34764270cf2c83ffcea2151"
        ),
    },
    {
        "runtime_generation": 8,
        "configuration_fingerprint": (
            "5d6a16de3e59f2d58583655cafcb26bf27d7151ac9f19027563d81dd07d99dd8"
        ),
    },
    {
        "runtime_generation": 9,
        "configuration_fingerprint": (
            "b8ca61a90d1901897fd2ee1bddf7508d8af074a888348dcf15b6b905128621d1"
        ),
    },
]


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_release(
    combination_path: Path, calibration_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    combination = _read(combination_path)
    calibration = _read(calibration_path)
    if combination.get("model_version") != COMBINATION_VERSION:
        raise ValueError("unexpected family-combination contract")
    if calibration.get("model_version") != CALIBRATION_VERSION:
        raise ValueError("unexpected probability-calibration contract")
    for name, contract in (
        ("combination", combination), ("calibration", calibration),
    ):
        if contract.get("mode") != "SHADOW_ONLY":
            raise ValueError(f"{name} contract is not SHADOW_ONLY")
        if any(contract.get(key) is not False for key in (
            "market_used", "production_effect", "promotion_authorized",
        )):
            raise ValueError(f"{name} isolation contract failed")
    if calibration.get("combination_model_version") != COMBINATION_VERSION:
        raise ValueError("calibration does not consume the selected combination")

    source_hashes = {
        "family_combination_sha256": _sha(combination_path),
        "probability_calibration_sha256": _sha(calibration_path),
    }
    components = {
        "ranking_model": "contextual-ranking-v7.1",
        "family_combination": COMBINATION_VERSION,
        "probability_calibration": CALIBRATION_VERSION,
        "runtime_generation": RUNTIME_GENERATION,
    }
    manifest_material = {
        "global_release_id": GLOBAL_RELEASE_ID,
        "release_slug": RELEASE_SLUG,
        "components": components,
        "source_hashes": source_hashes,
    }
    fingerprint = hashlib.sha256(
        json.dumps(manifest_material, sort_keys=True).encode()
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        **manifest_material,
        "configuration_fingerprint": fingerprint,
        "mode": "PROSPECTIVE_SHADOW_ONLY",
        "status": "EXPERIMENTAL_NOT_PROMOTED",
        "market_used_for_prediction": False,
        "edge_calculated": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
        "promotion_authorized": False,
        "legacy_audit_trail_preserved": True,
        "accepted_historical_releases": ACCEPTED_HISTORICAL_RELEASES,
    }
    runtime = {
        **manifest,
        "schema_version": 3,
        "universes": {
            universe: {
                "combination": combination["universes"][universe],
                "calibration": calibration["universes"][universe],
            }
            for universe in ("atp", "wta")
        },
    }
    return manifest, runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--combination", type=Path,
        default=Path("data/models/contextual-family-combination-v8.json"),
    )
    parser.add_argument(
        "--calibration", type=Path,
        default=Path("data/models/contextual-probability-uncertainty-v8.json"),
    )
    parser.add_argument(
        "--manifest", type=Path,
        default=Path("data/models/fenzobot-contextual-2026-11-manifest.json"),
    )
    parser.add_argument(
        "--runtime", type=Path,
        default=Path("data/models/fenzobot-contextual-2026-11.json"),
    )
    args = parser.parse_args()
    manifest, runtime = build_release(args.combination, args.calibration)
    for path, value in ((args.manifest, manifest), (args.runtime, runtime)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "status": "EXPORTED",
        "global_release_id": GLOBAL_RELEASE_ID,
        "fingerprint": manifest["configuration_fingerprint"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
