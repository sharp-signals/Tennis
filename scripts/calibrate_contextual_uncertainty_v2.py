"""Run v2 market-free probability and uncertainty calibration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.replay_recent_form_candidates import _scope, _source_health
from src import fetch_data
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_probability_uncertainty_v2 import (
    calibrate_probability_uncertainty_v2,
)
from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
)


def build_report() -> dict:
    frames = {
        "atp": _scope(fetch_data.get_history("atp"), "main"),
        "wta": _scope(fetch_data.get_history("wta"), "main"),
    }
    health = {
        tour: _source_health(frame, universe=tour)
        for tour, frame in frames.items()
    }
    unhealthy = [
        tour for tour, state in health.items()
        if not state["healthy_for_quality_replay"]
    ]
    if unhealthy:
        raise RuntimeError("Fonte histórica inadequada: " + ", ".join(unhealthy))
    results = {}
    for tour, frame in frames.items():
        enriched = enrich_tournament_surface_contexts(frame)[0]
        rows = build_contextual_family_replay_rows(enriched, universe=tour)
        results[tour] = calibrate_probability_uncertainty_v2(
            rows, universe=tour,
        )
    return {
        "mode": "READ_ONLY_CONTEXTUAL_UNCERTAINTY_V2",
        "source_health": health,
        "results": results,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    universes = {}
    for tour, result in report["results"].items():
        universes[tour] = {
            "status": result["status"],
            "central_calibrator": result["central_calibrator"],
            "confidence_level": result["confidence_level"],
            "supported_probability_range": result[
                "supported_probability_range"
            ],
            "calibration_model": result["calibration_model"],
            "test_summary": result["test_summary"],
        }
    return {
        "schema_version": 2,
        "model_version": "contextual-probability-uncertainty-v2",
        "combination_model_version": (
            "contextual-family-combination-v2-hierarchical"
        ),
        "mode": "SHADOW_ONLY",
        "central_probability_policy": (
            "CHRONOLOGICALLY_SELECT_IDENTITY_OR_NONNEGATIVE_PLATT"
        ),
        "missingness_policy": (
            "ZERO_CENTRAL_VOTE_AND_EMPIRICAL_INTERVAL_UNION"
        ),
        "fair_odd_formula": {
            "central": "1 / calibrated_probability",
            "lower_odd": "1 / probability_upper_bound",
            "upper_odd": "1 / probability_lower_bound",
        },
        "universes": universes,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract-output", type=Path)
    parser.add_argument("--provider-cache", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    report = build_report()
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.contract_output:
        args.contract_output.parent.mkdir(parents=True, exist_ok=True)
        args.contract_output.write_text(
            json.dumps(build_contract(report), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
    if not args.quiet:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
