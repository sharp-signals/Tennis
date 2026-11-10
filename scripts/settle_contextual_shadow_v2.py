"""Settle previous contextual SHADOW v2 observations and evaluate them."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import fetch_data  # noqa: E402
from src.contextual_shadow_settlement_v2 import (  # noqa: E402
    EVALUATION_PATH,
    MARKET_PATH,
    OBSERVATIONS_PATH,
    OUTCOMES_PATH,
    append_outcomes,
    build_evaluation,
    confirmed_outcome,
    read_jsonl,
    write_evaluation_atomic,
)


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bounded_pending_batch(
    rows: list[dict[str, Any]], limit: int,
) -> list[dict[str, Any]]:
    """Keep old retries alive without letting them starve recent matches."""
    ordered = sorted(
        rows, key=lambda row: str(row.get("commence_time_utc") or ""),
    )
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    oldest_slots = max(1, limit // 5)
    newest_slots = limit - oldest_slots
    return ordered[:oldest_slots] + ordered[-newest_slots:]


def settle(
    *, observations_path: Path = OBSERVATIONS_PATH,
    outcomes_path: Path = OUTCOMES_PATH,
    market_path: Path | None = None,
    evaluation_path: Path = EVALUATION_PATH,
    max_observations: int = 0,
    evaluate_only: bool = False,
) -> dict[str, Any]:
    if market_path is None:
        market_path = (
            MARKET_PATH if observations_path == OBSERVATIONS_PATH
            else observations_path.with_name("contextual_shadow_market-v2.jsonl")
        )
    observations = read_jsonl(observations_path)
    outcomes = read_jsonl(outcomes_path)
    markets = read_jsonl(market_path)
    settled_ids = {
        str(row.get("observation_id")) for row in outcomes
        if row.get("observation_id")
    }
    now = datetime.now(timezone.utc)
    pending = []
    if not evaluate_only:
        for row in observations:
            observation_id = str(row.get("observation_id") or "")
            commence = _parse_time(row.get("commence_time_utc"))
            if (
                observation_id and observation_id not in settled_ids
                and commence is not None
                and commence + timedelta(hours=2) < now
            ):
                pending.append(row)
    pending = _bounded_pending_batch(pending, max_observations)

    player_cache: dict[tuple[str, int], list[dict] | None] = {}

    def matches_for(tour: str, player_id: Any) -> list[dict]:
        try:
            key = (tour, int(player_id))
        except (TypeError, ValueError):
            return []
        if key not in player_cache:
            player_cache[key] = fetch_data.fetch_player_recent_matches(
                tour, key[1], force_refresh=True,
            )
        return player_cache[key] or []

    additions = []
    unresolved = 0
    for observation in pending:
        tour = str(observation.get("tour") or "").casefold()
        players = observation.get("players") or {}
        a_id = (players.get("a") or {}).get("id")
        b_id = (players.get("b") or {}).get("id")
        result = confirmed_outcome(observation, matches_for(tour, a_id))
        if result is None:
            result = confirmed_outcome(observation, matches_for(tour, b_id))
        if result is None:
            unresolved += 1
        else:
            additions.append(result)
    added = append_outcomes(additions, outcomes_path)
    final_outcomes = read_jsonl(outcomes_path)
    evaluation = build_evaluation(observations, final_outcomes, markets)
    write_evaluation_atomic(evaluation, evaluation_path)
    if (
        evaluation["settlement_audit"]["status"] != "HEALTHY"
        or evaluation["market_audit"]["status"] != "HEALTHY"
    ):
        raise RuntimeError("CONTEXTUAL_SHADOW_SETTLEMENT_CONTRACT_VIOLATION")
    return {
        "status": "COMPLETED",
        "observations": len(observations),
        "pending_examined": len(pending),
        "outcomes_added": added,
        "pending_without_confirmed_result": unresolved,
        "players_queried": len(player_cache),
        "evaluate_only": evaluate_only,
        "evaluation_state": evaluation["evaluation_state"],
        "ready_settled": evaluation["counts"]["ready_settled"],
        "ready_pending": evaluation["counts"]["ready_pending"],
        "market_observations": evaluation["counts"]["market_observations"],
        "ready_settled_with_market": evaluation["counts"][
            "ready_settled_with_market"
        ],
        "validation_gate": evaluation["validation_gate"]["status"],
        "isolation": {
            "predictions_rewritten": False,
            "market_used_for_prediction": False,
            "paper_created": False,
            "green_created": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-observations", type=int, default=50,
        help=(
            "Pending observations to examine, reserving 20%% for the oldest "
            "and the remainder for the newest; 0 disables the bound"
        ),
    )
    parser.add_argument(
        "--evaluate-only", action="store_true",
        help="Refresh derived metrics without querying results",
    )
    args = parser.parse_args()
    report = settle(
        max_observations=max(0, args.max_observations),
        evaluate_only=args.evaluate_only,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

