"""Calibra a escala residual do pricing contra snapshots pré-jogo liquidados.

O corte é estritamente cronológico: a escala é escolhida no bloco inicial e
avaliada no bloco final, que não participa na escolha. O mercado sem margem é
sempre o baseline (escala zero). O script não altera dados nem o modelo.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pricing import (
    PricingParameters,
    _coverage_values,
    _evidence_values,
    evidence_components,
    de_vig_market_probabilities,
)


DEFAULT_SNAPSHOTS = ROOT / "data" / "calibration_snapshots.json"
DEFAULT_TRAIN_FRACTION = 0.70
GRID = tuple(value / 4 for value in range(0, 49))  # 0..12 p.p.; passo 0,25


@dataclass(frozen=True)
class Observation:
    key: str
    analyzed_at: datetime
    segment: str
    market_probability_a: float
    target_a: float
    residual_predictor: float


def _datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _odd(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 1 else None


def _odds(snapshot: Mapping[str, Any]) -> tuple[float, float] | None:
    odds = snapshot.get("market_odds_decimal")
    if not isinstance(odds, Mapping):
        return None
    def player_name(value: Any) -> str:
        if isinstance(value, Mapping):
            return str(value.get("name") or "")
        return str(value or "")

    players = (player_name(snapshot.get("player_a")), player_name(snapshot.get("player_b")))
    found: list[float | None] = []
    for side, player in zip(("a", "b"), players):
        value = _odd(odds.get(f"player_{side}"))
        if value is None:
            for name, candidate in odds.items():
                if str(name).casefold() == player.casefold():
                    value = _odd(candidate)
                    break
        found.append(value)
    if all(value is not None for value in found):
        return float(found[0]), float(found[1])
    numeric = [_odd(value) for value in odds.values()]
    numeric = [value for value in numeric if value is not None]
    return (numeric[0], numeric[1]) if len(numeric) == 2 else None


def _segment(snapshot: Mapping[str, Any]) -> str | None:
    tier = str(snapshot.get("tier") or "").casefold()
    tour = str(snapshot.get("tour") or "").casefold()
    if "challenger" in tier:
        return "challenger"
    if tour == "atp":
        return "atp"
    if tour == "wta":
        return "wta"
    return None


def _quality(divergence: Mapping[str, Any], parameters: PricingParameters) -> tuple[float, float]:
    components = evidence_components(divergence, parameters)
    if not components["coverage_gate_passed"]:
        return float(components["index_a"]), 0.0
    return float(components["index_a"]), float(components["directional_reliability"])


def load_observations(path: Path) -> tuple[list[Observation], dict[str, int]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    snapshots = document.get("snapshots", []) if isinstance(document, Mapping) else []
    exclusions: dict[str, int] = {}
    earliest: dict[str, Observation] = {}
    parameters = PricingParameters()

    def reject(reason: str) -> None:
        exclusions[reason] = exclusions.get(reason, 0) + 1

    first_snapshots: dict[str, Mapping[str, Any]] = {}
    later_snapshots = 0
    for raw in snapshots:
        if not isinstance(raw, Mapping):
            reject("invalid_snapshot")
            continue
        raw_key = str(raw.get("canonical_match_instance_id") or raw.get("event_key") or raw.get("key") or "")
        raw_time = _datetime(raw.get("analyzed_at_utc"))
        if not raw_key or raw_time is None:
            reject("missing_identity_or_analysis_time")
            continue
        current = first_snapshots.get(raw_key)
        if current is None or raw_time < _datetime(current.get("analyzed_at_utc")):
            if current is not None:
                later_snapshots += 1
            first_snapshots[raw_key] = raw
        else:
            later_snapshots += 1

    for snapshot in first_snapshots.values():
        if not isinstance(snapshot, Mapping):
            reject("invalid_snapshot")
            continue
        outcome = snapshot.get("outcome")
        winner = outcome.get("winner_side") if isinstance(outcome, Mapping) else None
        if winner not in {"a", "b"}:
            reject("unsettled")
            continue
        analyzed_at = _datetime(snapshot.get("analyzed_at_utc"))
        if analyzed_at is None:
            reject("missing_analysis_time")
            continue
        commence_time = _datetime(snapshot.get("commence_time_utc"))
        if commence_time is None or analyzed_at >= commence_time:
            reject("not_strictly_pregame")
            continue
        segment = _segment(snapshot)
        if segment is None:
            reject("unsupported_segment")
            continue
        odds = _odds(snapshot)
        if odds is None:
            reject("invalid_two_way_odds")
            continue
        metrics = snapshot.get("metrics")
        divergence = metrics.get("divergencia") if isinstance(metrics, Mapping) else None
        if not isinstance(divergence, Mapping):
            reject("missing_frozen_divergence")
            continue
        index_a, quality = _quality(divergence, parameters)
        try:
            market_a, _, _ = de_vig_market_probabilities(*odds)
        except ValueError:
            reject("invalid_two_way_odds")
            continue
        key = str(
            snapshot.get("canonical_match_instance_id")
            or snapshot.get("event_key")
            or snapshot.get("key")
            or ""
        )
        if not key:
            reject("missing_identity")
            continue
        observation = Observation(
            key=key,
            analyzed_at=analyzed_at,
            segment=segment,
            market_probability_a=market_a,
            target_a=1.0 if winner == "a" else 0.0,
            residual_predictor=((index_a - 50.0) / 50.0) * quality,
        )
        current = earliest.get(key)
        if current is None or observation.analyzed_at < current.analyzed_at:
            earliest[key] = observation

    observations = sorted(earliest.values(), key=lambda item: (item.analyzed_at, item.key))
    exclusions["later_duplicate_snapshots"] = later_snapshots
    return observations, dict(sorted(exclusions.items()))


def _probability(row: Observation, scale_pp: float) -> float:
    result = row.market_probability_a + row.residual_predictor * scale_pp / 100.0
    return min(0.99, max(0.01, result))


def _scores(rows: Iterable[Observation], scale_pp: float) -> dict[str, float | int | None]:
    material = list(rows)
    if not material:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy_pct": None}
    probabilities = [_probability(row, scale_pp) for row in material]
    brier = sum((probability - row.target_a) ** 2 for row, probability in zip(material, probabilities)) / len(material)
    log_loss = -sum(
        row.target_a * math.log(probability) + (1.0 - row.target_a) * math.log(1.0 - probability)
        for row, probability in zip(material, probabilities)
    ) / len(material)
    accuracy = sum((probability >= 0.5) == bool(row.target_a) for row, probability in zip(material, probabilities)) / len(material)
    return {
        "n": len(material),
        "brier": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "accuracy_pct": round(accuracy * 100.0, 2),
    }


def _best_scale(rows: list[Observation]) -> float:
    return min(GRID, key=lambda scale: (_scores(rows, scale)["brier"], scale))


def calibrate_segment(rows: list[Observation], train_fraction: float) -> dict[str, Any]:
    split = max(1, min(len(rows) - 1, int(len(rows) * train_fraction)))
    train, holdout = rows[:split], rows[split:]
    scale = _best_scale(train)
    current_scale = 3.0 if rows and rows[0].segment == "challenger" else 6.0
    sensitivity = []
    for fraction in (0.50, 0.60, 0.70, 0.80):
        sensitivity_split = max(1, min(len(rows) - 1, int(len(rows) * fraction)))
        sensitivity_train = rows[:sensitivity_split]
        sensitivity_holdout = rows[sensitivity_split:]
        sensitivity_scale = _best_scale(sensitivity_train)
        baseline = _scores(sensitivity_holdout, 0.0)
        candidate = _scores(sensitivity_holdout, sensitivity_scale)
        sensitivity.append({
            "train_fraction": fraction,
            "selected_scale_pp": sensitivity_scale,
            "holdout_n": len(sensitivity_holdout),
            "holdout_delta_brier": round(candidate["brier"] - baseline["brier"], 6),
            "holdout_delta_log_loss": round(candidate["log_loss"] - baseline["log_loss"], 6),
        })
    consistently_better = all(
        row["holdout_delta_brier"] < 0 and row["holdout_delta_log_loss"] < 0
        for row in sensitivity
    )
    return {
        "sample": {"total": len(rows), "train": len(train), "holdout": len(holdout)},
        "chronological_cutoff_utc": holdout[0].analyzed_at.isoformat() if holdout else None,
        "selected_scale_pp": scale,
        "train": {
            "market_only": _scores(train, 0.0),
            "selected": _scores(train, scale),
        },
        "holdout": {
            "market_only": _scores(holdout, 0.0),
            "selected": _scores(holdout, scale),
            "provisional_rule": _scores(holdout, current_scale),
        },
        "cutoff_sensitivity": sensitivity,
        "validation_status": "SUPPORTED" if consistently_better else "NOT_SUPPORTED",
        "validated_scale_pp": scale if consistently_better else 0.0,
    }


def build_report(path: Path, train_fraction: float) -> dict[str, Any]:
    observations, exclusions = load_observations(path)
    segments = {
        segment: calibrate_segment([row for row in observations if row.segment == segment], train_fraction)
        for segment in ("atp", "wta", "challenger")
    }
    return {
        "schema_version": 1,
        "method": "chronological_train_holdout_grid_search_brier",
        "source": (
            path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT)
            else str(path)
        ),
        "train_fraction": train_fraction,
        "grid_scale_pp": {"minimum": min(GRID), "maximum": max(GRID), "step": 0.25},
        "deduplication": "earliest analyzed snapshot per canonical match identity",
        "exclusions": exclusions,
        "segments": segments,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--train-fraction", type=float, default=DEFAULT_TRAIN_FRACTION)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0.5 <= args.train_fraction <= 0.9:
        parser.error("--train-fraction deve estar entre 0.5 e 0.9")
    report = build_report(args.snapshots, args.train_fraction)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
