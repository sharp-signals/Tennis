"""Export the selected H2H family shadow contract from replay evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_contract(comparison: dict) -> dict:
    universes = comparison.get("universes", {})
    return {
        "schema_version": 1,
        "model_id": "contextual-h2h-family-v1",
        "status": "FAMILY_SHADOW_ONLY",
        "equation_version": "contextual-h2h-global-shrunk-v1",
        "selected_structure": "global H2H balance with two-match symmetric shrinkage",
        "selection": {
            tour: {
                "validation_winner": data.get("selected_on_validation"),
                "deployed_family_candidate": "h2h_global_shrunk_v1",
                "holdout_status": data.get("candidates", {}).get(
                    "h2h_global_shrunk_v1", {},
                ).get("status"),
                "holdout": data.get("candidates", {}).get(
                    "h2h_global_shrunk_v1", {},
                ).get("holdout"),
            }
            for tour, data in universes.items()
        },
        "decision_rationale": [
            "global H2H is supported on ATP and WTA holdout",
            "context modifiers add negligible and circuit-inconsistent improvement",
            "same matches cannot become global plus surface votes",
            "recency and context remain visible diagnostics",
            "one prior match remains low evidence and the family stays bounded",
        ],
        "states": {
            "OBSERVED_NONE": "neutral coverage with zero impact",
            "AVAILABLE": "shrunk global balance candidate",
            "SOURCE_OR_IDENTITY_UNAVAILABLE": "missing, never neutral or opponent vote",
        },
        "guards": {
            "market_used": False,
            "production_effect": False,
            "overall_probability_fitted": False,
            "fair_odd_fitted": False,
            "paper_allowed": False,
            "promotion_authorized": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    contract = build_contract(comparison)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
