"""Export the closed surface-family candidate as a SHADOW-only contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


CONTEXTS = ("hard_outdoor", "hard_indoor", "clay", "grass")
PROFILE = "surface_exact_career_seasons_shrunk"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("surface comparison must be a JSON object")
    return value


def _runtime_model(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "intercept": profile["intercept"],
        "coefficients": profile["coefficients"],
        "preprocessor": profile["preprocessor"],
        "selected_l1_on_validation": profile["selected_l1_on_validation"],
        "fixed_l2": profile["fixed_l2"],
        "features": profile["features"],
    }


def build_contract(report: dict[str, Any]) -> dict[str, Any]:
    comparisons = report.get("context_comparisons") or {}
    contexts: dict[str, Any] = {}
    for tour in ("atp", "wta"):
        tour_rows = comparisons.get(tour) or {}
        contexts[tour] = {}
        for context in CONTEXTS:
            comparison = tour_rows.get(context) or {}
            profile = (comparison.get("profiles") or {}).get(PROFILE)
            if not isinstance(profile, dict) or profile.get("status") != "HOLDOUT_SUPPORTED":
                raise ValueError(f"unsupported surface profile: {tour}/{context}")
            holdout = profile["holdout"]
            diagnostic_only = tour == "wta" and context == "hard_indoor"
            contexts[tour][context] = {
                "status": (
                    "DIAGNOSTIC_ONLY_INCONCLUSIVE"
                    if diagnostic_only else "READY_FOR_FAMILY_SHADOW"
                ),
                "reason": (
                    "NO_MATERIAL_GAIN_VS_INTERCEPT_ON_HOLDOUT"
                    if diagnostic_only else "POSITIVE_HOLDOUT_INFORMATION_GAIN"
                ),
                "source_rows": comparison.get("source_targets"),
                "paired_holdout_targets": comparison.get("paired_holdout_targets"),
                "holdout": holdout,
                "model": _runtime_model(profile),
                "numeric_vote_enabled": not diagnostic_only,
            }
    source_hash = hashlib.sha256(
        json.dumps(report, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "model_version": "contextual-surface-family-v2",
        "mode": "FAMILY_SHADOW_ONLY",
        "contexts": contexts,
        "source_hash_sha256": source_hash,
        "feature_profile": PROFILE,
        "shrinkage_policy": {
            "career_prior_matches": 10.0,
            "season_prior_matches": 8.0,
            "chosen_before_segment_holdout_audit": True,
        },
        "transition_policy": {
            "status": "DIAGNOSTIC_ONLY",
            "automatic_vote": False,
            "reason": "FIXED_TRANSITION_VOTE_REJECTED_IN_REPLAY",
        },
        "pace_policy": {
            "status": "DIAGNOSTIC_ONLY",
            "automatic_vote": False,
            "reason": "NO_LEAKAGE_SAFE_HISTORICAL_PACE_LEDGER",
        },
        "service_return_owned_by_separate_family": True,
        "market_used": False,
        "production_effect": False,
        "paper_eligible": False,
        "fair_odd_eligible": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = build_contract(_read(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "EXPORTED", "path": str(args.output),
        "model_version": contract["model_version"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
