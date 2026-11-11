"""Chronological comparison of raw and pooled tier-aware recent form."""

from __future__ import annotations

import argparse
import gzip
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


MODEL_VERSION = "contextual-family-combination-v7-tier-pooled"


def _compact(result: dict) -> dict:
    return {key: result[key] for key in (
        "status", "family_profiles", "family_l1_selected_inside_train",
        "meta_l1_selected_inside_validation", "intercept",
        "family_coefficients", "hierarchy", "holdout", "decision_gate",
        "runtime_family_models",
    )}


def _history(universe: str):
    if universe == "atp":
        return fetch_data.get_history("atp", tier="Challenger 125")
    return fetch_data.get_history(universe)


def _write_replay(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_replay(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _unshrink(value: float, sample: int) -> float:
    if sample <= 0:
        return 0.0
    return float(value) / min(1.0, sample / 4.0)


def _augment_pooled_main_features(rows: list[dict]) -> None:
    """Recover the exact pooled-main inputs from the persisted bucket audit.

    This avoids rebuilding the 10-year chronological replay merely to test a
    more parsimonious equation. Runtime rows calculate the same values directly.
    """
    for row in rows:
        audit = row.get("candidate_equation_audit", {}).get(
            "recent_form_tier_reliable_v5", {},
        )
        buckets = audit.get("buckets", {})
        features = row.setdefault("features", {})
        for label in ("result", "competitiveness"):
            sides = {}
            for side in ("a", "b"):
                total, weighted = 0, 0.0
                for bucket in ("peer_higher", "lower_main"):
                    metric = (buckets.get(bucket) or {}).get(label) or {}
                    sample = int(metric.get(f"{side}_sample") or 0)
                    if sample:
                        raw = _unshrink(float(metric.get(f"{side}_shrunk") or 0.0), sample)
                        total += sample
                        weighted += raw * sample
                sides[side] = (weighted / total if total else 0.0, total)
            raw_margin = sides["a"][0] - sides["b"][0]
            reliability = max(
                min(1.0, sides["a"][1] / 2.0),
                min(1.0, sides["b"][1] / 2.0),
            )
            available = sides["a"][1] > 0 or sides["b"][1] > 0
            features[f"contextual_recent_{label}_main_v7"] = (
                raw_margin * reliability if available else None
            )


def build_report(
    replay_cache_dir: Path | None = None,
    replay_input_dir: Path | None = None,
) -> dict:
    results, health = {}, {}
    for universe in ("atp", "wta"):
        cached = replay_input_dir / f"{universe}.jsonl.gz" if replay_input_dir else None
        if cached is not None and cached.exists():
            rows = _read_replay(cached)
            _augment_pooled_main_features(rows)
            health[universe] = {"source": "validated_replay_cache", "healthy_for_quality_replay": True}
        else:
            frame = _history(universe)
            primary = _scope(frame, "main")
            health[universe] = _source_health(primary, universe=universe)
            if not health[universe]["healthy_for_quality_replay"]:
                raise RuntimeError(f"Fonte histórica inadequada: {universe}")
            enriched = enrich_tournament_surface_contexts(frame)[0]
            rows = build_contextual_family_replay_rows(
                enriched, universe=universe, target_scope="main",
            )
        if replay_cache_dir is not None:
            _write_replay(replay_cache_dir / f"{universe}.jsonl.gz", rows)
        chronology = _split(rows)
        baseline = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={
                "recent_form": "recent_v2",
                "structural_strength": "contextual_v7",
            },
            model_version="contextual-family-combination-v5-raw-tier-baseline",
        )
        candidate = combine_contextual_families_v2(
            rows, universe=universe, include_diagnostics=True,
            family_profile_overrides={
                "recent_form": "recent_tier_pooled_v7",
                "structural_strength": "contextual_v7",
            },
            model_version=MODEL_VERSION,
        )
        baseline_diag = baseline.pop("_diagnostics")
        candidate_diag = candidate.pop("_diagnostics")
        targets = np.asarray([
            1.0 if row["target_a_win"] else 0.0
            for row in baseline_diag["holdout_rows"]
        ])
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
            "baseline_raw_recent": _compact(baseline),
            "candidate_tier_reliable": _compact(candidate),
            "candidate_gain_vs_raw_recent": paired,
            "decision": (
                "TIER_RELIABLE_SUPPORTED" if paired["status"] == "SUPPORTED"
                else "TIER_RELIABLE_REJECTED" if paired["status"] == "REJECTED"
                else "TIER_RELIABLE_INCONCLUSIVE"
            ),
        }
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_PAIRED_TIER_POOLED_COMPARISON_V7",
        "source_health": health,
        "results": results,
        "market_used": False,
        "fair_odd_fitted": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    universes = {}
    for universe, result in report["results"].items():
        candidate = result["candidate_tier_reliable"]
        universes[universe] = {
            "status": result["decision"],
            "family_profiles": candidate["family_profiles"],
            "intercept": candidate["intercept"],
            "family_coefficients": candidate["family_coefficients"],
            "hierarchy": candidate["hierarchy"],
            "runtime_family_models": candidate["runtime_family_models"],
            "holdout": candidate["holdout"],
            "decision_gate": candidate["decision_gate"],
            "gain_vs_raw_recent": result["candidate_gain_vs_raw_recent"],
            "chronology": result["chronology"],
        }
    return {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
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
    parser.add_argument("--replay-cache-dir", type=Path)
    parser.add_argument("--replay-input-dir", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    report = build_report(args.replay_cache_dir, args.replay_input_dir)
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
