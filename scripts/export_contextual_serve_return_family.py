"""Export the closed SHADOW contract for the secondary serve/return family."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SELECTED = {
    "atp": "serve_return_points_recent_deviation_v1",
    "wta": "serve_return_surface_points_shrunk_v1",
}


def build_contract(comparison: dict) -> dict:
    universes = comparison.get("universes", {})

    def incremental_summary(tour: str, data: dict) -> dict:
        incremental = data.get("incremental_after_primary_families", {})
        base = incremental.get("base", {})
        selected = (
            incremental.get("primary_plus_serve_return", {})
            if tour == "atp"
            else incremental.get("primary_plus_surface_serve_return", {})
        )
        base_validation = base.get("validation", {}).get("model", {}).get(
            "validation_log_loss",
        )
        selected_validation = selected.get("validation", {}).get(
            "model", {},
        ).get("validation_log_loss")
        base_holdout = base.get("holdout", {}).get("model", {}).get("log_loss")
        selected_holdout = selected.get("holdout", {}).get("model", {}).get(
            "log_loss",
        )
        return {
            "status": (
                "HOLDOUT_SUPPORTED"
                if all(value is not None for value in (
                    base_validation, selected_validation,
                    base_holdout, selected_holdout,
                ))
                and selected_validation < base_validation
                and selected_holdout < base_holdout
                else "NOT_SUPPORTED"
            ),
            "validation_log_loss_improvement": (
                round(base_validation - selected_validation, 6)
                if base_validation is not None and selected_validation is not None
                else None
            ),
            "holdout_log_loss_improvement": (
                round(base_holdout - selected_holdout, 6)
                if base_holdout is not None and selected_holdout is not None
                else None
            ),
        }

    return {
        "schema_version": 1,
        "model_id": "contextual-serve-return-family-v1",
        "status": "FAMILY_SHADOW_ONLY",
        "role": "SECONDARY_BOUNDED_MODIFIER",
        "selected_profiles": {
            tour: {
                "profile": profile,
                "isolated_calibration": data.get("candidates", {}).get(profile),
                "incremental_after_primary_families": incremental_summary(
                    tour, data,
                ),
            }
            for tour, data in universes.items()
            for profile in [SELECTED[tour]]
        },
        "feature_contract": {
            "baseline": [
                "service points won on current surface, sample-shrunk",
                "return points won on current surface, sample-shrunk",
            ],
            "atp_recent_modifier": [
                "90-day service deviation from surface baseline",
                "90-day return deviation from surface baseline",
            ],
            "wta_recent_modifier": "diagnostic only; not holdout-supported",
            "hold_and_break": "diagnostic only; downstream alternative, never summed",
        },
        "sample_priors": {
            "surface_points": 1_000,
            "recent_points": 500,
            "surface_games_diagnostic": 100,
        },
        "governance": {
            "below_recent_form_and_structural_strength": True,
            "career_is_baseline_recent_is_deviation": True,
            "points_and_hold_break_are_not_summed": True,
            "standalone_candidate_prohibited": True,
            "may_override_primary_families": False,
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
