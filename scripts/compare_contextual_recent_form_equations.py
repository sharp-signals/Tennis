"""Compare nested, market-free recent-form candidates for ATP and WTA."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src import fetch_data
from src.contextual_family_calibration import compare_recent_form_feature_profiles
from src.contextual_family_replay import build_contextual_family_replay_rows
from scripts.replay_recent_form_candidates import _scope, _source_health


def build_report(*, universes: tuple[str, ...] = ("atp", "wta")) -> dict:
    available = {
        "atp": _scope(fetch_data.get_history("atp"), "main"),
        "wta": _scope(fetch_data.get_history("wta"), "main"),
    }
    frames = {name: available[name] for name in universes}
    health = {
        name: _source_health(frame, universe=name)
        for name, frame in frames.items()
    }
    unhealthy = [
        name for name, state in health.items()
        if not state["healthy_for_quality_replay"]
    ]
    if unhealthy:
        raise RuntimeError("Fonte histórica inadequada: " + ", ".join(unhealthy))
    comparisons = {}
    for name, frame in frames.items():
        rows = build_contextual_family_replay_rows(frame, universe=name)
        comparisons[name] = compare_recent_form_feature_profiles(
            rows, universe=name,
        )
    return {
        "mode": "READ_ONLY_CONTEXTUAL_RECENT_FORM_COMPARISON",
        "primary_decision_scope": list(universes),
        "challenger_role": "OBSERVATIONAL_ONLY_NOT_INCLUDED",
        "source_health": health,
        "comparisons": comparisons,
        "market_used": False,
        "rapidapi_used": False,
        "production_effect": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider-cache", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
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
