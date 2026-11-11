"""Calibrate v7 uncertainty from the frozen pooled tier-aware combination."""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _history,
)
from scripts.replay_recent_form_candidates import _scope, _source_health
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_probability_uncertainty_v7 import calibrate_probability_uncertainty_v7
from src.contextual_tournament_surface_registry import enrich_tournament_surface_contexts


DEFAULT_COMBINATION = Path("data/models/contextual-family-combination-v7.json")


def _read_replay(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_report(
    combination_contract: dict, replay_cache_dir: Path | None = None,
) -> dict:
    results, health = {}, {}
    for universe in ("atp", "wta"):
        cache_path = (
            replay_cache_dir / f"{universe}.jsonl.gz"
            if replay_cache_dir is not None else None
        )
        if cache_path is not None and cache_path.exists():
            rows = _read_replay(cache_path)
            _augment_pooled_main_features(rows)
            health[universe] = {
                "healthy_for_quality_replay": True,
                "source": "frozen_replay_cache_from_tier_comparison",
                "rows": len(rows),
            }
        else:
            frame = _history(universe)
            primary = _scope(frame, "main")
            health[universe] = _source_health(primary, universe=universe)
            if not health[universe]["healthy_for_quality_replay"]:
                raise RuntimeError(f"Fonte histórica inadequada: {universe}")
            rows = build_contextual_family_replay_rows(
                enrich_tournament_surface_contexts(frame)[0],
                universe=universe,
                target_scope="main",
            )
        results[universe] = calibrate_probability_uncertainty_v7(
            rows, universe=universe,
            combination_contract=combination_contract,
        )
    return {
        "mode": "READ_ONLY_CONTEXTUAL_UNCERTAINTY_V7_FROZEN_COMBINATION",
        "source_health": health,
        "results": results,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def build_contract(report: dict) -> dict:
    universes = {
        universe: {key: result[key] for key in (
            "status", "central_calibrator", "confidence_level",
            "supported_probability_range", "calibration_model", "test_summary",
        )}
        for universe, result in report["results"].items()
    }
    return {
        "schema_version": 5,
        "model_version": "contextual-probability-uncertainty-v7",
        "combination_model_version": "contextual-family-combination-v7-tier-pooled",
        "mode": "SHADOW_ONLY",
        "central_probability_policy": "CHRONOLOGICALLY_SELECT_IDENTITY_OR_NONNEGATIVE_PLATT",
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
    parser.add_argument("--combination-contract", type=Path, default=DEFAULT_COMBINATION)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract-output", type=Path)
    parser.add_argument("--provider-cache", type=Path)
    parser.add_argument("--replay-cache-dir", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    combination = json.loads(args.combination_contract.read_text(encoding="utf-8"))
    report = build_report(combination, args.replay_cache_dir)
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
