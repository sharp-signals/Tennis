"""Chronological, market-free audit of recent win credit construction.

Compares the current category-only credit against two audit-only candidates:
category x round progress, and one joint category x round x opponent-quality
term.  The joint term replaces the standalone opponent-quality feature, so
the same evidence is never counted twice.  Production contracts are read but
never rewritten.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _read_replay,
)
from src.contextual_family_calibration import (
    _metrics,
    _paired_probability_gain,
    _runtime_model,
    calibrate_family,
    predict_family_equation,
)
from src.contextual_family_combination_v18 import (
    predict_contextual_combination_v18,
)
from src.contextual_family_replay import _split


SCHEMA_VERSION = 1
BASELINE_PROFILE = "recent_tier_context_v8"
ROUND_PROFILE = "recent_tier_round_audit_v1"
JOINT_PROFILE = "recent_tier_round_opponent_joint_audit_v1"
ROUND_FEATURE = "contextual_recent_tier_round_credit_audit_v1"
JOINT_FEATURE = "contextual_recent_tier_round_opponent_credit_audit_v1"
MIN_RECENT_MATCHES = 4

_ROUND_PROGRESS = {
    "r128": 1.0 / 7.0,
    "r64": 2.0 / 7.0,
    "r32": 3.0 / 7.0,
    "r16": 4.0 / 7.0,
    "qf": 5.0 / 7.0,
    "sf": 6.0 / 7.0,
    "f": 1.0,
    # A round-robin win is one of the three steps available in the group.
    "rr": 1.0 / 3.0,
}


def round_progress(value: Any) -> float | None:
    """Return transparent progress towards the title for a known round."""
    text = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    aliases = {
        "roundof128": "r128", "roundof64": "r64", "roundof32": "r32",
        "roundof16": "r16", "quarterfinal": "qf",
        "quarterfinals": "qf", "semifinal": "sf", "semifinals": "sf",
        "final": "f", "roundrobin": "rr",
    }
    return _ROUND_PROGRESS.get(aliases.get(text, text))


def opponent_quality(rank: Any) -> float | None:
    """Continuous bounded strength: no hand-picked ranking bands or ceiling."""
    try:
        value = float(rank)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return 1.0 / (1.0 + math.log(value))


def _side_credit(
    ledger: list[dict[str, Any]], *, include_opponent: bool,
) -> tuple[float | None, int, int]:
    numerator = 0.0
    denominator = 0.0
    usable = 0
    omitted_wins = 0
    for item in ledger:
        weight = float(item.get("recency_weight") or 0.0)
        if not item.get("won"):
            denominator += weight
            usable += 1
            continue
        progress = round_progress(item.get("round"))
        quality = opponent_quality(item.get("opponent_rank")) if include_opponent else 1.0
        if progress is None or quality is None:
            omitted_wins += 1
            continue
        category = float(item.get("category_points") or 0.0) / 2000.0
        numerator += weight * category * progress * quality
        denominator += weight
        usable += 1
    return (
        numerator / denominator if denominator > 0.0 else None,
        usable,
        omitted_wins,
    )


def augment_candidate_features(rows: list[dict[str, Any]]) -> dict[str, int]:
    coverage = {
        "rows": len(rows), "round_available": 0, "joint_available": 0,
        "round_omitted_wins": 0, "joint_omitted_wins": 0,
    }
    for row in rows:
        audit = (row.get("candidate_equation_audit") or {}).get(
            "recent_form_tier_reliable_v5", {},
        )
        context = audit.get("tier_win_credit") or {}
        features = row.setdefault("features", {})
        for feature, include_opponent, available_key, omitted_key in (
            (ROUND_FEATURE, False, "round_available", "round_omitted_wins"),
            (JOINT_FEATURE, True, "joint_available", "joint_omitted_wins"),
        ):
            a_credit, a_sample, a_omitted = _side_credit(
                context.get("a_ledger") or [], include_opponent=include_opponent,
            )
            b_credit, b_sample, b_omitted = _side_credit(
                context.get("b_ledger") or [], include_opponent=include_opponent,
            )
            reliability = max(
                min(1.0, a_sample / MIN_RECENT_MATCHES),
                min(1.0, b_sample / MIN_RECENT_MATCHES),
            )
            features[feature] = (
                (float(a_credit or 0.0) - float(b_credit or 0.0)) * reliability
                if a_sample or b_sample else None
            )
            if features[feature] is not None:
                coverage[available_key] += 1
            coverage[omitted_key] += a_omitted + b_omitted
    return coverage


def _paired_family_result(
    rows: list[dict[str, Any]], baseline_model: dict[str, Any],
    candidate_model: dict[str, Any],
) -> dict[str, Any]:
    baseline = predict_family_equation(rows, _runtime_model(baseline_model))
    candidate = predict_family_equation(rows, _runtime_model(candidate_model))
    wanted = [
        index for index in range(len(rows))
        if baseline[index] is not None and candidate[index] is not None
    ]
    targets = np.asarray([float(rows[index]["target_a_win"]) for index in wanted])
    old = np.asarray([baseline[index] for index in wanted], dtype=float)
    new = np.asarray([candidate[index] for index in wanted], dtype=float)
    return {
        "paired_targets": len(wanted),
        "baseline": _metrics(targets, old, total_targets=len(rows)),
        "candidate": _metrics(targets, new, total_targets=len(rows)),
        "paired_gain": _paired_probability_gain(targets, old, new),
    }


def _integrated_result(
    rows: list[dict[str, Any]], *, universe: str,
    baseline_contract: dict[str, Any], candidate_model: dict[str, Any],
    profile: str,
) -> dict[str, Any]:
    candidate_contract = copy.deepcopy(baseline_contract)
    universe_model = candidate_contract["universes"][universe]
    universe_model["runtime_family_models"]["recent_form"] = _runtime_model(
        candidate_model,
    )
    universe_model["family_profiles"]["recent_form"] = profile
    baseline = predict_contextual_combination_v18(
        rows, universe=universe, contract=baseline_contract,
    )["probabilities"]
    candidate = predict_contextual_combination_v18(
        rows, universe=universe, contract=candidate_contract,
    )["probabilities"]
    targets = np.asarray([float(row["target_a_win"]) for row in rows])
    old = np.asarray(baseline, dtype=float)
    new = np.asarray(candidate, dtype=float)
    return {
        "paired_targets": len(rows),
        "baseline": _metrics(targets, old, total_targets=len(rows)),
        "candidate": _metrics(targets, new, total_targets=len(rows)),
        "paired_gain": _paired_probability_gain(targets, old, new),
    }


def build_report(replay_dir: Path, contract_path: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    results: dict[str, Any] = {}
    for universe in ("atp", "wta"):
        rows = _read_replay(replay_dir / f"{universe}.jsonl.gz")
        _augment_pooled_main_features(rows)
        coverage = augment_candidate_features(rows)
        split = _split(rows)
        models = {
            profile: calibrate_family(
                split, family="recent_form", feature_profile=profile,
                allow_missingness_vote=False,
            )
            for profile in (BASELINE_PROFILE, ROUND_PROFILE, JOINT_PROFILE)
        }
        candidates = {}
        for profile in (ROUND_PROFILE, JOINT_PROFILE):
            family = _paired_family_result(
                split["holdout"], models[BASELINE_PROFILE], models[profile],
            )
            integrated = _integrated_result(
                split["holdout"], universe=universe,
                baseline_contract=contract, candidate_model=models[profile],
                profile=profile,
            )
            statuses = {
                family["paired_gain"]["status"],
                integrated["paired_gain"]["status"],
            }
            decision = (
                "SUPPORTED" if statuses == {"SUPPORTED"}
                else "REJECTED" if "REJECTED" in statuses
                else "INCONCLUSIVE"
            )
            candidates[profile] = {
                "family_holdout": family,
                "integrated_holdout_frozen_hierarchy": integrated,
                "decision": decision,
                "active_coefficients": models[profile].get("active_coefficients"),
            }
        results[universe] = {
            "rows": len(rows),
            "chronology": {key: len(value) for key, value in split.items()},
            "coverage": coverage,
            "baseline_profile": BASELINE_PROFILE,
            "candidates": candidates,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": "CHANGE-2026-11-20-228",
        "mode": "READ_ONLY_CHRONOLOGICAL_TIER_ROUND_OPPONENT_AUDIT",
        "round_scale": {key: round(value, 6) for key, value in _ROUND_PROGRESS.items()},
        "opponent_quality": "1 / (1 + ln(opponent_rank))",
        "double_counting_guard": (
            "joint candidate replaces standalone opponent quality and category-only credit"
        ),
        "results": results,
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument(
        "--contract", type=Path,
        default=Path("data/models/contextual-family-combination-v18.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = build_report(args.replay_dir, args.contract)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if not args.quiet:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
