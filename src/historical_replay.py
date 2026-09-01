"""Offline replay engine for the BACKTEST_RECONSTRUCTED universe."""

from __future__ import annotations

import uuid
from typing import Any

from .historical_snapshot import ENGINE_VERSION, build_historical_snapshot, config_hash, git_commit
from .historical_warehouse import CHANGE_ID, HistoricalWarehouse, utc_now


UNIVERSE = "BACKTEST_RECONSTRUCTED"


def replay_matches(warehouse: HistoricalWarehouse, match_ids: list[str]) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    warehouse.create_run({
        "replay_run_id": run_id,
        "mode": "offline_replay",
        "engine_version": ENGINE_VERSION,
        "config_hash": config_hash(),
        "sample_universe": {"name": UNIVERSE, "match_ids": match_ids},
        "created_at_utc": utc_now(),
        "git_commit": git_commit(),
        "change_id": CHANGE_ID,
    })
    reconstructed = failures = 0
    exact_fields = reconstructed_fields = usable_market_matches = 0
    dimensions = {"tours": set(), "years": set(), "surfaces": set(), "tournament_levels": set()}
    failure_details: list[dict[str, str]] = []
    unavailable: dict[str, int] = {}
    temporal_rejections = 0
    for match_id in match_ids:
        match = warehouse.get_match(match_id)
        if not match:
            failures += 1
            continue
        try:
            dimensions["tours"].add(str(match.get("tour") or "UNAVAILABLE"))
            dimensions["years"].add(str(match["event_start_utc"])[:4])
            dimensions["surfaces"].add(str(match.get("surface") or "UNAVAILABLE"))
            dimensions["tournament_levels"].add(str(match.get("tournament_level") or "UNAVAILABLE"))
            snapshot = build_historical_snapshot(warehouse, match, match["event_start_utc"])
            warehouse.store_snapshot(snapshot)
            prediction = {
                "universe": UNIVERSE,
                "features": snapshot["feature_values"]["engine_features"],
                "divergence": snapshot["feature_values"]["engine_divergence"],
            }
            # Settlement is attached only after prediction generation and is
            # never passed into build_historical_snapshot.
            settlement = {
                "winner_id": match.get("outcome_winner_id"),
                "result": match.get("outcome_result"),
                "temporal_class": "EX_POST_ONLY",
            }
            warehouse.store_replay_output(
                run_id=run_id, match_id=match_id, snapshot_id=snapshot["snapshot_id"],
                prediction=prediction, settlement=settlement,
            )
            reconstructed += 1
            exact_fields += snapshot["coverage"]["exact_ex_ante_fields"]
            reconstructed_fields += snapshot["coverage"]["reconstructed_ex_ante_fields"]
            usable_market_matches += int(snapshot["coverage"]["usable_market_quotes"] > 0)
            for field in snapshot["missing_data"]:
                unavailable[field] = unavailable.get(field, 0) + 1
            temporal_rejections += sum(
                value for value in snapshot["temporal_rejections"].values()
                if isinstance(value, int) and not isinstance(value, bool)
            )
        except Exception as exc:
            failures += 1
            failure_details.append({"match_id": match_id, "error": str(exc)})
    metrics = {
        "matches_requested": len(match_ids),
        "matches_reconstructed": reconstructed,
        "reconstruction_coverage": round(reconstructed / len(match_ids), 4) if match_ids else 0.0,
        "exact_ex_ante_fields": exact_fields,
        "reconstructed_ex_ante_fields": reconstructed_fields,
        "matches_with_usable_market_odds": usable_market_matches,
        "unavailable_fields": unavailable,
        "failures": failures,
        "failure_details": failure_details,
        "temporal_leakage_rejections": temporal_rejections,
        "universe": UNIVERSE,
        "warehouse_size_bytes": warehouse.size_bytes(),
        "sample_dimensions": {key: sorted(values) for key, values in dimensions.items()},
    }
    warehouse.complete_run(run_id, metrics)
    return {"replay_run_id": run_id, "metrics": metrics}
