"""Run the read-only recent-form replay against operational histories."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src import fetch_data
from src.recent_form_replay import replay_recent_form


def _scope(frame, wanted: str):
    scope = frame.get("_history_competition_scope")
    if scope is None:
        return frame.copy() if wanted == "main" else frame.iloc[0:0].copy()
    return frame[scope == wanted].copy()


def build_report() -> dict:
    atp = fetch_data.get_history("atp")
    wta = fetch_data.get_history("wta")
    combined = fetch_data.get_history("atp", tier="Challenger 125")
    universes = {
        "atp": _scope(atp, "main"),
        "wta": _scope(wta, "main"),
        "challenger": _scope(combined, "challenger"),
    }
    return {
        "mode": "READ_ONLY_EX_ANTE_REPLAY",
        "rapidapi_used": False,
        "market_used": False,
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
