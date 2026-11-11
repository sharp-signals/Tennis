"""Paired chronological comparison of ranking-v6 and return-aware v7."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from scripts.replay_recent_form_candidates import _scope, _source_health
from src import fetch_data
from src.contextual_family_calibration import _paired_probability_gain
from src.contextual_family_combination_v2 import combine_contextual_families_v2
from src.contextual_family_replay import _split, build_contextual_family_replay_rows
from src.contextual_tournament_surface_registry import enrich_tournament_surface_contexts

MODEL_VERSION = "contextual-family-combination-v4-ranking-v7"


def _compact(result: dict) -> dict:
    return {key: result[key] for key in (
        "status", "family_profiles", "family_l1_selected_inside_train",
        "meta_l1_selected_inside_validation", "intercept",
        "family_coefficients", "hierarchy", "holdout", "decision_gate",
        "runtime_family_models",
    )}


def build_report() -> dict:
    results, health = {}, {}
    for universe in ("atp", "wta"):
        frame = _scope(fetch_data.get_history(universe), "main")
        health[universe] = _source_health(frame, universe=universe)
        if not health[universe]["healthy_for_quality_replay"]:
            raise RuntimeError(f"Fonte histórica inadequada: {universe}")
        rows = build_contextual_family_replay_rows(
            enrich_tournament_surface_contexts(frame)[0], universe=universe,
        )
        chronology = _split(rows)
        baseline = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={"structural_strength": "contextual_v6"},
            model_version="contextual-family-combination-v3-ranking-v6",
        )
        candidate = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={"structural_strength": "contextual_v7"},
            model_version=MODEL_VERSION,
        )
        baseline_diag = baseline.pop("_diagnostics")
        candidate_diag = candidate.pop("_diagnostics")
        targets = np.asarray([
            1.0 if row["target_a_win"] else 0.0
            for row in baseline_diag["holdout_rows"]
        ])
        if list(targets) != [
            1.0 if row["target_a_win"] else 0.0
            for row in candidate_diag["holdout_rows"]
        ]:
            raise RuntimeError("paired holdout order mismatch")
        paired = _paired_probability_gain(
            targets,
            np.asarray(baseline_diag["holdout_probabilities"]),
            np.asarray(candidate_diag["holdout_probabilities"]),
        )
        holdout = chronology["holdout"]
        development = chronology["train"] + chronology["validation"]
        results[universe] = {
            "replay_rows_built_once": len(rows),
            "paired_holdout_targets": len(targets),
            "chronology": {
                "development_through": max(row["event_date"] for row in development),
                "holdout_from": min(row["event_date"] for row in holdout),
                "evaluation_through": max(row["event_date"] for row in holdout),
                "holdout_targets": len(holdout),
            },
            "baseline_ranking_v6": _compact(baseline),
            "candidate_ranking_v7": _compact(candidate),
            "candidate_gain_vs_v6": paired,
            "decision": (
                "RANKING_V7_SUPPORTED" if paired["status"] == "SUPPORTED"
                else "RANKING_V7_REJECTED" if paired["status"] == "REJECTED"
                else "RANKING_V7_INCONCLUSIVE"
            ),
        }
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_PAIRED_RANKING_V7_COMPARISON",
        "source_health": health, "results": results,
        "market_used": False, "fair_odd_fitted": False,
        "production_effect": False, "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    universes = {}
    for universe, result in report["results"].items():
        candidate = result["candidate_ranking_v7"]
        universes[universe] = {
            "status": result["decision"],
            "family_profiles": candidate["family_profiles"],
            "intercept": candidate["intercept"],
            "family_coefficients": candidate["family_coefficients"],
            "hierarchy": candidate["hierarchy"],
            "runtime_family_models": candidate["runtime_family_models"],
            "holdout": candidate["holdout"],
            "decision_gate": candidate["decision_gate"],
            "gain_vs_ranking_v6": result["candidate_gain_vs_v6"],
            "chronology": result["chronology"],
        }
    return {
        "schema_version": 1, "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY", "universes": universes,
        "market_used": False, "fair_odd_fitted": False,
        "production_effect": False, "promotion_authorized": False,
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
            json.dumps(build_contract(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not args.quiet:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
