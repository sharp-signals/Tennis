"""Compare secondary serve/return equations without production effects."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.replay_recent_form_candidates import _scope, _source_health
from src import fetch_data
from src.contextual_family_calibration import calibrate_family
from src.contextual_family_replay import (
    _split,
    build_contextual_family_replay_rows,
)


PROFILES = (
    "serve_return_surface_points_raw_v0",
    "serve_return_surface_points_shrunk_v1",
    "serve_return_surface_games_shrunk_v1",
    "serve_return_points_recent_deviation_v1",
)


def _comparison(rows: list[dict]) -> dict:
    split = _split(rows)
    candidates = {
        profile: calibrate_family(
            split,
            family="serve_return",
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
            len(usable[name].get("active_coefficients", [])),
            PROFILES.index(name),
        ),
    ) if usable else None
    base = calibrate_family(
        split, family="serve_return", feature_profile="primary_base_for_serve_v1",
    )
    plus = calibrate_family(
        split, family="serve_return", feature_profile="primary_plus_serve_v1",
    )
    plus_surface = calibrate_family(
        split,
        family="serve_return",
        feature_profile="primary_plus_serve_surface_v1",
    )
    base_validation = base.get("validation", {}).get("model", {}).get(
        "validation_log_loss",
    )
    plus_validation = plus.get("validation", {}).get("model", {}).get(
        "validation_log_loss",
    )
    base_holdout = base.get("holdout", {}).get("model", {}).get("log_loss")
    plus_holdout = plus.get("holdout", {}).get("model", {}).get("log_loss")
    incremental_supported = (
        all(value is not None for value in (
            base_validation, plus_validation, base_holdout, plus_holdout,
        ))
        and plus_validation < base_validation
        and plus_holdout < base_holdout
    )
    return {
        "selected_on_validation": selected,
        "selected_holdout_status": (
            candidates[selected]["status"] if selected else None
        ),
        "candidates": candidates,
        "split_targets": {name: len(items) for name, items in split.items()},
        "incremental_after_primary_families": {
            "status": (
                "HOLDOUT_SUPPORTED" if incremental_supported else "NOT_SUPPORTED"
            ),
            "base": base,
            "primary_plus_serve_return": plus,
            "primary_plus_surface_serve_return": plus_surface,
            "validation_log_loss_improvement": (
                round(base_validation - plus_validation, 6)
                if base_validation is not None and plus_validation is not None
                else None
            ),
            "holdout_log_loss_improvement": (
                round(base_holdout - plus_holdout, 6)
                if base_holdout is not None and plus_holdout is not None
                else None
            ),
            "recent_deviation_incremental_holdout": (
                round(
                    plus_surface.get("holdout", {}).get("model", {}).get(
                        "log_loss",
                    ) - plus_holdout,
                    6,
                )
                if (
                    plus_surface.get("holdout", {}).get("model", {}).get(
                        "log_loss",
                    ) is not None and plus_holdout is not None
                ) else None
            ),
        },
    }


def build_report() -> dict:
    frames = {
        "atp": _scope(fetch_data.get_history("atp"), "main"),
        "wta": _scope(fetch_data.get_history("wta"), "main"),
    }
    health = {
        tour: _source_health(frame, universe=tour)
        for tour, frame in frames.items()
    }
    unhealthy = [
        tour for tour, state in health.items()
        if not state["healthy_for_quality_replay"]
    ]
    if unhealthy:
        raise RuntimeError("Fonte histórica inadequada: " + ", ".join(unhealthy))
    rows = {
        tour: build_contextual_family_replay_rows(frame, universe=tour)
        for tour, frame in frames.items()
    }
    return {
        "mode": "READ_ONLY_SERVE_RETURN_EQUATION_COMPARISON",
        "candidate_profiles": list(PROFILES),
        "source_health": health,
        "universes": {
            tour: _comparison(items) for tour, items in rows.items()
        },
        "selection_rule": (
            "minimum validation log loss, then fewer active coefficients; "
            "holdout reported only after selection"
        ),
        "priors_declared_before_replay": {
            "surface_point_sample": 1_000,
            "surface_game_sample": 100,
            "recent_point_sample": 500,
        },
        "guards": {
            "career_is_baseline_recent_is_deviation": True,
            "point_and_game_profiles_are_not_summed": True,
            "secondary_family_only": True,
            "standalone_candidate_prohibited": True,
            "market_used": False,
            "production_effect": False,
            "fair_odd_fitted": False,
        },
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
