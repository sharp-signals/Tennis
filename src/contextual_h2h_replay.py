"""Chronological, market-free replay primitives for contextual H2H evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import re
import unicodedata
from typing import Any, Iterable

import pandas as pd


NON_COMPETITIVE = re.compile(r"\b(?:RET|W/O|WO|DEF|ABD|ABN|CANC)\b", re.I)


def _name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _dates(frame: pd.DataFrame) -> pd.Series:
    for column in ("event_date", "date", "Date", "tourney_date"):
        if column not in frame.columns:
            continue
        raw = frame[column].astype("string").str.strip()
        compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
        return compact.fillna(pd.to_datetime(raw, errors="coerce", utc=True))
    return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")


def _context(row: pd.Series) -> str | None:
    explicit_value = row.get("surface_context")
    if pd.isna(explicit_value):
        explicit_value = row.get("_surface_context")
    explicit = str(explicit_value or "").strip().casefold()
    if explicit in {"hard_outdoor", "hard_indoor", "clay", "grass"}:
        return explicit
    surface = str(row.get("surface") or row.get("Surface") or "").casefold()
    if "clay" in surface:
        return "clay"
    if "grass" in surface:
        return "grass"
    if "hard" not in surface and "carpet" not in surface:
        return None
    indoor = str(row.get("indoor") or row.get("Court") or "").strip().casefold()
    if indoor in {"i", "indoor", "indoors", "true", "1"}:
        return "hard_indoor"
    if indoor in {"o", "outdoor", "outdoors", "false", "0"}:
        return "hard_outdoor"
    return None


def _leader(records: Iterable[dict[str, Any]]) -> str | None:
    a_wins = sum(record["winner_side"] == "a" for record in records)
    b_wins = sum(record["winner_side"] == "b" for record in records)
    if a_wins == b_wins:
        return None
    return "a" if a_wins > b_wins else "b"


def _counts(records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    material = list(records)
    return (
        sum(record["winner_side"] == "a" for record in material),
        sum(record["winner_side"] == "b" for record in material),
    )


def _shrunk_balance(a_wins: int, b_wins: int, *, prior: float = 2.0) -> float:
    return (a_wins - b_wins) / (a_wins + b_wins + prior)


def _context_adjusted_signal(
    baseline: float,
    a_wins: int,
    b_wins: int,
    *,
    prior: float = 2.0,
    max_modifier: float = 0.25,
) -> float:
    sample = a_wins + b_wins
    if sample <= 0:
        return baseline
    contextual = _shrunk_balance(a_wins, b_wins, prior=prior)
    reliability = sample / (sample + prior)
    return baseline + max_modifier * reliability * (contextual - baseline)


def build_contextual_h2h_replay_rows(
    history: pd.DataFrame,
    *,
    recent_days: int = 730,
) -> list[dict[str, Any]]:
    """Evaluate each match before adding any result from the same day.

    A/B are alphabetical normalized identities.  The output intentionally
    contains factual candidates, not a family score or probability.
    """
    if history is None or history.empty:
        return []
    required = {"winner_name", "loser_name"}
    if not required.issubset(history.columns):
        return []

    frame = history.copy()
    frame["_date"] = _dates(frame)
    frame = frame[frame["_date"].notna()].copy()
    if "score" in frame.columns:
        competitive = ~frame["score"].astype("string").fillna("").str.contains(
            NON_COMPETITIVE, na=False,
        )
        frame = frame[competitive].copy()
    frame["_winner_key"] = frame["winner_name"].map(_name)
    frame["_loser_key"] = frame["loser_name"].map(_name)
    frame = frame[
        (frame["_winner_key"] != "")
        & (frame["_loser_key"] != "")
        & (frame["_winner_key"] != frame["_loser_key"])
    ].copy()
    frame["_context"] = frame.apply(_context, axis=1)
    frame["_day"] = frame["_date"].dt.date
    frame = frame.sort_values(["_date", "_winner_key", "_loser_key"])

    prior: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    result: list[dict[str, Any]] = []
    for _, day in frame.groupby("_day", sort=True):
        pending: list[tuple[tuple[str, str], dict[str, Any]]] = []
        for _, row in day.iterrows():
            pair = tuple(sorted((row["_winner_key"], row["_loser_key"])))
            winner_side = "a" if row["_winner_key"] == pair[0] else "b"
            previous = prior[pair]
            cutoff = row["_date"] - timedelta(days=recent_days)
            recent = [item for item in previous if item["date"] >= cutoff]
            same_context = [
                item for item in previous
                if row["_context"] is not None and item["context"] == row["_context"]
            ]
            recent_same_context = [
                item for item in recent
                if row["_context"] is not None and item["context"] == row["_context"]
            ]
            global_leader = _leader(previous)
            context_leader = _leader(same_context)
            recent_context_leader = _leader(recent_same_context)
            prior_a_wins, prior_b_wins = _counts(previous)
            context_a_wins, context_b_wins = _counts(same_context)
            recent_context_a_wins, recent_context_b_wins = _counts(
                recent_same_context,
            )
            global_signal = (
                _shrunk_balance(prior_a_wins, prior_b_wins)
                if previous else None
            )
            result.append({
                "event_date": row["_date"].date().isoformat(),
                "pair_key": "::".join(pair),
                "winner_side": winner_side,
                "surface_context": row["_context"],
                "prior_matches": len(previous),
                "prior_a_wins": prior_a_wins,
                "prior_b_wins": prior_b_wins,
                "prior_leader": global_leader,
                "prior_leader_correct": (
                    global_leader == winner_side if global_leader else None
                ),
                "same_context_matches": len(same_context),
                "same_context_a_wins": context_a_wins,
                "same_context_b_wins": context_b_wins,
                "same_context_leader": context_leader,
                "same_context_leader_correct": (
                    context_leader == winner_side if context_leader else None
                ),
                "recent_matches": len(recent),
                "recent_same_context_matches": len(recent_same_context),
                "recent_same_context_a_wins": recent_context_a_wins,
                "recent_same_context_b_wins": recent_context_b_wins,
                "recent_same_context_leader": recent_context_leader,
                "recent_same_context_leader_correct": (
                    recent_context_leader == winner_side
                    if recent_context_leader else None
                ),
                "target_a_win": winner_side == "a",
                "features": {
                    "contextual_h2h_global_shrunk_v1": global_signal,
                    "contextual_h2h_same_context_modifier_v1": (
                        _context_adjusted_signal(
                            global_signal, context_a_wins, context_b_wins,
                        ) if global_signal is not None else None
                    ),
                    "contextual_h2h_recent_context_modifier_v1": (
                        _context_adjusted_signal(
                            global_signal,
                            recent_context_a_wins,
                            recent_context_b_wins,
                        ) if global_signal is not None else None
                    ),
                },
            })
            pending.append((pair, {
                "date": row["_date"],
                "context": row["_context"],
                "winner_side": winner_side,
            }))
        for pair, record in pending:
            prior[pair].append(record)
    return result


def _accuracy(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [row[field] for row in rows if row.get(field) is not None]
    correct = sum(value is True for value in values)
    return {
        "signals": len(values),
        "correct": correct,
        "accuracy": round(correct / len(values), 6) if values else None,
    }


def summarize_contextual_h2h_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize evidence by pre-declared sample bands."""
    bands = {
        "zero": [row for row in rows if row["prior_matches"] == 0],
        "one": [row for row in rows if row["prior_matches"] == 1],
        "two_to_three": [row for row in rows if 2 <= row["prior_matches"] <= 3],
        "four_plus": [row for row in rows if row["prior_matches"] >= 4],
    }
    return {
        "targets": len(rows),
        "prior_h2h_available": sum(row["prior_matches"] > 0 for row in rows),
        "bands": {
            name: {
                "targets": len(items),
                "global_leader": _accuracy(items, "prior_leader_correct"),
                "same_context_leader": _accuracy(
                    items, "same_context_leader_correct",
                ),
                "recent_same_context_leader": _accuracy(
                    items, "recent_same_context_leader_correct",
                ),
            }
            for name, items in bands.items()
        },
    }
