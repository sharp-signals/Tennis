"""Calibra a fair probability independente com snapshots pré-jogo liquidados.

Não usa odds como preditor. O mercado serve apenas para comparação posterior
e para estimar o envelope histórico de discrepância. Deduplica pelo primeiro
snapshot de cada partida, evitando leakage de observações posteriores.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from calibrate_market_residual import DEFAULT_SNAPSHOTS, Observation, load_observations

ROOT = Path(__file__).resolve().parents[1]


def probability(row: Observation, beta: float) -> float:
    z = max(-20.0, min(20.0, beta * row.residual_predictor))
    return 1.0 / (1.0 + math.exp(-z))


def fit_beta(rows: list[Observation]) -> tuple[float, float]:
    beta = 0.0
    information = 0.0
    for _ in range(100):
        gradient = 0.0
        information = 0.0
        for row in rows:
            predicted = probability(row, beta)
            gradient += row.residual_predictor * (row.target_a - predicted)
            information += row.residual_predictor ** 2 * predicted * (1.0 - predicted)
        updated = beta + gradient / max(information, 1e-12)
        if abs(updated - beta) < 1e-10:
            beta = updated
            break
        beta = updated
    return beta, math.sqrt(1.0 / max(information, 1e-12))


def scores(rows: list[Observation], beta: float) -> dict[str, float | int]:
    predicted = [probability(row, beta) for row in rows]
    brier = sum((p - row.target_a) ** 2 for row, p in zip(rows, predicted)) / len(rows)
    return {"n": len(rows), "brier": round(brier, 6)}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position)); upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def calibrate(rows: list[Observation]) -> dict[str, Any]:
    beta, standard_error = fit_beta(rows)
    low = max(0.0, beta - 1.96 * standard_error)
    high = beta + 1.96 * standard_error
    gaps = [abs(probability(row, beta) - row.market_probability_a) * 100.0 for row in rows]
    sensitivity = []
    for fraction in (0.50, 0.60, 0.70, 0.80):
        split = max(1, min(len(rows) - 1, int(len(rows) * fraction)))
        train, holdout = rows[:split], rows[split:]
        fitted, _ = fit_beta(train)
        sensitivity.append({
            "train_fraction": fraction,
            "train_beta": round(fitted, 6),
            "holdout": scores(holdout, fitted),
            "holdout_neutral": scores(holdout, 0.0),
        })
    return {
        "n": len(rows),
        "beta": round(beta, 6),
        "standard_error": round(standard_error, 6),
        "beta_ci95": [round(low, 6), round(high, 6)],
        "maximum_quality_probability": round(probability(Observation("", rows[0].analyzed_at, rows[0].segment, .5, 1, 1), beta), 6),
        "market_gap_pp": {
            "p90": round(percentile(gaps, .90), 2),
            "p95": round(percentile(gaps, .95), 2),
        },
        "chronological_sensitivity": sensitivity,
    }


def build_report(path: Path) -> dict[str, Any]:
    observations, exclusions = load_observations(path)
    segments = {
        segment: calibrate([row for row in observations if row.segment == segment])
        for segment in ("atp", "wta", "challenger")
    }
    pooled = calibrate(observations)
    return {
        "schema_version": 2,
        "model": "factor-calibrated-v2",
        "source": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
        "deduplication": "earliest pre-match snapshot per canonical match identity",
        "predictor": "signed_index_strength_x_evidence_quality",
        "market_role": "comparison_and_out_of_distribution_check_only",
        "exclusions": exclusions,
        "pooled": pooled,
        "segments": segments,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.snapshots)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
