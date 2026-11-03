"""Paired chronological comparison of legacy and contextual family equations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src import fetch_data
from src.contextual_family_calibration import compare_family_feature_profiles
from src.contextual_family_replay import build_contextual_family_replay_rows
from scripts.replay_recent_form_candidates import _scope, _source_health


def build_report(
    *, universes: tuple[str, ...] = ("atp", "wta", "challenger"),
    contextual_profile: str = "contextual_v1",
) -> dict:
    atp = fetch_data.get_history("atp")
    wta = fetch_data.get_history("wta")
    available = {
        "atp": _scope(atp, "main"),
        "wta": _scope(wta, "main"),
    }
    if "challenger" in universes:
        combined = fetch_data.get_history("atp", tier="Challenger 125")
        available["challenger"] = _scope(combined, "challenger")
    frames = {name: available[name] for name in universes}
    health = {name: _source_health(frame, universe=name) for name, frame in frames.items()}
    unhealthy = [name for name, value in health.items() if not value["healthy_for_quality_replay"]]
    if unhealthy:
        raise RuntimeError("Fonte historica inadequada: " + ", ".join(unhealthy))
    comparisons = {}
    for name, frame in frames.items():
        rows = build_contextual_family_replay_rows(frame, universe=name)
        comparisons[name] = compare_family_feature_profiles(
            rows, universe=name, contextual_profile=contextual_profile,
        )
    return {
        "mode": "READ_ONLY_CONTEXTUAL_EQUATION_COMPARISON",
        "contextual_profile": contextual_profile,
        "primary_decision_scope": [name for name in universes if name in {"atp", "wta"}],
        "challenger_role": "OBSERVATIONAL_ONLY",
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
    parser.add_argument(
        "--universes", nargs="+", choices=("atp", "wta", "challenger"),
        default=("atp", "wta"),
    )
    parser.add_argument(
        "--contextual-profile", choices=("contextual_v1", "contextual_v2"),
        default="contextual_v2",
    )
    args = parser.parse_args()
    if args.provider_cache:
        os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    report = build_report(
        universes=tuple(args.universes), contextual_profile=args.contextual_profile,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
