"""Pure helpers for a paired, retrospective contextual SHADOW dry-run."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math
from typing import Any, Iterable, Mapping

from .recent_form_replay import _name_key

CURRENT_MODEL_VERSION = "hierarchical-surface-elo-v4.3"


def universe_for_snapshot(snapshot: Mapping[str, Any]) -> str:
    if str(snapshot.get("tier") or "").strip() == "Challenger 125":
        return "challenger"
    return str(snapshot.get("tour") or "").strip().casefold()


def replay_index(rows_by_universe: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for universe, rows in rows_by_universe.items():
        for raw in rows:
            row = dict(raw)
            pair = tuple(sorted((_name_key(row.get("player_a")), _name_key(row.get("player_b")))))
            if not all(pair):
                continue
            index[(str(universe), pair[0], pair[1])].append(row)
    for rows in index.values():
        rows.sort(key=lambda item: str(item["event_date"]))
    return dict(index)


def link_snapshot(
    snapshot: Mapping[str, Any], index: Mapping[tuple[str, str, str], list[dict[str, Any]]],
    *, maximum_days: int = 21,
) -> tuple[dict[str, Any] | None, str]:
    try:
        starts = datetime.fromisoformat(
            str(snapshot["commence_time_utc"]).replace("Z", "+00:00")
        ).date()
    except (KeyError, TypeError, ValueError):
        return None, "INVALID_SNAPSHOT_DATE"
    names = (
        _name_key((snapshot.get("player_a") or {}).get("name")),
        _name_key((snapshot.get("player_b") or {}).get("name")),
    )
    pair = tuple(sorted(names))
    if not all(pair):
        return None, "INVALID_SNAPSHOT_PLAYERS"
    candidates = []
    for row in index.get((universe_for_snapshot(snapshot), pair[0], pair[1]), []):
        try:
            event_date = date.fromisoformat(str(row["event_date"]))
        except ValueError:
            continue
        gap = (starts - event_date).days
        if 0 <= gap <= maximum_days:
            candidates.append((gap, row))
    if not candidates:
        return None, "NO_REPLAY_PAIR_WITHIN_WINDOW"
    minimum = min(gap for gap, _ in candidates)
    nearest = [row for gap, row in candidates if gap == minimum]
    if len(nearest) != 1:
        return None, "AMBIGUOUS_REPLAY_PAIR"
    row = nearest[0]
    winner_side = str((snapshot.get("outcome") or {}).get("winner_side") or "").casefold()
    if winner_side not in {"a", "b"}:
        return None, "OUTCOME_WINNER_SIDE_MISSING"
    winner_name = _name_key((snapshot.get(f"player_{winner_side}") or {}).get("name"))
    if bool(row.get("target_a_win")) != (winner_name == row.get("player_a")):
        return None, "OUTCOME_MISMATCH"
    return row, "LINKED"


def orient_snapshot_probability(snapshot: Mapping[str, Any], key: str) -> float | None:
    pricing = snapshot.get("pricing") if isinstance(snapshot.get("pricing"), Mapping) else {}
    model_a = min(
        _name_key((snapshot.get("player_a") or {}).get("name")),
        _name_key((snapshot.get("player_b") or {}).get("name")),
    )
    provider_a = _name_key((snapshot.get("player_a") or {}).get("name"))
    side = "a" if provider_a == model_a else "b"
    value = pricing.get(f"{key}_{side}")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if 0.0 < value < 1.0 else None


def probability_metrics(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, Any]:
    material = []
    for row in rows:
        try:
            probability = float(row[key])
        except (KeyError, TypeError, ValueError):
            continue
        if 0.0 < probability < 1.0:
            material.append((probability, bool(row["target_a_win"])))
    if not material:
        return {"sample": 0, "log_loss": None, "brier": None, "accuracy_pct": None}
    log_loss = -sum(
        math.log(p if target else 1.0 - p) for p, target in material
    ) / len(material)
    brier = sum((p - float(target)) ** 2 for p, target in material) / len(material)
    accuracy = sum((p >= 0.5) == target for p, target in material) / len(material)
    return {
        "sample": len(material), "log_loss": round(log_loss, 6),
        "brier": round(brier, 6), "accuracy_pct": round(100.0 * accuracy, 2),
        "predicted_mean": round(sum(p for p, _ in material) / len(material), 6),
        "observed_rate": round(sum(target for _, target in material) / len(material), 6),
    }
