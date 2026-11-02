"""Paired offline dry-run of the current model and contextual SHADOW v1."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
from typing import Any

from src import fetch_data
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_shadow_dry_run import (
    CURRENT_MODEL_VERSION, link_snapshot, orient_snapshot_probability,
    probability_metrics, replay_index, universe_for_snapshot,
)
from src.contextual_shadow_runtime import load_contract, predict_contextual_shadow
from scripts.replay_recent_form_candidates import _scope, _source_health


def _read_snapshots(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in value.get("snapshots", []) if isinstance(row, dict)]


def build_report(snapshots_path: Path) -> dict[str, Any]:
    atp = fetch_data.get_history("atp")
    wta = fetch_data.get_history("wta")
    combined = fetch_data.get_history("atp", tier="Challenger 125")
    frames = {
        "atp": _scope(atp, "main"), "wta": _scope(wta, "main"),
        "challenger": _scope(combined, "challenger"),
    }
    health = {name: _source_health(frame, universe=name) for name, frame in frames.items()}
    if any(not item["healthy_for_quality_replay"] for item in health.values()):
        raise RuntimeError("historical source health gate failed")
    replay = {
        name: build_contextual_family_replay_rows(frame, universe=name)
        for name, frame in frames.items()
    }
    index = replay_index(replay)
    contract = load_contract()
    all_snapshots = _read_snapshots(snapshots_path)
    settled = [row for row in all_snapshots if isinstance(row.get("outcome"), dict)]
    cohort = [
        row for row in settled
        if (row.get("pricing") or {}).get("model_version") == CURRENT_MODEL_VERSION
    ]
    paired, exclusions = [], Counter()
    for snapshot in cohort:
        replay_row, reason = link_snapshot(snapshot, index)
        if replay_row is None:
            exclusions[reason] += 1
            continue
        universe = universe_for_snapshot(snapshot)
        shadow = predict_contextual_shadow(replay_row, contract, universe=universe)
        current_probability = orient_snapshot_probability(snapshot, "sharp_estimate")
        market_probability = orient_snapshot_probability(snapshot, "market_probability")
        if current_probability is None:
            exclusions["CURRENT_PROBABILITY_UNAVAILABLE"] += 1
            continue
        paired.append({
            "snapshot_key": snapshot.get("key"), "universe": universe,
            "event_date": replay_row["event_date"],
            "commence_time_utc": snapshot.get("commence_time_utc"),
            "player_a": replay_row["player_a"], "player_b": replay_row["player_b"],
            "target_a_win": bool(replay_row["target_a_win"]),
            "current_probability_a": current_probability,
            "market_probability_a": market_probability,
            "contextual_probability_a": shadow["probability_model_a"],
            "contextual_interval_a": shadow["probability_interval_90_model_a"],
            "contextual_status": shadow["status"],
            "absolute_difference_pp": round(
                100.0 * abs(shadow["probability_model_a"] - current_probability), 2,
            ),
            "predicted_side_disagrees": (
                (shadow["probability_model_a"] >= 0.5) != (current_probability >= 0.5)
            ),
        })

    def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "contextual_shadow": probability_metrics(rows, "contextual_probability_a"),
            "current_model": probability_metrics(rows, "current_probability_a"),
            "market_baseline": probability_metrics(rows, "market_probability_a"),
            "ready_for_prospective_shadow": sum(
                row["contextual_status"] == "READY_FOR_PROSPECTIVE_SHADOW" for row in rows
            ),
            "prediction_side_disagreements": sum(row["predicted_side_disagrees"] for row in rows),
        }

    by_universe = {
        universe: metrics([row for row in paired if row["universe"] == universe])
        for universe in ("atp", "wta", "challenger")
    }
    return {
        "schema_version": 1,
        "status": "RETROSPECTIVE_DRY_RUN_NOT_PROSPECTIVE_VALIDATION",
        "current_model_version": CURRENT_MODEL_VERSION,
        "contextual_model_version": contract["model_version"],
        "contextual_configuration_fingerprint": contract["configuration_fingerprint"],
        "source_health": health,
        "population": {
            "all_snapshots": len(all_snapshots), "settled_snapshots": len(settled),
            "current_model_settled_cohort": len(cohort), "paired": len(paired),
            "excluded": dict(sorted(exclusions.items())),
        },
        "overall": metrics(paired), "by_universe": by_universe,
        "largest_probability_differences": sorted(
            paired, key=lambda row: row["absolute_difference_pp"], reverse=True,
        )[:15],
        "market_used_by_contextual_model": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, default=Path("data/calibration_snapshots.json"))
    parser.add_argument("--provider-cache", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    report = build_report(args.snapshots)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
