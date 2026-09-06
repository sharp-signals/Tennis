"""Controlled pilot/backfill and offline replay CLI."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from src import fetch_data
from src.historical_acquisition import HistoricalAcquirer
from src.historical_replay import replay_matches
from src.historical_warehouse import HistoricalWarehouse


DEFAULT_PLAYERS = {"atp": [68074, 47275], "wta": [45854, 18455]}


def _assert_zero_llm() -> None:
    if (
        os.environ.get("LLM_MODE", "disabled") != "disabled"
        or os.environ.get("ALLOW_PAID_LLM", "0") != "0"
        or os.environ.get("LLM_POLICY", "never") != "never"
    ):
        raise RuntimeError(
            "Historical commands require LLM_MODE=disabled, ALLOW_PAID_LLM=0 and LLM_POLICY=never."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pilot", "backfill", "replay"))
    parser.add_argument("--warehouse", type=Path, default=Path(os.environ.get("HISTORICAL_WAREHOUSE_PATH", "data/historical_warehouse/sharp_history.sqlite3")))
    parser.add_argument("--tour", choices=("atp", "wta", "both"), default="both")
    parser.add_argument("--max-matches", type=int, default=100)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--confirm-backfill", default="")
    args = parser.parse_args()
    _assert_zero_llm()
    if args.mode == "backfill" and args.confirm_backfill != "I_UNDERSTAND_THE_QUOTA":
        parser.error("backfill requires --confirm-backfill I_UNDERSTAND_THE_QUOTA")
    warehouse = HistoricalWarehouse(args.warehouse)
    fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN = min(fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN, args.max_calls)
    tours = list(DEFAULT_PLAYERS) if args.tour == "both" else [args.tour]
    if args.mode in {"pilot", "backfill"}:
        if not fetch_data.RAPIDAPI_KEY:
            parser.error("RAPIDAPI_KEY is required for acquisition; replay remains fully offline.")
        acquirer = HistoricalAcquirer(warehouse)
        remaining = max(0, args.max_matches)
        acquired: list[str] = []
        selected_players = [(tour, player_id) for tour in tours for player_id in DEFAULT_PLAYERS[tour]]
        per_player = math.ceil(args.max_matches / len(selected_players)) if selected_players else 0
        for tour, player_id in selected_players:
            if remaining <= 0 or acquirer.metrics.calls_made >= args.max_calls:
                break
            ids = acquirer.acquire_player_past_matches(
                tour, player_id, resume=args.resume, max_records=min(remaining, per_player),
            )
            acquired.extend(ids)
            remaining -= len(ids)
        result = {"mode": args.mode, "acquisition": acquirer.metrics.as_dict(), "match_ids": acquired}
        if args.mode == "pilot":
            replay = replay_matches(warehouse, acquired, mode="pilot")
            result["replay"] = replay
            reconstructed = replay["metrics"]["matches_reconstructed"]
            result["pilot_metrics"] = {
                "calls_per_reconstructed_match": round(acquirer.metrics.calls_made / reconstructed, 4) if reconstructed else None,
                "cache_hit_rate": round(acquirer.metrics.cache_hits / max(1, acquirer.metrics.cache_hits + acquirer.metrics.calls_made), 4),
                "warehouse_size_bytes": warehouse.size_bytes(),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        matches = warehouse.list_matches(tour=None if args.tour == "both" else args.tour, limit=args.max_matches)
        print(json.dumps(replay_matches(warehouse, [m["canonical_match_id"] for m in matches]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
