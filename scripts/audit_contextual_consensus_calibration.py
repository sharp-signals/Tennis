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
)
from src.contextual_family_combination_v2 import FAMILY_ORDER
from src.contextual_family_combination_v8 import predict_contextual_combination_v8
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
    observed = sum(item["favorite_won"] for item in values) / sample
    return {
        "sample": sample,
        "predicted_pct": round(100.0 * predicted, 2),
        "observed_pct": round(100.0 * observed, 2),
        "gap_pp": round(100.0 * (observed - predicted), 2),
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
        raw_logit = _logit(raw_probability)
        for family in FAMILY_ORDER:
            family_probability = family_probabilities.get(family)
            if family_probability is None:
                continue
            directions[family] = (
                "a" if float(family_probability) > 0.5
                else "b" if float(family_probability) < 0.5 else "neutral"
            )
            contribution = float(coefficients.get(family, 0.0)) * _logit(
                family_probability
            )
            without = _apply_calibrator(
                _sigmoid(raw_logit - contribution), calibrator,
            )
            intensities[family] = _intensity(
                100.0 * (probability_a - without)
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
        records.append({
            "favorite_probability": favorite_probability,
            "favorite_won": target_a if favorite_side == "a" else not target_a,
            "fair_band": _fair_band(favorite_probability),
            "active_families": len(active),
            "aligned_families": aligned,
            "consensus": f"{aligned}/{len(active)}" if active else "0/0",
            "primary_aligned": primary_aligned,
            "strongest_primary_intensity": strongest_primary,
        })
    return records


def _grouped(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record[key])].append(record)
    return {name: _segment(rows) for name, rows in sorted(groups.items())}


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
    prediction = predict_contextual_combination_v8(
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
    return {
        "holdout": {
            "from": chronology["holdout_from"],
            "through": chronology["evaluation_through"],
            "sample": len(records),
        },
        "overall": _segment(records),
        "fair_odd_bands": _grouped(records, "fair_band"),
        "family_consensus": _grouped(records, "consensus"),
        "primary_alignment": {
            "both_primary_aligned": _segment(
                row for row in records if row["primary_aligned"]
            ),
            "not_both_primary_aligned": _segment(
                row for row in records if not row["primary_aligned"]
            ),
        },
        "unanimous_5_of_5": _segment(unanimous),
        "unanimous_primary_intensity": _grouped(
            unanimous, "strongest_primary_intensity",
        ),
    }


def _load_rows(universe: str, replay_input_dir: Path | None) -> list[dict[str, Any]]:
    cache = replay_input_dir / f"{universe}.jsonl.gz" if replay_input_dir else None
    if cache is not None and cache.is_file():
        rows = _read_replay(cache)
    else:
        history = _history(universe)
        rows = build_contextual_family_replay_rows(
            enrich_tournament_surface_contexts(history)[0],
            universe=universe, target_scope="main",
        )
    _augment_pooled_main_features(rows)
    return rows


def build_audit(release: dict[str, Any], replay_input_dir: Path | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "READ_ONLY_CHRONOLOGICAL_CALIBRATION_AUDIT",
        "model_version": release["global_release_id"],
        "configuration_fingerprint": release["configuration_fingerprint"],
        "market_used": False,
        "model_refit": False,
        "results": {
            universe: audit_universe(
                _load_rows(universe, replay_input_dir),
                universe=universe, release=release,
            )
            for universe in ("atp", "wta")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--replay-input-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    release = json.loads(args.model.read_text(encoding="utf-8"))
    audit = build_audit(release, args.replay_input_dir)
    encoded = json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
