"""Compare the frozen hierarchical stack with the ranking-v6 candidate.

Replay rows are built once per universe and reused by both candidates.  This
keeps the comparison paired, avoids duplicate source work and has no production
effect.
"""

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
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
)


def _compact(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "status", "family_profiles", "family_l1_selected_inside_train",
            "meta_l1_selected_inside_validation", "intercept",
            "family_coefficients", "hierarchy", "holdout", "decision_gate",
            "runtime_family_models",
        )
    }


def build_report() -> dict:
    results = {}
    source_health = {}
    for universe in ("atp", "wta"):
        frame = _scope(fetch_data.get_history(universe), "main")
        source_health[universe] = _source_health(frame, universe=universe)
        if not source_health[universe]["healthy_for_quality_replay"]:
            raise RuntimeError(f"Fonte histórica inadequada: {universe}")
        frame = enrich_tournament_surface_contexts(frame)[0]
        rows = build_contextual_family_replay_rows(frame, universe=universe)
        baseline = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
        )
        candidate = combine_contextual_families_v2(
            rows,
            universe=universe,
            include_diagnostics=True,
            family_profile_overrides={"structural_strength": "contextual_v6"},
            model_version="contextual-family-combination-v3-ranking-v6",
        )
        baseline_diag = baseline.pop("_diagnostics")
        candidate_diag = candidate.pop("_diagnostics")
        baseline_targets = [
            1.0 if row["target_a_win"] else 0.0
            for row in baseline_diag["holdout_rows"]
        ]
        candidate_targets = [
            1.0 if row["target_a_win"] else 0.0
            for row in candidate_diag["holdout_rows"]
        ]
        if baseline_targets != candidate_targets:
            raise RuntimeError("paired holdout order mismatch")
        targets = np.asarray(baseline_targets)
        paired = _paired_probability_gain(
            targets,
            np.asarray(baseline_diag["holdout_probabilities"]),
            np.asarray(candidate_diag["holdout_probabilities"]),
        )
        results[universe] = {
            "replay_rows_built_once": len(rows),
            "paired_holdout_targets": len(targets),
            "baseline_legacy_ranking": _compact(baseline),
            "candidate_ranking_v6": _compact(candidate),
            "candidate_gain_vs_baseline": paired,
            "decision": (
                "RANKING_V6_SUPPORTED"
                if paired["status"] == "SUPPORTED"
                else "RANKING_V6_REJECTED"
                if paired["status"] == "REJECTED"
                else "RANKING_V6_INCONCLUSIVE"
            ),
        }
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_PAIRED_FINAL_FAMILY_COMBINATION_COMPARISON",
        "source_health": source_health,
        "results": results,
        "market_used": False,
        "fair_odd_fitted": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    universes = {}
    for universe, result in report["results"].items():
        candidate = result["candidate_ranking_v6"]
        universes[universe] = {
            "status": result["decision"],
            "family_profiles": candidate["family_profiles"],
            "intercept": candidate["intercept"],
            "family_coefficients": candidate["family_coefficients"],
            "hierarchy": candidate["hierarchy"],
            "runtime_family_models": candidate["runtime_family_models"],
            "holdout": candidate["holdout"],
            "decision_gate": candidate["decision_gate"],
            "gain_vs_legacy_ranking_combination": result[
                "candidate_gain_vs_baseline"
            ],
        }
    return {
        "schema_version": 1,
        "model_version": "contextual-family-combination-v3-ranking-v6",
        "mode": "SHADOW_ONLY",
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
            json.dumps(build_contract(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if not args.quiet:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
