"""Fit and evaluate the five family-level equations, without production use."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src import fetch_data
from src.contextual_family_calibration import calibrate_contextual_families
from src.contextual_family_replay import build_contextual_family_replay_rows
from scripts.replay_recent_form_candidates import _scope, _source_health


def build_report() -> dict:
    atp = fetch_data.get_history("atp")
    wta = fetch_data.get_history("wta")
    combined = fetch_data.get_history("atp", tier="Challenger 125")
    frames = {
        "atp": _scope(atp, "main"),
        "wta": _scope(wta, "main"),
        "challenger": _scope(combined, "challenger"),
    }
    health = {name: _source_health(frame, universe=name) for name, frame in frames.items()}
    unhealthy = [name for name, value in health.items() if not value["healthy_for_quality_replay"]]
    if unhealthy:
        raise RuntimeError("Fonte histórica inadequada: " + ", ".join(unhealthy))
    calibrations = {}
    for name, frame in frames.items():
        rows = build_contextual_family_replay_rows(frame, universe=name)
        calibrations[name] = calibrate_contextual_families(rows, universe=name)
    return {
        "mode": "READ_ONLY_FAMILY_LEVEL_CALIBRATION",
        "source_health": health,
        "calibrations": calibrations,
        "market_used": False,
        "rapidapi_used": False,
        "production_effect": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider-cache", type=Path)
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
