"""Audit cached four-context player coverage without network or production effects."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
from typing import Any

from src.contextual_surface_ledger import (
    SURFACE_CONTEXTS,
    build_provider_surface_ledger,
)


def _performance(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = ((document.get("entries") or {}).get("perf_breakdown") or {})
    data = entry.get("data") if isinstance(entry, dict) else None
    return data if isinstance(data, dict) else None


def _tour_audit(root: Path, tour: str, *, as_of: date) -> dict[str, Any]:
    files = sorted((root / tour).glob("*.json"))
    totals = Counter()
    contexts = {context: Counter() for context in SURFACE_CONTEXTS}
    for path in files:
        totals["cache_files"] += 1
        performance = _performance(path)
        if performance is None:
            continue
        totals["profiles_with_performance"] += 1
        ledger = build_provider_surface_ledger(performance, as_of=as_of)
        if ledger["available_contexts"] == len(SURFACE_CONTEXTS):
            totals["profiles_with_all_four_career_contexts"] += 1
        for context, row in ledger["contexts"].items():
            if row["career"] is not None:
                contexts[context]["career"] += 1
                if row["career"]["matches"] >= 10:
                    contexts[context]["career_ge10"] += 1
            if row["current_season"] is not None:
                contexts[context]["current_season"] += 1
                if row["current_season"]["matches"] >= 5:
                    contexts[context]["current_season_ge5"] += 1
            if row["previous_season"] is not None:
                contexts[context]["previous_season"] += 1
                if row["previous_season"]["matches"] >= 5:
                    contexts[context]["previous_season_ge5"] += 1
            if row["current_vs_previous_win_pct_pp"] is not None:
                contexts[context]["comparable_seasons"] += 1
                if (
                    row["current_season"]["matches"] >= 5
                    and row["previous_season"]["matches"] >= 5
                ):
                    contexts[context]["comparable_seasons_both_ge5"] += 1
    return {
        "tour": tour,
        **dict(totals),
        "contexts": {key: dict(value) for key, value in contexts.items()},
    }


def build_report(root: Path, *, as_of: date) -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_SURFACE_LEDGER_COVERAGE_AUDIT",
        "as_of": as_of.isoformat(),
        "tours": {
            tour: _tour_audit(root, tour, as_of=as_of)
            for tour in ("atp", "wta")
        },
        "four_contexts": list(SURFACE_CONTEXTS),
        "provider_aggregates_are_not_summed_with_match_history": True,
        "market_used": False,
        "network_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=Path("data/cache/players"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.cache_root, as_of=args.as_of)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
