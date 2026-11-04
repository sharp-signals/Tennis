"""Run the hierarchy-constrained family combination in read-only mode."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.replay_recent_form_candidates import _scope, _source_health
from src import fetch_data
from src.contextual_family_combination_v2 import combine_contextual_families_v2
from src.contextual_family_replay import build_contextual_family_replay_rows
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
    frames = {
        tour: enrich_tournament_surface_contexts(frame)[0]
        for tour, frame in frames.items()
    }
    results = {}
    for tour, frame in frames.items():
        rows = build_contextual_family_replay_rows(frame, universe=tour)
        results[tour] = combine_contextual_families_v2(rows, universe=tour)
    return {
        "mode": "READ_ONLY_HIERARCHY_CONSTRAINED_COMBINATION_V2",
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
            "family_profiles": result["family_profiles"],
            "intercept": result["intercept"],
            "coefficients": result["coefficients"],
            "family_coefficients": result["family_coefficients"],
            "hierarchy": result["hierarchy"],
            "runtime_family_models": result["runtime_family_models"],
            "holdout": result["holdout"],
            "decision_gate": result["decision_gate"],
        }
    return {
        "schema_version": 1,
        "model_version": "contextual-family-combination-v2-hierarchical",
        "mode": "SHADOW_ONLY",
        "hierarchy": [
            "recent_form + structural_strength",
            "surface_conditions",
            "matchup_h2h",
            "serve_return",
        ],
        "missingness_policy": (
            "RECORDED_FOR_UNCERTAINTY_BUT_ZERO_IN_CENTRAL_ESTIMATE"
        ),
        "universes": universes,
        "market_used": False,
        "fair_odd_fitted": False,
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
