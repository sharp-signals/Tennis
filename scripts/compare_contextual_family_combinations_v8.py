"""Chronological comparison of v7 with competition-context aware v8."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features, _compact, _history, _read_replay,
    _write_replay,
)
from scripts.replay_recent_form_candidates import _scope, _source_health
from src.contextual_family_calibration import _paired_probability_gain
from src.contextual_family_combination_v2 import combine_contextual_families_v2
from src.contextual_family_replay import _split, build_contextual_family_replay_rows
from src.contextual_tournament_surface_registry import enrich_tournament_surface_contexts


MODEL_VERSION = "contextual-family-combination-v8-tier-context"


def build_report(replay_input_dir: Path | None = None) -> dict:
    results, health = {}, {}
    for universe in ("atp", "wta"):
        cache = replay_input_dir / f"{universe}.jsonl.gz" if replay_input_dir else None
        if cache is not None and cache.exists():
            rows = _read_replay(cache)
            health[universe] = {"source": "validated_replay_cache", "rows": len(rows)}
        else:
            frame = _history(universe)
            health[universe] = _source_health(_scope(frame, "main"), universe=universe)
            if not health[universe]["healthy_for_quality_replay"]:
                raise RuntimeError(f"Fonte histórica inadequada: {universe}")
            rows = build_contextual_family_replay_rows(
                enrich_tournament_surface_contexts(frame)[0],
                universe=universe, target_scope="main",
            )
        _augment_pooled_main_features(rows)
        baseline = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={
                "recent_form": "recent_tier_pooled_v7",
                "structural_strength": "contextual_v7",
                "surface_conditions": "surface_exact_career_seasons_shrunk",
            }, model_version="contextual-family-combination-v7-tier-pooled",
        )
        candidate = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={
                "recent_form": "recent_tier_context_v8",
                "structural_strength": "contextual_v7",
                "surface_conditions": "surface_exact_tier_adjusted_v8",
            }, model_version=MODEL_VERSION,
        )
        base_diag = baseline.pop("_diagnostics")
        candidate_diag = candidate.pop("_diagnostics")
        targets = np.asarray([
            1.0 if row["target_a_win"] else 0.0
            for row in base_diag["holdout_rows"]
        ])
        chronology = _split(rows)
        development = chronology["train"] + chronology["validation"]
        holdout = chronology["holdout"]
        results[universe] = {
            "baseline": _compact(baseline),
            "candidate": _compact(candidate),
            "gain": _paired_probability_gain(
                targets,
                np.asarray(base_diag["holdout_probabilities"]),
                np.asarray(candidate_diag["holdout_probabilities"]),
            ),
            "chronology": {
                "development_through": max(row["event_date"] for row in development),
                "holdout_from": min(row["event_date"] for row in holdout),
                "evaluation_through": max(row["event_date"] for row in holdout),
                "holdout_targets": len(holdout),
            },
        }
    return {"schema_version": 1, "results": results, "source_health": health,
            "market_used": False, "production_effect": False,
            "promotion_authorized": False}


def build_contract(report: dict) -> dict:
    return {
        "schema_version": 1, "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "universes": {
            universe: {
                **result["candidate"],
                "gain_vs_v7": result["gain"],
                "chronology": result["chronology"],
            } for universe, result in report["results"].items()
        },
        "market_used": False, "fair_odd_fitted": False,
        "production_effect": False, "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract-output", type=Path)
    args = parser.parse_args()
    report = build_report(args.replay_input_dir)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.contract_output:
        args.contract_output.write_text(json.dumps(build_contract(report), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({u: r["gain"] for u, r in report["results"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
