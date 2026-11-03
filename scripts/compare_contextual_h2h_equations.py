"""Select an H2H candidate on validation and report untouched holdout support."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.replay_recent_form_candidates import _scope
from src import fetch_data
from src.contextual_family_calibration import calibrate_family
from src.contextual_family_replay import _split
from src.contextual_h2h_replay import build_contextual_h2h_replay_rows
from src.contextual_tournament_surface_registry import (
    enrich_tournament_surface_contexts,
)


PROFILES = (
    "h2h_global_shrunk_v1",
    "h2h_same_context_modifier_v1",
    "h2h_recent_context_modifier_v1",
)


def _comparison(rows: list[dict]) -> dict:
    split = _split(rows)
    candidates = {
        profile: calibrate_family(
            split,
            family="matchup_h2h",
            feature_profile=profile,
        )
        for profile in PROFILES
    }
    usable = {
        name: value for name, value in candidates.items()
        if value.get("validation", {}).get("model", {}).get(
            "validation_log_loss",
        ) is not None
    }
    selected = min(
        usable,
        key=lambda name: (
            usable[name]["validation"]["model"]["validation_log_loss"],
            PROFILES.index(name),
        ),
    ) if usable else None
    return {
        "selected_on_validation": selected,
        "selected_holdout_status": (
            candidates[selected]["status"] if selected else None
        ),
        "candidates": candidates,
        "split_targets": {name: len(items) for name, items in split.items()},
    }


def build_report() -> dict:
    atp = _scope(fetch_data.get_history("atp"), "main")
    wta = fetch_data._load_tennisdata_couk_multi_year(
        "wta", fetch_data.HISTORY_YEARS_TO_LOAD,
    )
    if wta is None or wta.empty:
        wta = fetch_data.get_history("wta")
    frames = {"atp": atp, "wta": _scope(wta, "main")}
    frames = {
        tour: enrich_tournament_surface_contexts(frame)[0]
        for tour, frame in frames.items()
    }
    rows = {
        tour: build_contextual_h2h_replay_rows(frame)
        for tour, frame in frames.items()
    }
    return {
        "mode": "READ_ONLY_CONTEXTUAL_H2H_EQUATION_COMPARISON",
        "candidate_profiles": list(PROFILES),
        "universes": {
            tour: _comparison(items) for tour, items in rows.items()
        },
        "selection_rule": (
            "minimum validation log loss; holdout reported only after selection"
        ),
        "guards": {
            "same_matches_never_summed_as_global_and_context_votes": True,
            "context_is_bounded_modifier": True,
            "single_h2h_is_shrunk": True,
            "market_used": False,
            "production_effect": False,
            "fair_odd_fitted": False,
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
