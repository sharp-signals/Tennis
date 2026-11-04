"""Capture a frozen market benchmark after contextual predictions exist."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import fetch_data  # noqa: E402
from src.contextual_shadow_market_v2 import (  # noqa: E402
    MARKET_PATH,
    append_markets,
    build_market_observation,
    match_fixture,
    read_markets,
)
from src.contextual_shadow_settlement_v2 import (  # noqa: E402
    OBSERVATIONS_PATH,
    read_jsonl,
)


SUMMARY_PATH = Path("data/validation/contextual-shadow-v2-market-latest.json")


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _write_json_atomic(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def capture(
    *, max_observations: int = 50,
    observations_path: Path = OBSERVATIONS_PATH,
    market_path: Path = MARKET_PATH,
    summary_path: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    observations = read_jsonl(observations_path)
    existing = read_markets(market_path)
    frozen_ids = {
        str(row.get("observation_id")) for row in existing
        if row.get("observation_id")
    }
    now = datetime.now(timezone.utc)
    pending = []
    for row in observations:
        shadow = row.get("contextual_shadow") or {}
        analyzed = _parse_time(row.get("analyzed_at_utc"))
        commence = _parse_time(row.get("commence_time_utc"))
        if (
            row.get("observation_id") not in frozen_ids
            and shadow.get("status") == "READY_FOR_PROSPECTIVE_SHADOW"
            and analyzed is not None
            and commence is not None
            and analyzed <= now < commence
        ):
            pending.append(row)
    pending.sort(key=lambda row: str(row.get("commence_time_utc") or ""))
    if max_observations > 0:
        pending = pending[:max_observations]

    reset_calls = getattr(fetch_data, "reset_rapidapi_call_count", None)
    if callable(reset_calls):
        reset_calls()
    fixtures = fetch_data.fetch_resilient_discovery_fixtures()
    linked: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unlinked = 0
    for observation in pending:
        fixture = match_fixture(observation, fixtures)
        if fixture is None:
            unlinked += 1
        else:
            linked.append((observation, fixture))

    linked_fixtures = [fixture for _, fixture in linked]
    fetch_data.prepare_the_odds_market_index(linked_fixtures)
    additions = []
    source_counts: dict[str, int] = {}
    unavailable = 0
    for observation, fixture in linked:
        odds, provenance = fetch_data.fetch_the_odds_moneyline_with_provenance(
            fixture,
        )
        if not odds or not provenance:
            odds, provenance = (
                fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(
                    fixture,
                )
            )
        market = (
            build_market_observation(observation, fixture, odds, provenance)
            if odds and provenance else None
        )
        if market is None:
            unavailable += 1
            continue
        source = str(market.get("source") or "UNKNOWN")
        source_counts[source] = source_counts.get(source, 0) + 1
        additions.append(market)
    added = append_markets(additions, market_path)
    report = {
        "schema_version": 1,
        "status": "COMPLETED",
        "captured_at_utc": now.isoformat(timespec="seconds"),
        "observations": len(observations),
        "already_frozen": len(frozen_ids),
        "pending_examined": len(pending),
        "fixtures_discovered": len(fixtures),
        "fixtures_linked": len(linked),
        "fixtures_unlinked": unlinked,
        "market_quotes_added": added,
        "market_unavailable": unavailable,
        "source_counts": dict(sorted(source_counts.items())),
        "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
        "isolation": {
            "prediction_ledger_rewritten": False,
            "market_used_for_prediction": False,
            "edge_used_for_decision": False,
            "paper_created": False,
            "green_created": False,
            "reports_published": False,
        },
    }
    _write_json_atomic(report, summary_path)
    fetch_data.flush_tournament_cache()
    fetch_data.flush_fixtures_cache()
    fetch_data.persist_rapidapi_usage(
        status="contextual_shadow_market_v2", matches=added,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-observations", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(
        capture(max_observations=max(0, args.max_observations)),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
