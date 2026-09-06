"""Offline replay engine for the BACKTEST_RECONSTRUCTED universe."""

from __future__ import annotations

import uuid
from typing import Any

from .historical_snapshot import ENGINE_VERSION, REPLAY_VERSION, build_historical_snapshot, config_hash, git_commit
from .historical_warehouse import CHANGE_ID, HistoricalWarehouse, utc_now


UNIVERSE = "BACKTEST_RECONSTRUCTED"
ALLOWED_MODES = {
    "offline_replay", "pilot", "coverage_enrichment_baseline",
    "coverage_enrichment",
}


def replay_matches(
    warehouse: HistoricalWarehouse,
    match_ids: list[str],
    *,
    mode: str = "offline_replay",
    replay_version: str = REPLAY_VERSION,
) -> dict[str, Any]:
    if mode not in ALLOWED_MODES:
        raise ValueError(f"Modo de replay inválido: {mode}")
    requested_ids = [str(match_id) for match_id in match_ids]
    unique_ids = list(dict.fromkeys(requested_ids))
    duplicate_ids = sorted({match_id for match_id in requested_ids if requested_ids.count(match_id) > 1})
    run_id = str(uuid.uuid4())
    warehouse.create_run({
        "replay_run_id": run_id,
        "mode": mode,
        "engine_version": ENGINE_VERSION,
        "config_hash": config_hash(),
        "sample_universe": {
            "name": UNIVERSE, "match_ids": unique_ids,
            "requested_positions": len(requested_ids),
            "duplicate_input_ids": duplicate_ids,
        },
        "created_at_utc": utc_now(),
        "git_commit": git_commit(),
        "change_id": CHANGE_ID,
    })
    reconstructed = failures = 0
    exact_fields = reconstructed_fields = usable_market_matches = 0
    dimensions = {"tours": set(), "years": set(), "surfaces": set(), "tournament_levels": set()}
    failure_details: list[dict[str, str]] = []
    unavailable: dict[str, int] = {}
    availability: dict[str, int] = {}
    available_histogram: dict[int, int] = {}
    dimension_coverage: dict[str, dict[str, dict[str, int]]] = {
        "tour": {}, "surface": {}, "tournament_level": {},
    }
    temporal_rejections = 0
    h2h_status_counts: dict[str, int] = {}
    for match_id in unique_ids:
        match = warehouse.get_effective_match(match_id)
        if not match:
            failures += 1
            continue
        try:
            dimensions["tours"].add(str(match.get("tour") or "UNAVAILABLE"))
            dimensions["years"].add(str(match["event_start_utc"])[:4])
            dimensions["surfaces"].add(str(match.get("surface") or "UNAVAILABLE"))
            dimensions["tournament_levels"].add(str(match.get("tournament_level") or "UNAVAILABLE"))
            snapshot = build_historical_snapshot(
                warehouse, match, match["event_start_utc"], replay_version=replay_version,
            )
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
            classified = snapshot["feature_values"]["classified"]
            h2h_status = str((classified.get("h2h") or {}).get("status") or "UNCLASSIFIED")
            h2h_status_counts[h2h_status] = h2h_status_counts.get(h2h_status, 0) + 1
            available_count = sum(int(item["available"]) for item in classified.values())
            available_histogram[available_count] = available_histogram.get(available_count, 0) + 1
            for field, item in classified.items():
                availability[field] = availability.get(field, 0) + int(item["available"])
            dimension_values = {
                "tour": str(match.get("tour") or "UNAVAILABLE"),
                "surface": str(match.get("surface") or "UNAVAILABLE"),
                "tournament_level": str(match.get("tournament_level") or "UNAVAILABLE"),
            }
            for dimension, value in dimension_values.items():
                bucket = dimension_coverage[dimension].setdefault(
                    value, {"matches": 0, "available_feature_cells": 0, "total_feature_cells": 0},
                )
                bucket["matches"] += 1
                bucket["available_feature_cells"] += available_count
                bucket["total_feature_cells"] += len(classified)
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
        "requested_positions": len(requested_ids),
        "unique_matches_requested": len(unique_ids),
        "duplicate_input_ids": duplicate_ids,
        "matches_reconstructed_unique": reconstructed,
        "unique_reconstruction_coverage": round(reconstructed / len(unique_ids), 4) if unique_ids else 0.0,
        # Compatibility aliases now use the unique-match denominator.
        "matches_requested": len(unique_ids),
        "matches_reconstructed": reconstructed,
        "reconstruction_coverage": round(reconstructed / len(unique_ids), 4) if unique_ids else 0.0,
        "exact_ex_ante_fields": exact_fields,
        "reconstructed_ex_ante_fields": reconstructed_fields,
        "matches_with_usable_market_odds": usable_market_matches,
        "unavailable_fields": unavailable,
        "available_fields": availability,
        "h2h_status_counts": h2h_status_counts,
        "available_features_per_snapshot": {
            "mean": round(sum(count * matches for count, matches in available_histogram.items()) / reconstructed, 4)
            if reconstructed else 0.0,
            "histogram_0_to_7": {str(index): available_histogram.get(index, 0) for index in range(8)},
        },
        "coverage_by_dimension": dimension_coverage,
        "failures": failures,
        "failure_details": failure_details,
        "temporal_leakage_rejections": temporal_rejections,
        "universe": UNIVERSE,
        "warehouse_size_bytes": warehouse.size_bytes(),
        "sample_dimensions": {key: sorted(values) for key, values in dimensions.items()},
    }
    warehouse.complete_run(run_id, metrics)
    return {"replay_run_id": run_id, "metrics": metrics}
