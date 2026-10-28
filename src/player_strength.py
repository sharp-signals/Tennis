"""Prior histórico de força para pricing independente do mercado.

Reconstrói Elo ATP apenas com resultados do circuito principal anteriores à
data da análise. Challengers não contaminam este prior. O módulo é read-only e
mantém uma cache diária em memória para que dezenas de relatórios não voltem a
percorrer o histórico.
"""

from __future__ import annotations

import csv
import gzip
import math
import re
import threading
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
ATP_HISTORY_FILES = tuple(sorted((ROOT / "data" / "history_cache").glob(
    "valuebetennis_atp_*.csv.gz"
)))
ATP_ELO_K = 40.0
ATP_ELO_VERSION = "atp-main-global-surface-elo-v1"
_CACHE_LOCK = threading.Lock()
_RATING_CACHE: dict[date, dict[str, Any]] = {}


def normalize_player_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def normalize_surface(value: Any) -> str:
    normalized = str(value or "").casefold()
    for candidate in ("hard", "clay", "grass", "carpet"):
        if candidate in normalized:
            return candidate
    return "unknown"


def _player_name(payload: Mapping[str, Any], side: str) -> str:
    raw = payload.get(f"player_{side}")
    if isinstance(raw, Mapping):
        raw = raw.get("name")
    return normalize_player_name(raw)


def _analysis_cutoff(payload: Mapping[str, Any]) -> date:
    for key in ("analyzed_at_utc", "analysis_generated_at_utc", "generated_at_utc"):
        raw = payload.get(key)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date()
    return datetime.now(timezone.utc).date()


@lru_cache(maxsize=1)
def _history_matches() -> tuple[tuple[date, str, str, str], ...]:
    matches = []
    for path in ATP_HISTORY_FILES:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("_history_competition_scope") or "").casefold() != "main":
                    continue
                if not str(row.get("score") or "").strip():
                    continue
                try:
                    played_on = date.fromisoformat(str(row.get("date") or ""))
                except ValueError:
                    continue
                winner = normalize_player_name(row.get("winner_name"))
                loser = normalize_player_name(row.get("loser_name"))
                if winner and loser:
                    matches.append((
                        played_on,
                        normalize_surface(row.get("surface")),
                        winner,
                        loser,
                    ))
    return tuple(sorted(matches, key=lambda item: (item[0], item[2], item[3])))


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _ratings_before(cutoff: date) -> dict[str, Any]:
    cached = _RATING_CACHE.get(cutoff)
    if cached is not None:
        return cached
    with _CACHE_LOCK:
        cached = _RATING_CACHE.get(cutoff)
        if cached is not None:
            return cached
        global_ratings = defaultdict(lambda: 1500.0)
        surface_ratings = defaultdict(lambda: 1500.0)
        global_matches = defaultdict(int)
        surface_matches = defaultdict(int)
        processed = 0
        for played_on, surface, winner, loser in _history_matches():
            # O ficheiro histórico só tem data, não hora. Excluir o próprio dia
            # evita usar um resultado que ainda não era conhecido no snapshot.
            if played_on >= cutoff:
                break
            expected = _expected(global_ratings[winner], global_ratings[loser])
            change = ATP_ELO_K * (1.0 - expected)
            global_ratings[winner] += change
            global_ratings[loser] -= change
            global_matches[winner] += 1
            global_matches[loser] += 1

            winner_key, loser_key = (surface, winner), (surface, loser)
            expected_surface = _expected(
                surface_ratings[winner_key], surface_ratings[loser_key]
            )
            surface_change = ATP_ELO_K * (1.0 - expected_surface)
            surface_ratings[winner_key] += surface_change
            surface_ratings[loser_key] -= surface_change
            surface_matches[winner_key] += 1
            surface_matches[loser_key] += 1
            processed += 1
        cached = {
            "global_ratings": dict(global_ratings),
            "surface_ratings": dict(surface_ratings),
            "global_matches": dict(global_matches),
            "surface_matches": dict(surface_matches),
            "processed_matches": processed,
        }
        _RATING_CACHE[cutoff] = cached
        return cached


def atp_main_strength_features(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Devolve logits Elo ex ante para ATP principal; nunca consulta mercado."""
    player_a, player_b = _player_name(payload, "a"), _player_name(payload, "b")
    if not player_a or not player_b or not ATP_HISTORY_FILES:
        return {"available": False, "reason": "PLAYER_OR_HISTORY_UNAVAILABLE"}
    cutoff = _analysis_cutoff(payload)
    ratings = _ratings_before(cutoff)
    matches_a = int(ratings["global_matches"].get(player_a, 0))
    matches_b = int(ratings["global_matches"].get(player_b, 0))
    if min(matches_a, matches_b) < 5:
        return {
            "available": False,
            "reason": "INSUFFICIENT_MAIN_TOUR_HISTORY",
            "matches_a": matches_a,
            "matches_b": matches_b,
        }
    rating_a = float(ratings["global_ratings"].get(player_a, 1500.0))
    rating_b = float(ratings["global_ratings"].get(player_b, 1500.0))
    surface = normalize_surface(payload.get("surface"))
    surface_key_a, surface_key_b = (surface, player_a), (surface, player_b)
    surface_matches_a = int(ratings["surface_matches"].get(surface_key_a, 0))
    surface_matches_b = int(ratings["surface_matches"].get(surface_key_b, 0))
    surface_rating_a = float(ratings["surface_ratings"].get(surface_key_a, 1500.0))
    surface_rating_b = float(ratings["surface_ratings"].get(surface_key_b, 1500.0))
    surface_logit = (
        (surface_rating_a - surface_rating_b) * math.log(10.0) / 400.0
        if min(surface_matches_a, surface_matches_b) >= 3 else 0.0
    )
    return {
        "available": True,
        "version": ATP_ELO_VERSION,
        "cutoff_date": cutoff.isoformat(),
        "history_scope": "ATP_MAIN_ONLY",
        "processed_matches": ratings["processed_matches"],
        "global_logit": (rating_a - rating_b) * math.log(10.0) / 400.0,
        "surface_logit": surface_logit,
        "surface": surface,
        "rating_a": round(rating_a, 3),
        "rating_b": round(rating_b, 3),
        "surface_rating_a": round(surface_rating_a, 3),
        "surface_rating_b": round(surface_rating_b, 3),
        "matches_a": matches_a,
        "matches_b": matches_b,
        "surface_matches_a": surface_matches_a,
        "surface_matches_b": surface_matches_b,
    }
