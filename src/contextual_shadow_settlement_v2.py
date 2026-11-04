"""Settlement and descriptive evaluation for contextual SHADOW v2.

Predictions remain immutable in ``contextual_shadow_observations-v2.jsonl``.
Confirmed outcomes are appended to a separate ledger and can therefore never
rewrite the information that was available before the match.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


OBSERVATIONS_PATH = Path("data/contextual_shadow_observations-v2.jsonl")
OUTCOMES_PATH = Path("data/contextual_shadow_outcomes-v2.jsonl")
EVALUATION_PATH = Path(
    "data/validation/contextual-shadow-v2-evaluation-latest.json"
)
MODEL_VERSION = "contextual-family-shadow-v2"
LINKAGE_WINDOW_SECONDS = 48 * 60 * 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1,
    ):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"invalid row at {path}:{line_number}")
        rows.append(row)
    return rows


def _player_id(match: Mapping[str, Any], side: int) -> Any:
    return match.get(f"player{side}Id") or (
        match.get(f"player{side}") or {}
    ).get("id")


def confirmed_outcome(
    observation: Mapping[str, Any],
    matches: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Resolve one completed result using exact player IDs and nearby time.

    Provider match IDs are intentionally not trusted on their own because they
    can be reused. Ambiguous candidates fail closed.
    """
    players = observation.get("players") or {}
    a_id = (players.get("a") or {}).get("id")
    b_id = (players.get("b") or {}).get("id")
    scheduled = _parse_time(observation.get("commence_time_utc"))
    if a_id in (None, "") or b_id in (None, "") or scheduled is None:
        return None
    wanted = frozenset((str(a_id), str(b_id)))
    candidates: list[tuple[float, Mapping[str, Any]]] = []
    for match in matches:
        if str(match.get("result_type") or "").casefold() not in {
            "completed", "finished",
        }:
            continue
        p1, p2 = _player_id(match, 1), _player_id(match, 2)
        if p1 in (None, "") or p2 in (None, ""):
            continue
        if frozenset((str(p1), str(p2))) != wanted:
            continue
        played = _parse_time(match.get("date"))
        if played is None:
            continue
        delta = abs((played - scheduled).total_seconds())
        if delta <= LINKAGE_WINDOW_SECONDS:
            candidates.append((delta, match))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    if len(candidates) > 1 and math.isclose(
        candidates[0][0], candidates[1][0], abs_tol=1.0,
    ):
        return None
    match = candidates[0][1]
    winner_id = match.get("match_winner")
    if str(winner_id) == str(a_id):
        winner_side = "a"
    elif str(winner_id) == str(b_id):
        winner_side = "b"
    else:
        return None
    observation_id = str(observation.get("observation_id") or "")
    if not observation_id:
        return None
    material = f"{observation_id}|{winner_side}|{match.get('id') or match.get('matchId')}"
    result_text = str(match.get("result") or "")
    is_walkover = any(
        marker in result_text.casefold()
        for marker in ("w/o", "walkover", "walk over")
    )
    return {
        "schema_version": 1,
        "outcome_id": hashlib.sha256(material.encode()).hexdigest()[:32],
        "observation_id": observation_id,
        "canonical_match_instance_id": observation.get(
            "canonical_match_instance_id"
        ),
        "model_version": MODEL_VERSION,
        "configuration_fingerprint": (
            observation.get("contextual_shadow") or {}
        ).get("configuration_fingerprint"),
        "commence_time_utc": observation.get("commence_time_utc"),
        "winner_side": winner_side,
        "winner_id": winner_id,
        "result": match.get("result"),
        "contest_status": "WALKOVER" if is_walkover else "PLAYED",
        "primary_evaluation_eligible": not is_walkover,
        "source": "rapidapi_player_past_matches",
        "source_match_id": match.get("id") or match.get("matchId"),
        "source_match_date_utc": match.get("date"),
        "linkage": "EXACT_PLAYER_IDS_AND_TIME_WINDOW",
        "settled_at_utc": _utc_now(),
    }


def append_outcomes(
    rows: Iterable[Mapping[str, Any]], path: Path = OUTCOMES_PATH,
) -> int:
    """Append outcomes idempotently; contradictory settlement is fatal."""
    existing_rows = read_jsonl(path)
    existing = {
        str(row.get("observation_id") or ""): row for row in existing_rows
        if row.get("observation_id")
    }
    additions = []
    for original in rows:
        row = dict(original)
        key = str(row.get("observation_id") or "")
        side = row.get("winner_side")
        if not key or side not in {"a", "b"}:
            raise ValueError("invalid contextual SHADOW outcome")
        previous = existing.get(key)
        if previous is not None:
            if (
                previous.get("winner_side") != side
                or str(previous.get("winner_id")) != str(row.get("winner_id"))
            ):
                raise ValueError(f"CONFLICTING_SHADOW_OUTCOME:{key}")
            continue
        existing[key] = row
        additions.append(row)
    if additions:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(
                    row, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ) + "\n")
    return len(additions)


def _metric_block(pairs: list[tuple[float, int, float, float]]) -> dict[str, Any]:
    count = len(pairs)
    if not count:
        return {
            "sample_size": 0, "status": "WAITING_FOR_SETTLED_RESULTS",
            "accuracy_pct": None, "brier": None, "log_loss": None,
            "ece_10": None,
        }
    epsilon = 1e-12
    accuracy = sum((probability >= 0.5) == bool(outcome) for probability, outcome, _, _ in pairs) / count
    brier = sum((probability - outcome) ** 2 for probability, outcome, _, _ in pairs) / count
    log_loss = -sum(
        outcome * math.log(min(1 - epsilon, max(epsilon, probability)))
        + (1 - outcome) * math.log(
            min(1 - epsilon, max(epsilon, 1 - probability))
        )
        for probability, outcome, _, _ in pairs
    ) / count
    bins: list[dict[str, Any]] = []
    ece = 0.0
    interval_bins_checked = 0
    interval_bins_consistent = 0
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        selected = [
            pair for pair in pairs
            if low <= pair[0] < high or (index == 9 and pair[0] == 1.0)
        ]
        if not selected:
            continue
        mean_probability = sum(pair[0] for pair in selected) / len(selected)
        observed_rate = sum(pair[1] for pair in selected) / len(selected)
        gap = abs(mean_probability - observed_rate)
        ece += len(selected) / count * gap
        mean_lower = sum(pair[2] for pair in selected) / len(selected)
        mean_upper = sum(pair[3] for pair in selected) / len(selected)
        interval_consistent = None
        if len(selected) >= 10:
            interval_bins_checked += 1
            interval_consistent = mean_lower <= observed_rate <= mean_upper
            interval_bins_consistent += int(interval_consistent)
        bins.append({
            "range": f"{low:.1f}-{high:.1f}",
            "sample_size": len(selected),
            "mean_probability": round(mean_probability, 6),
            "observed_rate": round(observed_rate, 6),
            "absolute_gap": round(gap, 6),
            "mean_probability_interval_90": [
                round(mean_lower, 6), round(mean_upper, 6),
            ],
            "interval_consistent": interval_consistent,
        })
    neutral_log_loss = math.log(2.0)
    return {
        "sample_size": count,
        "status": "DESCRIPTIVE_ONLY_NO_APPROVED_PROMOTION_GATE",
        "accuracy_pct": round(accuracy * 100, 3),
        "mean_probability_a": round(sum(pair[0] for pair in pairs) / count, 6),
        "observed_win_rate_a": round(sum(pair[1] for pair in pairs) / count, 6),
        "brier": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "ece_10": round(ece, 6),
        "neutral_baseline": {
            "brier": 0.25,
            "log_loss": round(neutral_log_loss, 6),
            "brier_improvement": round(0.25 - brier, 6),
            "log_loss_improvement": round(neutral_log_loss - log_loss, 6),
        },
        "probability_interval_diagnostic": {
            "mean_width": round(
                sum(pair[3] - pair[2] for pair in pairs) / count, 6,
            ),
            "bins_with_minimum_10": interval_bins_checked,
            "consistent_bins": interval_bins_consistent,
            "note": (
                "A binary result is not tested as if it were a continuous "
                "value inside the interval; interval calibration is checked "
                "only through empirical rates in bins with n>=10."
            ),
        },
        "calibration_bins": bins,
    }


def build_evaluation(
    observations: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    observations = list(observations)
    observation_by_id = {
        str(row.get("observation_id")): row for row in observations
        if row.get("observation_id")
    }
    outcome_by_observation: dict[str, Mapping[str, Any]] = {}
    settlement_violations: list[dict[str, Any]] = []
    for line_number, row in enumerate(outcomes, start=1):
        key = str(row.get("observation_id") or "")
        observation = observation_by_id.get(key)
        code = None
        if not key or observation is None:
            code = "ORPHAN_OR_MISSING_OBSERVATION_ID"
        elif key in outcome_by_observation:
            code = "DUPLICATE_OUTCOME"
        elif row.get("winner_side") not in {"a", "b"}:
            code = "INVALID_WINNER_SIDE"
        elif row.get("model_version") not in {None, MODEL_VERSION}:
            code = "MODEL_VERSION_MISMATCH"
        elif (
            row.get("configuration_fingerprint")
            != (observation.get("contextual_shadow") or {}).get(
                "configuration_fingerprint"
            )
        ):
            code = "FINGERPRINT_MISMATCH"
        elif (
            row.get("canonical_match_instance_id")
            != observation.get("canonical_match_instance_id")
        ):
            code = "CANONICAL_IDENTITY_MISMATCH"
        if code:
            settlement_violations.append({"line": line_number, "code": code})
            continue
        outcome_by_observation[key] = row
    pairs: list[tuple[Mapping[str, Any], tuple[float, int, float, float]]] = []
    excluded_settled = 0
    excluded_by_reason: dict[str, int] = defaultdict(int)
    for observation in observations:
        outcome = outcome_by_observation.get(str(observation.get("observation_id")))
        if outcome is None:
            continue
        shadow = observation.get("contextual_shadow") or {}
        if shadow.get("status") != "READY_FOR_PROSPECTIVE_SHADOW":
            excluded_settled += 1
            excluded_by_reason["PREDICTION_NOT_READY"] += 1
            continue
        if outcome.get("primary_evaluation_eligible") is False:
            excluded_settled += 1
            excluded_by_reason[str(
                outcome.get("contest_status") or "OUTCOME_INELIGIBLE"
            )] += 1
            continue
        try:
            probability = float(shadow["probability_model_a"])
            lower, upper = map(float, shadow["probability_interval_90_model_a"])
        except (KeyError, TypeError, ValueError):
            excluded_settled += 1
            excluded_by_reason["INVALID_PREDICTION_PROBABILITY"] += 1
            continue
        if outcome.get("winner_side") not in {"a", "b"}:
            excluded_settled += 1
            continue
        pairs.append((observation, (
            probability, int(outcome["winner_side"] == "a"), lower, upper,
        )))

    def grouped(field):
        groups: dict[str, list[tuple[float, int, float, float]]] = defaultdict(list)
        for observation, pair in pairs:
            key = str(field(observation) or "unknown")
            groups[key].append(pair)
        return {key: _metric_block(value) for key, value in sorted(groups.items())}

    ready_total = sum(
        (row.get("contextual_shadow") or {}).get("status")
        == "READY_FOR_PROSPECTIVE_SHADOW"
        for row in observations
    )
    return {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "generated_at_utc": _utc_now(),
        "evaluation_state": (
            "CONTRACT_VIOLATION"
            if settlement_violations
            else "DESCRIPTIVE_ONLY_NO_APPROVED_PROMOTION_GATE"
            if pairs else "WAITING_FOR_SETTLED_RESULTS"
        ),
        "promotion_authorized": False,
        "settlement_audit": {
            "status": (
                "CONTRACT_VIOLATION" if settlement_violations else "HEALTHY"
            ),
            "violations": settlement_violations,
        },
        "market_benchmark": {
            "status": "NOT_AVAILABLE_IN_ISOLATED_SHADOW_LEDGER",
            "note": (
                "Market comparison may only be joined after the prediction "
                "is frozen and only from an independently timestamped source."
            ),
        },
        "counts": {
            "observations": len(observations),
            "ready_observations": ready_total,
            "outcomes": len(outcome_by_observation),
            "ready_settled": len(pairs),
            "ready_pending": max(0, ready_total - len(pairs)),
            "settled_excluded_from_primary_metrics": excluded_settled,
            "settled_excluded_by_reason": dict(sorted(excluded_by_reason.items())),
        },
        "overall": _metric_block([pair for _, pair in pairs]),
        "by_tour": grouped(lambda row: row.get("tour")),
        "by_surface_context": grouped(
            lambda row: (row.get("contextual_shadow") or {}).get("surface_context")
        ),
        "by_quality_group": grouped(
            lambda row: (row.get("contextual_shadow") or {}).get("quality_group")
        ),
    }


def write_evaluation_atomic(document: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

