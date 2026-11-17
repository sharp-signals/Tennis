"""Efficient read-only audit of indoor/outdoor serve-return separation."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path

import numpy as np

from scripts.compare_contextual_family_combinations_v5 import _read_replay
from scripts.replay_recent_form_candidates import _scope
from src import fetch_data
from src.contextual_family_calibration import (
    CALIBRATION_FEATURE_PROFILES,
    _metrics,
    _paired_probability_gain,
    _runtime_model,
    calibrate_family,
    predict_family_equation,
)
from src.contextual_family_replay import (
    _cached_material,
    _metric_margin_shrunk,
    _name_key,
    _recent_metric_deviation,
    _service_exact_context_view,
    _split,
)
from src.contextual_serve_return import _extract_match


BASELINE = "serve_return_points_recent_deviation_v1"
CANDIDATES = (
    "serve_return_exact_context_points_shrunk_v2",
    "serve_return_exact_context_recent_deviation_v2",
    "serve_return_surface_with_exact_context_modifier_v2",
)


def _enrich(rows: list[dict], frame) -> dict[str, int]:
    material = _cached_material(frame)
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_date[str(row["event_date"])].append(row)
    history: dict[str, list[dict]] = defaultdict(list)
    linked = 0
    for event_date, day in material.groupby("_event_date", sort=True):
        date_key = event_date.isoformat()
        for row in by_date.get(date_key, []):
            context = (row.get("diagnostics") or {}).get("surface_context")
            a, a_recent = _service_exact_context_view(
                history[_name_key(row["player_a"])], cutoff=event_date,
                context=context,
            )
            b, b_recent = _service_exact_context_view(
                history[_name_key(row["player_b"])], cutoff=event_date,
                context=context,
            )
            features = row.setdefault("features", {})
            features.update({
                "service_points_won_exact_context_margin_shrunk_v2":
                    _metric_margin_shrunk(
                        a, b, "service_points_won_pct", "service_points_sample",
                        prior_sample=1_000.0,
                    ),
                "return_points_won_exact_context_margin_shrunk_v2":
                    _metric_margin_shrunk(
                        a, b, "return_points_won_pct", "return_points_sample",
                        prior_sample=1_000.0,
                    ),
                "service_points_won_exact_context_recent_deviation_v2":
                    _recent_metric_deviation(
                        a, b, a_recent, b_recent,
                        "service_points_won_pct", "service_points_sample",
                        prior_sample=500.0,
                    ),
                "return_points_won_exact_context_recent_deviation_v2":
                    _recent_metric_deviation(
                        a, b, a_recent, b_recent,
                        "return_points_won_pct", "return_points_sample",
                        prior_sample=500.0,
                    ),
            })
            linked += 1
        for _, match in day.iterrows():
            if bool(match["_non_standard"]):
                continue
            context = match["_surface_context"]
            for player, won in (
                (_name_key(match["_winner"]), True),
                (_name_key(match["_loser"]), False),
            ):
                service = _extract_match(match, player_won=won)
                if player and service is not None:
                    history[player].append({
                        **service,
                        "event_date": event_date,
                        "surface_context": context,
                    })
    return {"rows": len(rows), "linked": linked}


def _audit(rows: list[dict]) -> dict:
    CALIBRATION_FEATURE_PROFILES.update({
        "serve_return_exact_context_points_shrunk_v2": {
            "serve_return": (
                "service_points_won_exact_context_margin_shrunk_v2",
                "return_points_won_exact_context_margin_shrunk_v2",
            ),
        },
        "serve_return_exact_context_recent_deviation_v2": {
            "serve_return": (
                "service_points_won_exact_context_margin_shrunk_v2",
                "return_points_won_exact_context_margin_shrunk_v2",
                "service_points_won_exact_context_recent_deviation_v2",
                "return_points_won_exact_context_recent_deviation_v2",
            ),
        },
        "serve_return_surface_with_exact_context_modifier_v2": {
            "serve_return": (
                "service_points_won_surface_margin_shrunk_v1",
                "return_points_won_surface_margin_shrunk_v1",
                "service_points_won_recent_deviation_v1",
                "return_points_won_recent_deviation_v1",
                "service_points_won_exact_context_margin_shrunk_v2",
                "return_points_won_exact_context_margin_shrunk_v2",
                "service_points_won_exact_context_recent_deviation_v2",
                "return_points_won_exact_context_recent_deviation_v2",
            ),
        },
    })
    split = _split(rows)
    models = {
        profile: calibrate_family(
            split, family="serve_return", feature_profile=profile,
        )
        for profile in (BASELINE, *CANDIDATES)
    }
    holdout = split["holdout"]
    predictions = {
        profile: predict_family_equation(holdout, _runtime_model(model))
        for profile, model in models.items()
    }
    result = {"split_targets": {key: len(value) for key, value in split.items()}}
    for candidate in CANDIDATES:
        wanted = [
            index for index in range(len(holdout))
            if predictions[BASELINE][index] is not None
            and predictions[candidate][index] is not None
        ]
        targets = np.asarray([
            float(holdout[index]["target_a_win"]) for index in wanted
        ])
        baseline = np.asarray([predictions[BASELINE][index] for index in wanted])
        tested = np.asarray([predictions[candidate][index] for index in wanted])
        result[candidate] = {
            "paired_holdout_targets": len(wanted),
            "baseline": _metrics(targets, baseline, total_targets=len(holdout)),
            "candidate": _metrics(targets, tested, total_targets=len(holdout)),
            "paired_gain": _paired_probability_gain(targets, baseline, tested),
            "candidate_coefficients": models[candidate].get("coefficients"),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-input-dir", type=Path, required=True)
    parser.add_argument("--provider-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["TENNISMYLIFE_CACHE_DIR"] = str(args.provider_cache)
    result = {
        "schema_version": 1,
        "mode": "READ_ONLY_EXACT_CONTEXT_SERVE_RETURN_AUDIT",
        "market_used": False,
        "production_effect": False,
        "universes": {},
    }
    for universe in ("atp", "wta"):
        rows = _read_replay(args.replay_input_dir / f"{universe}.jsonl.gz")
        frame = _scope(fetch_data.get_history(universe), "main")
        coverage = _enrich(rows, frame)
        result["universes"][universe] = {
            "enrichment": coverage,
            "audit": _audit(rows),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        universe: value["audit"]
        for universe, value in result["universes"].items()
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
