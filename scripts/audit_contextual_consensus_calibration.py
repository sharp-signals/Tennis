"""Read-only chronological calibration audit by family consensus and fair-odd band.

This audit never refits the model and never reads market prices.  It checks
whether the frozen contextual release is systematically under/over-confident
when several families point to the same player.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare_contextual_family_combinations_v5 import (
    _augment_pooled_main_features,
    _history,
    _read_replay,
    _write_replay,
)
from src.contextual_family_combination_v2 import FAMILY_ORDER
from src.contextual_family_combination_v18 import predict_contextual_combination_v18
from src.contextual_family_replay import build_contextual_family_replay_rows
from src.contextual_probability_uncertainty_v2 import _apply_calibrator
from src.contextual_tournament_surface_registry import enrich_tournament_surface_contexts


DEFAULT_MODEL = Path("data/models/fenzobot-contextual-2026-11.json")


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(value)))


def _fair_band(probability: float) -> str:
    odd = 1.0 / max(float(probability), 1e-9)
    if odd <= 1.25:
        return "1.10-1.25"
    if odd <= 1.40:
        return "1.26-1.40"
    if odd <= 1.60:
        return "1.41-1.60"
    if odd <= 1.80:
        return "1.61-1.80"
    return ">1.80"


def _probability_band(probability: float) -> str:
    value = 100.0 * float(probability)
    if value < 55.0:
        return "50-55%"
    if value < 60.0:
        return "55-60%"
    if value < 70.0:
        return "60-70%"
    if value < 80.0:
        return "70-80%"
    if value < 90.0:
        return "80-90%"
    return "90-100%"


def _rank_band(rank: float | None) -> str:
    if rank is None or not math.isfinite(float(rank)) or float(rank) <= 0:
        return "unknown"
    value = float(rank)
    if value <= 2:
        return "top_2"
    if value <= 3:
        return "rank_3"
    if value <= 10:
        return "rank_4_10"
    if value <= 20:
        return "rank_11_20"
    if value <= 50:
        return "rank_21_50"
    if value <= 100:
        return "rank_51_100"
    return "rank_101_plus"


def _rank_gap_band(rank_a: float | None, rank_b: float | None) -> str:
    if rank_a is None or rank_b is None:
        return "unknown"
    gap = abs(float(rank_a) - float(rank_b))
    if gap < 6:
        return "0-5"
    if gap < 16:
        return "6-15"
    if gap < 31:
        return "16-30"
    if gap < 61:
        return "31-60"
    return "61+"


def _wilson(successes: int, sample: int) -> list[float | None]:
    if sample <= 0:
        return [None, None]
    z = 1.959963984540054
    rate = successes / sample
    denominator = 1.0 + z * z / sample
    centre = (rate + z * z / (2.0 * sample)) / denominator
    margin = z * math.sqrt(
        rate * (1.0 - rate) / sample + z * z / (4.0 * sample * sample)
    ) / denominator
    return [round(100.0 * (centre - margin), 2),
            round(100.0 * (centre + margin), 2)]


def _intensity(delta_pp: float) -> str:
    value = abs(float(delta_pp))
    if value < 3.0:
        return "SLIGHT"
    if value < 7.0:
        return "MODERATE"
    if value < 12.0:
        return "STRONG"
    return "DECISIVE"


def _segment(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    sample = len(values)
    if not sample:
        return {"sample": 0, "predicted_pct": None, "observed_pct": None,
                "gap_pp": None}
    predicted = sum(item["favorite_probability"] for item in values) / sample
    successes = sum(bool(item["favorite_won"]) for item in values)
    observed = successes / sample
    return {
        "sample": sample,
        "wins": successes,
        "predicted_pct": round(100.0 * predicted, 2),
        "observed_pct": round(100.0 * observed, 2),
        "gap_pp": round(100.0 * (observed - predicted), 2),
        "observed_wilson_95_pct": _wilson(successes, sample),
        "minimum_diagnostic_sample_met": sample >= 30,
    }


def _stage_trace(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    if not values:
        return {"sample": 0}

    def mean(key: str) -> float:
        return sum(float(row[key]) for row in values) / len(values)

    below_1_60 = sum(
        float(row["favorite_probability"]) <= 0.625 for row in values
    )
    return {
        "sample": len(values),
        "mean_pre_slope_probability_pct": round(
            100.0 * mean("pre_slope_favorite_probability"), 2,
        ),
        "mean_post_slope_probability_pct": round(
            100.0 * mean("combination_favorite_probability"), 2,
        ),
        "mean_final_probability_pct": round(
            100.0 * mean("favorite_probability"), 2,
        ),
        "mean_final_fair_odd": round(mean("favorite_fair_odd"), 3),
        "mean_primary_logit_contribution": round(
            mean("primary_logit_contribution"), 6,
        ),
        "mean_secondary_logit_contribution": round(
            mean("secondary_logit_contribution"), 6,
        ),
        "final_probability_le_62_5_count": below_1_60,
        "final_probability_le_62_5_pct": round(
            100.0 * below_1_60 / len(values), 2,
        ),
        "mean_final_calibration_shift_pp": round(
            mean("final_calibration_shift_pp"), 3,
        ),
    }


def _stage_grouped(
    records: list[dict[str, Any]], key: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record[key])].append(record)
    return {name: _stage_trace(rows) for name, rows in sorted(groups.items())}


def _within_wilson(segment: dict[str, Any]) -> bool | None:
    if int(segment.get("sample") or 0) < 30:
        return None
    interval = segment.get("observed_wilson_95_pct")
    predicted = segment.get("predicted_pct")
    if not interval or predicted is None:
        return None
    return float(interval[0]) <= float(predicted) <= float(interval[1])


def _certification(
    *, overall: dict[str, Any], primary: dict[str, Any],
    unanimous: dict[str, Any], intensity: dict[str, Any],
    coefficients: dict[str, float],
) -> dict[str, Any]:
    primary_names = ("recent_form", "structural_strength")
    secondary_names = ("surface_conditions", "matchup_h2h", "serve_return")
    primary_values = [abs(float(coefficients[name])) for name in primary_names]
    secondary_values = [abs(float(coefficients[name])) for name in secondary_names]
    ordered = [
        intensity.get(name) for name in ("SLIGHT", "MODERATE", "STRONG", "DECISIVE")
        if int((intensity.get(name) or {}).get("sample") or 0) >= 30
    ]
    monotonic = all(
        float(left["predicted_pct"]) <= float(right["predicted_pct"]) + 1e-9
        for left, right in zip(ordered, ordered[1:])
    )
    segment_checks = {
        name: _within_wilson(value)
        for name, value in intensity.items()
        if int(value.get("sample") or 0) >= 30
    }
    gates = {
        "each_primary_coefficient_above_each_secondary": (
            min(primary_values) > max(secondary_values)
        ),
        "primary_coefficient_block_above_secondary_block": (
            sum(primary_values) > sum(secondary_values)
        ),
        "overall_prediction_inside_observed_wilson_95": _within_wilson(overall),
        "both_primary_aligned_inside_observed_wilson_95": _within_wilson(
            primary["both_primary_aligned"]
        ),
        "unanimous_5_of_5_inside_observed_wilson_95": _within_wilson(unanimous),
        "unanimous_predicted_probability_rises_with_primary_intensity": monotonic,
        "unanimous_intensity_segments_inside_observed_wilson_95": all(
            value is not False for value in segment_checks.values()
        ),
    }
    return {
        "status": (
            "PASSED" if all(value is True for value in gates.values())
            else "FAILED"
        ),
        "gates": gates,
        "unanimous_intensity_segment_checks": segment_checks,
        "scope": (
            "historical calibration and hierarchy certification; individual "
            "match prices still require regression and traceability checks"
        ),
    }


def _rank_segment(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = [row for row in rows if row.get("rank_favorite_probability") is not None]
    sample = len(values)
    if not sample:
        return {"sample": 0, "predicted_pct": None, "observed_pct": None,
                "gap_pp": None}
    successes = sum(bool(row["rank_favorite_won"]) for row in values)
    predicted = sum(float(row["rank_favorite_probability"]) for row in values) / sample
    observed = successes / sample
    return {
        "sample": sample,
        "wins": successes,
        "predicted_pct": round(100.0 * predicted, 2),
        "observed_pct": round(100.0 * observed, 2),
        "gap_pp": round(100.0 * (observed - predicted), 2),
        "observed_wilson_95_pct": _wilson(successes, sample),
        "minimum_diagnostic_sample_met": sample >= 30,
    }


def _audit_records(
    rows: list[dict[str, Any]], probabilities: list[float], *,
    coefficients: dict[str, float], calibrator: dict[str, Any],
) -> list[dict[str, Any]]:
    records = []
    for row, raw_probability in zip(rows, probabilities):
        probability_a = _apply_calibrator(raw_probability, calibrator)
        favorite_side = "a" if probability_a >= 0.5 else "b"
        favorite_probability = max(probability_a, 1.0 - probability_a)
        family_probabilities = row.get("family_probabilities") or {}
        directions = {}
        intensities = {}
        calibrated_contributions = row.get(
            "calibrated_realized_family_contributions"
        ) or {}
        realized_contributions = row.get("realized_family_contributions") or {}
        pre_slope_probability_a = _sigmoid(sum(
            float(realized_contributions.get(family, 0.0))
            for family in FAMILY_ORDER
        ))
        final_logit = _logit(raw_probability)
        family_probability_for_favorite = {}
        family_contribution_for_favorite = {}
        for family in FAMILY_ORDER:
            family_probability = family_probabilities.get(family)
            if family_probability is None:
                continue
            directions[family] = (
                "a" if float(family_probability) > 0.5
                else "b" if float(family_probability) < 0.5 else "neutral"
            )
            contribution = float(calibrated_contributions.get(family, 0.0))
            without = _apply_calibrator(
                _sigmoid(final_logit - contribution), calibrator,
            )
            intensities[family] = _intensity(
                100.0 * (probability_a - without)
            )
            family_probability_for_favorite[family] = round(
                float(family_probability)
                if favorite_side == "a" else 1.0 - float(family_probability),
                8,
            )
            family_contribution_for_favorite[family] = round(
                contribution if favorite_side == "a" else -contribution, 8,
            )
        active = [value for value in directions.values() if value != "neutral"]
        aligned = sum(value == favorite_side for value in active)
        primary_aligned = all(
            directions.get(family) == favorite_side
            for family in ("recent_form", "structural_strength")
        )
        primary_intensities = [
            intensities.get(family) for family in ("recent_form", "structural_strength")
            if directions.get(family) == favorite_side
        ]
        strongest_primary = next(
            (label for label in ("DECISIVE", "STRONG", "MODERATE", "SLIGHT")
             if label in primary_intensities),
            "NONE",
        )
        target_a = bool(row.get("target_a_win"))
        diagnostics = row.get("diagnostics") or {}
        rank_a = diagnostics.get("rank_a")
        rank_b = diagnostics.get("rank_b")
        rank_favorite_side = None
        if rank_a is not None and rank_b is not None and float(rank_a) != float(rank_b):
            rank_favorite_side = "a" if float(rank_a) < float(rank_b) else "b"
        rank_favorite_probability = (
            None if rank_favorite_side is None else
            probability_a if rank_favorite_side == "a" else 1.0 - probability_a
        )
        rank_favorite_won = (
            None if rank_favorite_side is None else
            target_a if rank_favorite_side == "a" else not target_a
        )
        records.append({
            "favorite_probability": favorite_probability,
            "favorite_won": target_a if favorite_side == "a" else not target_a,
            "pre_slope_favorite_probability": (
                pre_slope_probability_a
                if favorite_side == "a" else 1.0 - pre_slope_probability_a
            ),
            "combination_favorite_probability": (
                raw_probability if favorite_side == "a" else 1.0 - raw_probability
            ),
            "favorite_fair_odd": 1.0 / favorite_probability,
            "primary_logit_contribution": sum(
                family_contribution_for_favorite.get(family, 0.0)
                for family in ("recent_form", "structural_strength")
            ),
            "secondary_logit_contribution": sum(
                family_contribution_for_favorite.get(family, 0.0)
                for family in ("surface_conditions", "matchup_h2h", "serve_return")
            ),
            "final_calibration_shift_pp": 100.0 * (
                favorite_probability
                - (raw_probability if favorite_side == "a" else 1.0 - raw_probability)
            ),
            "fair_band": _fair_band(favorite_probability),
            "probability_band": _probability_band(favorite_probability),
            "active_families": len(active),
            "aligned_families": aligned,
            "consensus": f"{aligned}/{len(active)}" if active else "0/0",
            "primary_aligned": primary_aligned,
            "strongest_primary_intensity": strongest_primary,
            "family_probability_for_favorite": family_probability_for_favorite,
            "family_contribution_for_favorite": family_contribution_for_favorite,
            "surface_context": diagnostics.get("surface_context") or "unknown",
            "target_tier": diagnostics.get("target_tier") or "unknown",
            "rank_favorite_side": rank_favorite_side,
            "rank_favorite_probability": rank_favorite_probability,
            "rank_favorite_won": rank_favorite_won,
            "model_agrees_with_rank": (
                None if rank_favorite_side is None else
                favorite_side == rank_favorite_side
            ),
            "better_rank_band": (
                "unknown" if rank_favorite_side is None else
                _rank_band(rank_a if rank_favorite_side == "a" else rank_b)
            ),
            "rank_gap_band": _rank_gap_band(rank_a, rank_b),
            "primary_alignment_label": (
                "both_primary_aligned"
                if primary_aligned else "primary_split_or_neutral"
            ),
            "consensus_label": (
                "unanimous_5_of_5"
                if len(active) == 5 and aligned == 5 else "not_unanimous"
            ),
        })
    return records


def _grouped(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record[key])].append(record)
    return {name: _segment(rows) for name, rows in sorted(groups.items())}


def _rank_grouped(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record[key])].append(record)
    return {name: _rank_segment(rows) for name, rows in sorted(groups.items())}


def _cross_grouped(
    records: list[dict[str, Any]],
    left_key: str,
    right_key: str,
    *,
    ranking_favorite: bool = False,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[f"{record[left_key]} | {record[right_key]}"].append(record)
    summarize = _rank_segment if ranking_favorite else _segment
    return {name: summarize(rows) for name, rows in sorted(groups.items())}


def _family_stage_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"sample": 0, "families": {}}
    return {
        "sample": len(records),
        "families": {
            family: {
                "mean_family_probability_for_final_favorite_pct": round(
                    100.0 * sum(
                        row["family_probability_for_favorite"].get(family, 0.5)
                        for row in records
                    ) / len(records), 2,
                ),
                "mean_final_logit_contribution_for_favorite": round(
                    sum(
                        row["family_contribution_for_favorite"].get(family, 0.0)
                        for row in records
                    ) / len(records), 6,
                ),
            }
            for family in FAMILY_ORDER
        },
    }


def audit_universe(
    replay_rows: list[dict[str, Any]], *, universe: str,
    release: dict[str, Any],
) -> dict[str, Any]:
    universe_model = release["universes"][universe]
    combination = universe_model["combination"]
    chronology = combination["chronology"]
    holdout = [
        row for row in replay_rows
        if str(chronology["holdout_from"]) <= str(row["event_date"])
        <= str(chronology["evaluation_through"])
    ]
    if len(holdout) != int(chronology["holdout_targets"]):
        raise ValueError(f"{universe}: frozen holdout cannot be reproduced")
    combination_contract = {
        "model_version": release["components"]["family_combination"],
        "mode": "SHADOW_ONLY",
        "market_used": False,
        "production_effect": False,
        "promotion_authorized": False,
        "universes": {universe: combination},
    }
    prediction = predict_contextual_combination_v18(
        holdout, universe=universe, contract=combination_contract,
    )
    records = _audit_records(
        prediction["rows"], prediction["probabilities"],
        coefficients=combination["family_coefficients"],
        calibrator=universe_model["calibration"]["central_calibrator"],
    )
    unanimous = [
        row for row in records
        if row["active_families"] == 5 and row["aligned_families"] == 5
    ]
    overall = _segment(records)
    primary_alignment = {
        "both_primary_aligned": _segment(
            row for row in records if row["primary_aligned"]
        ),
        "not_both_primary_aligned": _segment(
            row for row in records if not row["primary_aligned"]
        ),
    }
    unanimous_segment = _segment(unanimous)
    unanimous_intensity = _grouped(
        unanimous, "strongest_primary_intensity",
    )
    return {
        "holdout": {
            "from": chronology["holdout_from"],
            "through": chronology["evaluation_through"],
            "sample": len(records),
        },
        "overall": overall,
        "probability_bands": _grouped(records, "probability_band"),
        "fair_odd_bands": _grouped(records, "fair_band"),
        "surface_context": _grouped(records, "surface_context"),
        "tournament_tier": _grouped(records, "target_tier"),
        "family_consensus": _grouped(records, "consensus"),
        "primary_alignment": primary_alignment,
        "unanimous_5_of_5": unanimous_segment,
        "unanimous_5_of_5_family_stage": _family_stage_summary(unanimous),
        "unanimous_primary_intensity": unanimous_intensity,
        "unanimous_5_of_5_probability_trace": _stage_trace(unanimous),
        "unanimous_probability_trace_by_primary_intensity": _stage_grouped(
            unanimous, "strongest_primary_intensity",
        ),
        "certification": _certification(
            overall=overall,
            primary=primary_alignment,
            unanimous=unanimous_segment,
            intensity=unanimous_intensity,
            coefficients=combination["family_coefficients"],
        ),
        "ranking_favorite": {
            "overall": _rank_segment(records),
            "when_model_agrees": _rank_segment(
                row for row in records if row["model_agrees_with_rank"] is True
            ),
            "when_model_disagrees": _rank_segment(
                row for row in records if row["model_agrees_with_rank"] is False
            ),
            "by_better_rank_band": _rank_grouped(records, "better_rank_band"),
            "by_rank_gap": _rank_grouped(records, "rank_gap_band"),
        },
        "intersections": {
            "probability_by_surface": _cross_grouped(
                records, "probability_band", "surface_context",
            ),
            "probability_by_tournament_tier": _cross_grouped(
                records, "probability_band", "target_tier",
            ),
            "probability_by_primary_alignment": _cross_grouped(
                records, "probability_band", "primary_alignment_label",
            ),
            "probability_by_consensus": _cross_grouped(
                records, "probability_band", "consensus_label",
            ),
            "ranking_band_by_rank_gap": _cross_grouped(
                records, "better_rank_band", "rank_gap_band",
                ranking_favorite=True,
            ),
            "ranking_band_by_surface": _cross_grouped(
                records, "better_rank_band", "surface_context",
                ranking_favorite=True,
            ),
        },
    }


def _load_rows(
    universe: str,
    replay_input_dir: Path | None,
    replay_cache_dir: Path | None,
) -> list[dict[str, Any]]:
    cache = replay_input_dir / f"{universe}.jsonl.gz" if replay_input_dir else None
    if cache is not None and cache.is_file():
        rows = _read_replay(cache)
    else:
        history = _history(universe)
        rows = build_contextual_family_replay_rows(
            enrich_tournament_surface_contexts(history)[0],
            universe=universe, target_scope="main",
        )
        if replay_cache_dir is not None:
            replay_cache_dir.mkdir(parents=True, exist_ok=True)
            _write_replay(replay_cache_dir / f"{universe}.jsonl.gz", rows)
    _augment_pooled_main_features(rows)
    return rows


def build_audit(
    release: dict[str, Any],
    replay_input_dir: Path | None,
    replay_cache_dir: Path | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "mode": "READ_ONLY_CHRONOLOGICAL_CALIBRATION_AUDIT",
        "model_version": release["global_release_id"],
        "configuration_fingerprint": release["configuration_fingerprint"],
        "market_used": False,
        "model_refit": False,
        "results": {
            universe: audit_universe(
                _load_rows(universe, replay_input_dir, replay_cache_dir),
                universe=universe, release=release,
            )
            for universe in ("atp", "wta")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--replay-input-dir", type=Path)
    parser.add_argument("--replay-cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    release = json.loads(args.model.read_text(encoding="utf-8"))
    audit = build_audit(release, args.replay_input_dir, args.replay_cache_dir)
    encoded = json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
