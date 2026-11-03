"""Compare exact four-context surface candidates without production effects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src import fetch_data
from src.contextual_family_calibration import compare_exact_surface_profiles
from src.contextual_family_replay import build_contextual_family_replay_rows
from scripts.replay_recent_form_candidates import _scope


def build_report() -> dict:
    frames = {
        "atp": _scope(fetch_data.get_history("atp"), "main"),
        "wta": _scope(fetch_data.get_history("wta"), "main"),
    }
    rows = {
        tour: build_contextual_family_replay_rows(frame, universe=tour)
        for tour, frame in frames.items()
    }
    return {
        "mode": "READ_ONLY_EXACT_SURFACE_PROFILE_COMPARISON",
        "comparisons": {
            tour: compare_exact_surface_profiles(items, universe=tour)
            for tour, items in rows.items()
        },
        "replay_rows": {tour: len(items) for tour, items in rows.items()},
        "four_contexts": ["hard_outdoor", "hard_indoor", "clay", "grass"],
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
