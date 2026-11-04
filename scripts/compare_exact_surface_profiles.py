"""Compare exact four-context surface candidates without production effects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src import fetch_data
from src.contextual_family_calibration import compare_exact_surface_profiles
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
)
from scripts.replay_recent_form_candidates import _scope


def build_report() -> dict:
    atp_history = fetch_data.get_history("atp")
    # TennisMyLife is authoritative for ATP indoor/outdoor.  Its WTA indoor
    # field is sparse, while the existing tennis-data cache carries an
    # explicit Court column throughout the replay period.
    wta_surface_history = fetch_data._load_tennisdata_couk_multi_year(
        "wta", fetch_data.HISTORY_YEARS_TO_LOAD,
    )
    if wta_surface_history is None or wta_surface_history.empty:
        wta_surface_history = fetch_data.get_history("wta")
        wta_source = str(
            wta_surface_history.attrs.get("history_source") or "fallback"
        )
    else:
        wta_source = "tennisdata.co.uk (explicit Court field)"
    raw_frames = {
        "atp": _scope(atp_history, "main"),
        "wta": _scope(wta_surface_history, "main"),
    }
    enriched = {
        tour: enrich_tournament_surface_contexts(frame)
        for tour, frame in raw_frames.items()
    }
    frames = {tour: value[0] for tour, value in enriched.items()}
    rows = {
        tour: build_contextual_family_replay_rows(frame, universe=tour)
        for tour, frame in frames.items()
    }
    contexts = ["hard_outdoor", "hard_indoor", "clay", "grass"]
    context_rows = {
        tour: {
            context: [
                row for row in items
                if row.get("diagnostics", {}).get("surface_context") == context
            ]
            for context in contexts
        }
        for tour, items in rows.items()
    }
    return {
        "mode": "READ_ONLY_EXACT_SURFACE_PROFILE_COMPARISON",
        "history_sources": {
            "atp": str(atp_history.attrs.get("history_source") or "unknown"),
            "wta": wta_source,
        },
        "comparisons": {
            tour: compare_exact_surface_profiles(items, universe=tour)
            for tour, items in rows.items()
        },
        "replay_rows": {tour: len(items) for tour, items in rows.items()},
        "context_comparisons": {
            tour: {
                context: compare_exact_surface_profiles(
                    items, universe=f"{tour}:{context}",
                )
                for context, items in grouped.items()
            }
            for tour, grouped in context_rows.items()
        },
        "context_rows": {
            tour: {
                context: len(items) for context, items in grouped.items()
            }
            for tour, grouped in context_rows.items()
        },
        "surface_context_recovery": {
            tour: value[1] for tour, value in enriched.items()
        },
        "four_contexts": contexts,
        "market_used": False,
        "rapidapi_used": False,
        "production_effect": False,
        "promotion_authorized": False,
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
