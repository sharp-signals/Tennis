"""Chronological audit of governed primary agreement and H2H sample trust."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _compact,
    _history,
    _read_replay,
    _write_replay,
)
from scripts.replay_recent_form_candidates import _scope, _source_health
from src.contextual_family_calibration import _paired_probability_gain
from src.contextual_family_combination_v2 import combine_contextual_families_v2
from src.contextual_family_combination_v9 import (
    MODEL_VERSION,
    combine_contextual_families_v9,
)
from src.contextual_family_replay import _split, build_contextual_family_replay_rows
from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
)


def build_report(
    replay_input_dir: Path | None = None,
    replay_cache_dir: Path | None = None,
) -> dict:
    results, health = {}, {}
    for universe in ("atp", "wta"):
        cache = replay_input_dir / f"{universe}.jsonl.gz" if replay_input_dir else None
        if cache is not None and cache.exists():
            rows = _read_replay(cache)
            health[universe] = {
                "source": "validated_replay_cache", "rows": len(rows),
            }
        else:
            frame = _history(universe)
            health[universe] = _source_health(
                _scope(frame, "main"), universe=universe,
            )
            if not health[universe]["healthy_for_quality_replay"]:
                raise RuntimeError(f"Fonte histórica inadequada: {universe}")
            rows = build_contextual_family_replay_rows(
                enrich_tournament_surface_contexts(frame)[0],
                universe=universe, target_scope="main",
            )
        if replay_cache_dir is not None:
            _write_replay(replay_cache_dir / f"{universe}.jsonl.gz", rows)
        _augment_pooled_main_features(rows)
        baseline = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={
                "recent_form": "recent_tier_context_v8",
                "structural_strength": "contextual_v7",
                "surface_conditions": "surface_exact_tier_adjusted_v8",
            },
            model_version="contextual-family-combination-v8-tier-context",
        )
        candidate = combine_contextual_families_v9(
            rows, universe=universe, include_diagnostics=True,
        )
        baseline_diag = baseline.pop("_diagnostics")
        candidate_diag = candidate.pop("_diagnostics")
        targets = np.asarray([
            1.0 if row["target_a_win"] else 0.0
            for row in baseline_diag["holdout_rows"]
        ])
        chronology = _split(rows)
        development = chronology["train"] + chronology["validation"]
        holdout = chronology["holdout"]
        results[universe] = {
            "replay_rows": len(rows),
            "chronology": {
                "development_through": max(
                    row["event_date"] for row in development
                ),
                "holdout_from": min(row["event_date"] for row in holdout),
                "evaluation_through": max(
                    row["event_date"] for row in holdout
                ),
                "holdout_targets": len(holdout),
            },
            "baseline_v8": _compact(baseline),
            "candidate_v9": candidate,
            "paired_gain": _paired_probability_gain(
                targets,
                np.asarray(baseline_diag["holdout_probabilities"]),
                np.asarray(candidate_diag["holdout_probabilities"]),
            ),
        }
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_CHRONOLOGICAL_HIERARCHY_AUDIT",
        "source_health": health,
        "results": results,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    return {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "mode": "SHADOW_ONLY",
        "universes": {
            universe: {
                **result["candidate_v9"],
                "paired_gain_vs_v8": result["paired_gain"],
                "chronology": result["chronology"],
            }
            for universe, result in report["results"].items()
        },
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path)
    parser.add_argument("--replay-cache-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract-output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.replay_input_dir, args.replay_cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.contract_output.parent.mkdir(parents=True, exist_ok=True)
    args.contract_output.write_text(
        json.dumps(build_contract(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: result["paired_gain"]
        for universe, result in report["results"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
