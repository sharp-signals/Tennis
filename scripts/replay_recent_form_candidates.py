"""Run the read-only recent-form replay against operational histories."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import pandas as pd

from src import fetch_data
from src.recent_form_replay import replay_recent_form
from src.recent_form_audit import _column, _parse_history_dates, _positive_number


MIN_BILATERAL_RANK_COVERAGE_PCT = 90.0
MAX_SOURCE_STALENESS_DAYS = 14


def _scope(frame, wanted: str):
    scope = frame.get("_history_competition_scope")
    if scope is None:
        return frame.copy() if wanted == "main" else frame.iloc[0:0].copy()
    return frame[scope == wanted].copy()


def _source_health(frame, *, universe: str) -> dict:
    dates = _parse_history_dates(_column(frame, "event_date"))
    bilateral = (
        _positive_number(_column(frame, "winner_rank"))
        & _positive_number(_column(frame, "loser_rank"))
    )
    rank_pct = 100.0 * float(bilateral.sum()) / max(1, len(frame))
    latest = dates.max()
    latest_date = latest.date() if pd.notna(latest) else None
    today = datetime.now(timezone.utc).date()
    staleness = (today - latest_date).days if latest_date else None
    healthy = (
        len(frame) > 0
        and rank_pct >= MIN_BILATERAL_RANK_COVERAGE_PCT
        and staleness is not None
        and staleness <= MAX_SOURCE_STALENESS_DAYS
    )
    return {
        "universe": universe,
        "source": frame.attrs.get("history_source"),
        "rows": int(len(frame)),
        "bilateral_rank_coverage_pct": round(rank_pct, 2),
        "latest_event_date": latest_date.isoformat() if latest_date else None,
        "staleness_days": staleness,
        "required_rank_coverage_pct": MIN_BILATERAL_RANK_COVERAGE_PCT,
        "maximum_staleness_days": MAX_SOURCE_STALENESS_DAYS,
        "healthy_for_quality_replay": healthy,
    }


def build_report() -> dict:
    atp = fetch_data.get_history("atp")
    wta = fetch_data.get_history("wta")
    combined = fetch_data.get_history("atp", tier="Challenger 125")
    universes = {
        "atp": _scope(atp, "main"),
        "wta": _scope(wta, "main"),
        "challenger": _scope(combined, "challenger"),
    }
    health = {
        universe: _source_health(frame, universe=universe)
        for universe, frame in universes.items()
    }
    unhealthy = [name for name, status in health.items() if not status["healthy_for_quality_replay"]]
    if unhealthy:
        details = "; ".join(
            f"{name}: rank={health[name]['bilateral_rank_coverage_pct']}%, "
            f"staleness={health[name]['staleness_days']}d, source={health[name]['source']}"
            for name in unhealthy
        )
        raise RuntimeError(
            "Fonte histórica inadequada para qualidade adversarial; "
            "replay recusado em vez de degradar silenciosamente. " + details
        )
    return {
        "mode": "READ_ONLY_EX_ANTE_REPLAY",
        "rapidapi_used": False,
        "market_used": False,
        "source_health": health,
        "reports": {
            universe: replay_recent_form(frame, universe=universe)
            for universe, frame in universes.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--provider-cache", type=Path,
        help="Optional last-known-good cache directory for the public provider.",
    )
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    report = build_report()
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
