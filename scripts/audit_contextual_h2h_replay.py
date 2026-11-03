"""Audit H2H sample, recency and context before defining a family equation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.replay_recent_form_candidates import _scope
from src import fetch_data
from src.contextual_h2h_replay import (
    build_contextual_h2h_replay_rows,
    summarize_contextual_h2h_rows,
)
from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
)


def _split(rows: list[dict]) -> dict[str, list[dict]]:
    dates = sorted({row["event_date"] for row in rows})
    if not dates:
        return {"validation": [], "holdout": []}
    validation_start = dates[int(len(dates) * 0.60)]
    holdout_start = dates[int(len(dates) * 0.80)]
    return {
        "validation": [
            row for row in rows
            if validation_start <= row["event_date"] < holdout_start
        ],
        "holdout": [row for row in rows if row["event_date"] >= holdout_start],
    }


def build_report() -> dict:
    atp = _scope(fetch_data.get_history("atp"), "main")
    wta = fetch_data._load_tennisdata_couk_multi_year(
        "wta", fetch_data.HISTORY_YEARS_TO_LOAD,
    )
    if wta is None or wta.empty:
        wta = fetch_data.get_history("wta")
    raw = {"atp": atp, "wta": _scope(wta, "main")}
    enriched = {
        tour: enrich_tournament_surface_contexts(frame)[0]
        for tour, frame in raw.items()
    }
    replay = {
        tour: build_contextual_h2h_replay_rows(frame)
        for tour, frame in enriched.items()
    }
    return {
        "mode": "READ_ONLY_CONTEXTUAL_H2H_AUDIT",
        "recent_window_days": 730,
        "universes": {
            tour: {
                partition: summarize_contextual_h2h_rows(items)
                for partition, items in _split(rows).items()
            }
            for tour, rows in replay.items()
        },
        "interpretation_guards": {
            "zero_h2h_is_observed_none_not_missing": True,
            "same_day_results_excluded": True,
            "single_match_not_automatically_material": True,
            "global_and_context_h2h_not_summed": True,
            "market_used": False,
            "production_effect": False,
            "family_equation_selected": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = build_report()
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if not args.quiet:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
