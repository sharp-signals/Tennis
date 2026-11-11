"""Calibrate v4 uncertainty from the frozen ranking-v7 combination."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.replay_recent_form_candidates import _scope, _source_health
from src import fetch_data
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_probability_uncertainty_v4 import calibrate_probability_uncertainty_v4
from src.contextual_tournament_surface_registry import enrich_tournament_surface_contexts

DEFAULT_COMBINATION = Path("data/models/contextual-family-combination-v4.json")


def build_report(combination_contract: dict) -> dict:
    results, health = {}, {}
    for universe in ("atp", "wta"):
        frame = _scope(fetch_data.get_history(universe), "main")
        health[universe] = _source_health(frame, universe=universe)
        if not health[universe]["healthy_for_quality_replay"]:
            raise RuntimeError(f"Fonte histórica inadequada: {universe}")
        rows = build_contextual_family_replay_rows(
            enrich_tournament_surface_contexts(frame)[0], universe=universe,
        )
        results[universe] = calibrate_probability_uncertainty_v4(
            rows, universe=universe, combination_contract=combination_contract,
        )
    return {
        "mode": "READ_ONLY_CONTEXTUAL_UNCERTAINTY_V4_FROZEN_COMBINATION",
        "source_health": health, "results": results,
        "market_used": False, "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    universes = {}
    for universe, result in report["results"].items():
        universes[universe] = {key: result[key] for key in (
            "status", "central_calibrator", "confidence_level",
            "supported_probability_range", "calibration_model", "test_summary",
        )}
    return {
        "schema_version": 4,
        "model_version": "contextual-probability-uncertainty-v4",
        "combination_model_version": "contextual-family-combination-v4-ranking-v7",
        "mode": "SHADOW_ONLY",
        "central_probability_policy": "CHRONOLOGICALLY_SELECT_IDENTITY_OR_NONNEGATIVE_PLATT",
        "fair_odd_formula": {
            "central": "1 / calibrated_probability",
            "lower_odd": "1 / probability_upper_bound",
            "upper_odd": "1 / probability_lower_bound",
        },
        "universes": universes, "market_used": False,
        "production_effect": False, "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--combination-contract", type=Path, default=DEFAULT_COMBINATION)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract-output", type=Path)
    parser.add_argument("--provider-cache", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    contract = json.loads(args.combination_contract.read_text(encoding="utf-8"))
    report = build_report(contract)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.contract_output:
        args.contract_output.parent.mkdir(parents=True, exist_ok=True)
        args.contract_output.write_text(
            json.dumps(build_contract(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not args.quiet:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
