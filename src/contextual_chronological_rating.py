"""Leakage-safe chronological ratings for isolated contextual experiments."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
import re
from threading import RLock
import unicodedata
from typing import Any

import pandas as pd

from .contextual_surface_ledger import exact_surface_context


SURFACE_K = 32
SURFACE_SHRINK_MATCHES = 10.0
_CACHE: dict[tuple[str, str, int, int], dict[str, Any]] = {}
_LOCK = RLock()


def _name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _expected(a: float, b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def _indoor_value(value: Any) -> bool | None:
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "indoor"}:
        return True
    if text in {"false", "0", "no", "outdoor"}:
        return False
    return None


def _snapshot(history: pd.DataFrame, *, cutoff: date, global_k: int) -> dict[str, Any]:
    key = (str(cutoff), str(global_k), len(history), id(history))
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

    required = {"tourney_date", "winner_name", "loser_name", "surface"}
    if history.empty or not required.issubset(history.columns):
        return {"global": {}, "surface": {}, "surface_count": {}}
    material = history.copy()
    material["_event_date"] = pd.to_datetime(
        material["tourney_date"], format="%Y%m%d", errors="coerce",
    ).dt.date
    material = material[
        material["_event_date"].notna() & (material["_event_date"] < cutoff)
    ].sort_values("_event_date", kind="stable")
    global_rating: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    surface_rating: defaultdict[tuple[str, str], float] = defaultdict(lambda: 1500.0)
    surface_count: defaultdict[tuple[str, str], int] = defaultdict(int)
    for _, day in material.groupby("_event_date", sort=True):
        global_updates = []
        surface_updates = []
        for row in day.to_dict("records"):
            winner, loser = _name(row.get("winner_name")), _name(row.get("loser_name"))
            if not winner or not loser or winner == loser:
                continue
            winner_rating = float(global_rating[winner])
            loser_rating = float(global_rating[loser])
            delta = global_k * (1.0 - _expected(winner_rating, loser_rating))
            global_updates.append((winner, loser, delta))
            context = exact_surface_context(
                row.get("surface"), indoor=_indoor_value(row.get("indoor")),
            )
            if context:
                winner_key, loser_key = (winner, context), (loser, context)
                winner_surface = float(surface_rating[winner_key])
                loser_surface = float(surface_rating[loser_key])
                surface_delta = SURFACE_K * (
                    1.0 - _expected(winner_surface, loser_surface)
                )
                surface_updates.append((winner_key, loser_key, surface_delta))
        for winner, loser, delta in global_updates:
            global_rating[winner] += delta
            global_rating[loser] -= delta
        for winner_key, loser_key, delta in surface_updates:
            surface_rating[winner_key] += delta
            surface_rating[loser_key] -= delta
            surface_count[winner_key] += 1
            surface_count[loser_key] += 1
    result = {
        "global": dict(global_rating),
        "surface": dict(surface_rating),
        "surface_count": dict(surface_count),
    }
    with _LOCK:
        _CACHE[key] = result
    return result


def build_rating_features(
    history: pd.DataFrame, *, universe: str, cutoff: date,
    player_a: str, player_b: str, surface_context: str | None,
) -> dict[str, float | None]:
    """Return only pre-match, market-free features used by frozen A/B models."""
    universe = str(universe).casefold()
    global_k = 32 if universe == "atp" else 24
    snapshot = _snapshot(history, cutoff=cutoff, global_k=global_k)
    a, b = _name(player_a), _name(player_b)
    rating_a = float(snapshot["global"].get(a, 1500.0))
    rating_b = float(snapshot["global"].get(b, 1500.0))
    result: dict[str, float | None] = {
        f"chronological_elo_margin_k{global_k}": (rating_a - rating_b) / 400.0,
    }
    if universe != "wta":
        return result
    if not surface_context:
        result["surface_elo_residual_k32"] = None
        return result
    key_a, key_b = (a, surface_context), (b, surface_context)
    surface_a = float(snapshot["surface"].get(key_a, 1500.0))
    surface_b = float(snapshot["surface"].get(key_b, 1500.0))
    count_a = int(snapshot["surface_count"].get(key_a, 0))
    count_b = int(snapshot["surface_count"].get(key_b, 0))
    weight_a = count_a / (count_a + SURFACE_SHRINK_MATCHES)
    weight_b = count_b / (count_b + SURFACE_SHRINK_MATCHES)
    shrunk_a = rating_a + weight_a * (surface_a - rating_a)
    shrunk_b = rating_b + weight_b * (surface_b - rating_b)
    result["surface_elo_residual_k32"] = (
        (shrunk_a - shrunk_b) - (rating_a - rating_b)
    ) / 400.0
    return result


def augment_replay_rows_with_ratings(
    rows: list[dict[str, Any]], *, universe: str,
) -> list[dict[str, Any]]:
    """Add the same leakage-safe ratings to an already chronological replay."""
    universe = str(universe).casefold()
    global_k = 32 if universe == "atp" else 24
    global_rating: defaultdict[str, float] = defaultdict(lambda: 1500.0)
    surface_rating: defaultdict[tuple[str, str], float] = defaultdict(
        lambda: 1500.0,
    )
    surface_count: defaultdict[tuple[str, str], int] = defaultdict(int)
    grouped: defaultdict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[str(row["event_date"])].append((index, row))
    additions: dict[int, dict[str, float | None]] = {}

    for event_date in sorted(grouped):
        global_updates = []
        surface_updates = []
        for index, row in grouped[event_date]:
            player_a, player_b = _name(row["player_a"]), _name(row["player_b"])
            outcome = 1.0 if row["target_a_win"] else 0.0
            rating_a = float(global_rating[player_a])
            rating_b = float(global_rating[player_b])
            values: dict[str, float | None] = {
                f"chronological_elo_margin_k{global_k}": (
                    rating_a - rating_b
                ) / 400.0,
            }
            global_updates.append((
                player_a, player_b,
                global_k * (outcome - _expected(rating_a, rating_b)),
            ))
            audit = (
                (row.get("candidate_equation_audit") or {})
                .get("exact_surface_ledger") or {}
            )
            context = audit.get("context") or (
                (row.get("diagnostics") or {}).get("surface_context")
            )
            context = str(context) if context not in {None, "", "nan", "none"} else None
            if universe == "wta" and context:
                key_a, key_b = (player_a, context), (player_b, context)
                surface_a = float(surface_rating[key_a])
                surface_b = float(surface_rating[key_b])
                weight_a = surface_count[key_a] / (
                    surface_count[key_a] + SURFACE_SHRINK_MATCHES
                )
                weight_b = surface_count[key_b] / (
                    surface_count[key_b] + SURFACE_SHRINK_MATCHES
                )
                shrunk_a = rating_a + weight_a * (surface_a - rating_a)
                shrunk_b = rating_b + weight_b * (surface_b - rating_b)
                values["surface_elo_residual_k32"] = (
                    (shrunk_a - shrunk_b) - (rating_a - rating_b)
                ) / 400.0
                surface_updates.append((
                    key_a, key_b,
                    SURFACE_K * (outcome - _expected(surface_a, surface_b)),
                ))
            elif universe == "wta":
                values["surface_elo_residual_k32"] = None
            additions[index] = values
        for player_a, player_b, delta in global_updates:
            global_rating[player_a] += delta
            global_rating[player_b] -= delta
        for key_a, key_b, delta in surface_updates:
            surface_rating[key_a] += delta
            surface_rating[key_b] -= delta
            surface_count[key_a] += 1
            surface_count[key_b] += 1

    output = []
    for index, row in enumerate(rows):
        features = dict(row.get("features") or {})
        features.update(additions[index])
        output.append({**row, "features": features})
    return output


def clear_rating_cache() -> None:
    with _LOCK:
        _CACHE.clear()
