"""Diagnose recurring contexts inside low-probability unanimous consensus.

This audit describes historical regimes only.  It does not fit a correction,
read market data or authorize a production change.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from typing import Any, Callable

from scripts.audit_contextual_family_priority_v1 import _augment_h2h_candidates
from scripts.audit_contextual_low_consensus_rolling import _fit_fold
from scripts.audit_contextual_rolling_refit_v1 import rolling_splits
from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)


DEFAULT_MODEL = Path("data/models/fenzobot-contextual-2026-11.json")
MIN_TOTAL_SAMPLE = 20
MIN_FOLD_SAMPLE = 5


def _wilson(successes: int, sample: int) -> list[float | None]:
    if sample <= 0:
        return [None, None]
    z = 1.959963984540054
    rate = successes / sample
    denominator = 1.0 + z * z / sample
    centre = (rate + z * z / (2.0 * sample)) / denominator
    margin = z * math.sqrt(
        rate * (1.0 - rate) / sample + z * z / (4.0 * sample * sample)
    ) / denominator
    return [
        round(100.0 * (centre - margin), 2),
        round(100.0 * (centre + margin), 2),
    ]


def _segment(cases: list[dict[str, Any]]) -> dict[str, Any]:
    sample = len(cases)
    if not sample:
        return {"sample": 0}
    wins = sum(bool(case["favorite_won"]) for case in cases)
    predicted = sum(float(case["favorite_probability"]) for case in cases) / sample
    observed = wins / sample
    return {
        "sample": sample,
        "wins": wins,
        "predicted_pct": round(100.0 * predicted, 2),
        "observed_pct": round(100.0 * observed, 2),
        "gap_pp": round(100.0 * (observed - predicted), 2),
        "observed_wilson_95_pct": _wilson(wins, sample),
    }


def _rank_band(case: dict[str, Any]) -> str:
    rank = case.get("favorite_rank")
    if rank is None:
        return "unknown"
    value = float(rank)
    if value <= 10:
        return "rank_1_10"
    if value <= 20:
        return "rank_11_20"
    if value <= 50:
        return "rank_21_50"
    if value <= 100:
        return "rank_51_100"
    return "rank_101_plus"


def _rank_relation(case: dict[str, Any]) -> str:
    favorite = case.get("favorite_rank")
    opponent = case.get("opponent_rank")
    if favorite is None or opponent is None:
        return "unknown"
    gap = float(opponent) - float(favorite)
    if gap < 0:
        return "model_favorite_worse_rank"
    if gap < 10:
        return "better_by_0_9"
    if gap < 25:
        return "better_by_10_24"
    if gap < 50:
        return "better_by_25_49"
    return "better_by_50_plus"


def _h2h_band(case: dict[str, Any]) -> str:
    sample = int(case.get("h2h_sample") or 0)
    if sample == 0:
        return "h2h_0"
    if sample <= 2:
        return "h2h_1_2"
    if sample <= 4:
        return "h2h_3_4"
    return "h2h_5_plus"


def _primary_balance(case: dict[str, Any]) -> str:
    if float(case["primary_logit_contribution"]) > float(
        case["secondary_logit_contribution"]
    ):
        return "primary_above_secondary"
    return "primary_not_above_secondary"


SEGMENTERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "primary_intensity": lambda case: str(case["strongest_primary_intensity"]),
    "surface_context": lambda case: str(case["surface_context"]),
    "tournament_tier": lambda case: str(case["target_tier"]),
    "favorite_rank_band": _rank_band,
    "rank_relation": _rank_relation,
    "h2h_sample": _h2h_band,
    "primary_balance": _primary_balance,
    "primary_intensity_x_tier": lambda case: (
        f"{case['strongest_primary_intensity']} | {case['target_tier']}"
    ),
    "primary_intensity_x_surface": lambda case: (
        f"{case['strongest_primary_intensity']} | {case['surface_context']}"
    ),
    "primary_intensity_x_rank_relation": lambda case: (
        f"{case['strongest_primary_intensity']} | {_rank_relation(case)}"
    ),
}


def _context_verdict(
    aggregate: dict[str, Any], folds: dict[str, dict[str, Any]],
) -> str:
    if int(aggregate.get("sample") or 0) < MIN_TOTAL_SAMPLE:
        return "INSUFFICIENT_TOTAL_SAMPLE"
    eligible = [
        value for value in folds.values()
        if int(value.get("sample") or 0) >= MIN_FOLD_SAMPLE
    ]
    if len(eligible) < 2:
        return "INSUFFICIENT_FOLD_REPLICATION"
    positive = sum(float(value["gap_pp"]) > 0.0 for value in eligible)
    material_negative = any(float(value["gap_pp"]) < -5.0 for value in eligible)
    interval = aggregate["observed_wilson_95_pct"]
    statistically_low = float(aggregate["predicted_pct"]) < float(interval[0])
    if positive >= 2 and not material_negative and statistically_low:
        return "REPEATED_UNDERCONFIDENCE_SIGNAL"
    if positive >= 2 and not material_negative:
        return "DIRECTIONALLY_REPEATED_NOT_CERTIFIED"
    return "UNSTABLE_OR_CONTRADICTORY"


def _grouping(
    cases: list[dict[str, Any]], classifier: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        groups[classifier(case)].append(case)
    result = {}
    for name, values in sorted(groups.items()):
        fold_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in values:
            fold_groups[str(case["fold"])].append(case)
        folds = {
            fold: _segment(fold_values)
            for fold, fold_values in sorted(fold_groups.items())
        }
        aggregate = _segment(values)
        result[name] = {
            "aggregate": aggregate,
            "folds": folds,
            "verdict": _context_verdict(aggregate, folds),
        }
    return result


def audit_universe(
    rows: list[dict[str, Any]], *, universe: str, release: dict[str, Any],
) -> dict[str, Any]:
    _augment_pooled_main_features(rows)
    _augment_h2h_candidates(rows)
    combination = release["universes"][universe]["combination"]
    fitted = [
        _fit_fold(fold, universe=universe, combination=combination)
        for fold in rolling_splits(rows)
    ]
    cases = [
        case for fold in fitted for case in fold["_case_records"]
    ]
    groupings = {
        name: _grouping(cases, classifier)
        for name, classifier in SEGMENTERS.items()
    }
    actionable = []
    for grouping, segments in groupings.items():
        for segment, result in segments.items():
            if result["verdict"] == "REPEATED_UNDERCONFIDENCE_SIGNAL":
                actionable.append({
                    "grouping": grouping,
                    "segment": segment,
                    **result,
                })
    actionable.sort(
        key=lambda item: (
            -float(item["aggregate"]["gap_pp"]),
            -int(item["aggregate"]["sample"]),
        )
    )
    return {
        "source_rows": len(rows),
        "low_unanimous_cases": len(cases),
        "overall": _segment(cases),
        "groupings": groupings,
        "repeated_underconfidence_contexts": actionable,
        "individual_cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.model.read_text(encoding="utf-8"))
    audit = {
        "schema_version": 1,
        "mode": "READ_ONLY_LOW_UNANIMOUS_REGIME_DIAGNOSTIC",
        "model_version": release["global_release_id"],
        "configuration_fingerprint": release["configuration_fingerprint"],
        "market_used": False,
        "model_refit_for_correction": False,
        "production_effect": False,
        "promotion_authorized": False,
        "thresholds": {
            "minimum_total_sample": MIN_TOTAL_SAMPLE,
            "minimum_fold_sample": MIN_FOLD_SAMPLE,
            "minimum_replicated_folds": 2,
        },
        "universes": {
            universe: audit_universe(
                _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz"),
                universe=universe, release=release,
            )
            for universe in ("atp", "wta")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: {
            "cases": payload["low_unanimous_cases"],
            "repeated_contexts": len(
                payload["repeated_underconfidence_contexts"]
            ),
        }
        for universe, payload in audit["universes"].items()
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
