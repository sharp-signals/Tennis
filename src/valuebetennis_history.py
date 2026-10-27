"""Licensed ATP results/odds history from Valuebetennis.

The source publishes annual CSV files under CC BY 4.0.  This module keeps the
external observations separate from the immutable Fenzobot snapshots: it can
enrich descriptive history, but it never rewrites what was known pre-match.
"""

from __future__ import annotations

import io
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import requests


SOURCE_NAME = "Valuebetennis"
SOURCE_PAGE = "https://www.valuebetennis.com/donnees.htm"
SOURCE_LICENSE = "CC BY 4.0"
SOURCE_CITATION = (
    "Valuebetennis, Résultats et cotes de tennis depuis 2021, "
    "https://www.valuebetennis.com/donnees.htm"
)
SOURCE_URL_TEMPLATE = "https://www.valuebetennis.com/datasets/valuebetennis-matchs-{year}.csv"
CACHE_PATTERN = "valuebetennis_atp_{year}.csv.gz"
FIRST_YEAR = 2021
ATP_CATEGORIES = frozenset(
    {"Challenger", "Main tour", "Masters", "Grand Chelem", "Davis/BJK"}
)
_CATEGORY_TIER = {
    "Challenger": "challenger",
    "Main tour": "atp 250",
    "Masters": "masters 1000",
    "Grand Chelem": "grand slam",
    "Davis/BJK": "davis cup",
}
REQUEST_TIMEOUT = 45
_HEADERS = {"User-Agent": "Fenzobot/1.0 (+historical research; CC BY attribution)"}


def normalize_name(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(char for char in raw if not unicodedata.combining(char))
    clean = "".join(char if char.isalnum() else " " for char in ascii_value)
    return " ".join(clean.casefold().split())


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) and parsed > 1 else None


def _surface_tokens(value: object) -> tuple[str, bool]:
    """Return the normalized label and its explicit indoor qualifier.

    Some legacy gzip caches contain a replacement character in
    ``intérieur`` (``int�rieur``).  ``normalize_name`` safely turns that
    byte-decoding artefact into ``int rieur``; supporting that exact token
    sequence recovers the source meaning without guessing a venue.
    """
    normalized = normalize_name(value)
    indoor = any(
        marker in normalized
        for marker in ("interieur", "int rieur", "indoor")
    )
    return normalized, indoor


def _surface(value: object) -> str | None:
    """Normaliza os rótulos franceses da fonte para o contrato do motor."""
    normalized, _indoor = _surface_tokens(value)
    if normalized in {"dur", "hard", "hardcourt"} or normalized.startswith("dur "):
        return "Hard"
    if normalized in {"terre", "terre battue", "clay"}:
        return "Clay"
    if normalized in {"gazon", "grass"}:
        return "Grass"
    if normalized in {"moquette", "carpet"} or normalized.startswith("moquette "):
        return "Carpet"
    return str(value or "").strip() or None


def _surface_is_indoor(value: object) -> bool:
    """Use only the explicit venue qualifier supplied by Valuebetennis."""
    return _surface_tokens(value)[1]


def _score_sets(score: object) -> list[tuple[int, int]]:
    raw = str(score or "").strip()
    if not raw or any(marker in raw.upper() for marker in ("RET", "W/O", "DEF", "ABD")):
        return []
    result: list[tuple[int, int]] = []
    for token in raw.split():
        match = re.fullmatch(r"(\d+)-(\d+)(?:\([^)]*\))?", token)
        if not match:
            return []
        left, right = int(match.group(1)), int(match.group(2))
        if max(left, right) < 6 or (abs(left - right) < 2 and max(left, right) < 7):
            return []
        result.append((left, right))
    return result


def _best_of(category: str, round_value: object, sets: list[tuple[int, int]]) -> int | None:
    if len(sets) >= 4:
        return 5
    # In the source, Grand Slam qualifying rounds are numbered 1–3 and the
    # men's main draw starts at round 4.  A straight-set main-draw result still
    # needs this rule because the score alone cannot prove BO5.
    try:
        round_number = int(float(round_value))
    except (TypeError, ValueError):
        round_number = None
    if category == "Grand Chelem" and round_number is not None and round_number >= 4:
        return 5
    return 3 if len(sets) >= 2 else None


def normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Return a compact, winner-oriented ATP frame with explicit provenance."""
    required = {
        "match_id", "date", "tournoi", "categorie", "genre", "surface", "tour",
        "joueur1", "joueur1_id", "joueur2", "joueur2_id", "cote1_ouverture",
        "cote2_ouverture", "cote1_cloture", "cote2_cloture", "vainqueur_id", "score",
    }
    if not required.issubset(raw.columns):
        missing = sorted(required.difference(raw.columns))
        raise ValueError(f"Valuebetennis schema incompleto: {missing}")
    source = raw[
        raw["genre"].astype(str).str.casefold().eq("atp")
        & raw["categorie"].astype(str).isin(ATP_CATEGORIES)
    ].copy()
    rows: list[dict[str, Any]] = []
    for record in source.to_dict("records"):
        p1_id = str(record.get("joueur1_id") or "").removesuffix(".0")
        p2_id = str(record.get("joueur2_id") or "").removesuffix(".0")
        winner_id = str(record.get("vainqueur_id") or "").removesuffix(".0")
        if winner_id not in {p1_id, p2_id}:
            continue
        winner_is_p1 = winner_id == p1_id
        player1, player2 = str(record.get("joueur1") or "").strip(), str(record.get("joueur2") or "").strip()
        if not player1 or not player2:
            continue
        sets_player_order = _score_sets(record.get("score"))
        sets_winner_order = [
            pair if winner_is_p1 else (pair[1], pair[0]) for pair in sets_player_order
        ]
        category = str(record.get("categorie") or "").strip()
        opening1, opening2 = _number(record.get("cote1_ouverture")), _number(record.get("cote2_ouverture"))
        closing1, closing2 = _number(record.get("cote1_cloture")), _number(record.get("cote2_cloture"))
        opening_w, opening_l = ((opening1, opening2) if winner_is_p1 else (opening2, opening1))
        closing_w, closing_l = ((closing1, closing2) if winner_is_p1 else (closing2, closing1))
        paired_closing = closing_w is not None and closing_l is not None
        paired_opening = opening_w is not None and opening_l is not None
        preferred_w = closing_w if paired_closing else opening_w if paired_opening else None
        preferred_l = closing_l if paired_closing else opening_l if paired_opening else None
        played_at = pd.to_datetime(record.get("date"), errors="coerce")
        row = {
            "source": SOURCE_NAME,
            "source_match_id": str(record.get("match_id") or "").removesuffix(".0"),
            "tourney_date": played_at.strftime("%Y%m%d") if pd.notna(played_at) else None,
            "date": played_at.strftime("%Y-%m-%d") if pd.notna(played_at) else None,
            "tourney_name": str(record.get("tournoi") or "").strip(),
            "category": category,
            # This field is used only by the existing ranking-eligibility
            # classifier.  Main-tour ATP 250/500 distinctions have the same
            # eligibility weight; the original category remains preserved.
            "tier": _CATEGORY_TIER.get(category),
            "surface": _surface(record.get("surface")),
            "source_surface": str(record.get("surface") or "").strip() or None,
            "indoor": _surface_is_indoor(record.get("surface")),
            "round": record.get("tour"),
            "winner_name": player1 if winner_is_p1 else player2,
            "winner_id": p1_id if winner_is_p1 else p2_id,
            "loser_name": player2 if winner_is_p1 else player1,
            "loser_id": p2_id if winner_is_p1 else p1_id,
            "score": " ".join(f"{left}-{right}" for left, right in sets_winner_order),
            "best_of": _best_of(category, record.get("tour"), sets_winner_order),
            "opening_winner_odd": opening_w,
            "opening_loser_odd": opening_l,
            "closing_winner_odd": closing_w,
            "closing_loser_odd": closing_l,
            # Compatibility columns used by the existing odds-band analytics.
            "PSW": preferred_w,
            "PSL": preferred_l,
            "odds_observation": "closing" if paired_closing else "opening" if paired_opening else None,
            "_history_competition_scope": "challenger" if category == "Challenger" else "main",
        }
        for number in range(1, 6):
            if number <= len(sets_winner_order):
                row[f"W{number}"], row[f"L{number}"] = sets_winner_order[number - 1]
            else:
                row[f"W{number}"], row[f"L{number}"] = None, None
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["source_match_id"], keep="last").reset_index(drop=True)


def download_year(year: int) -> pd.DataFrame:
    response = requests.get(
        SOURCE_URL_TEMPLATE.format(year=int(year)), headers=_HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    raw = pd.read_csv(io.BytesIO(response.content), sep=";", low_memory=False)
    return normalize_frame(raw)


def refresh_year(cache_dir: Path, year: int) -> pd.DataFrame:
    frame = download_year(year)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Fixed gzip mtime keeps identical source content byte-identical, avoiding
    # a generated-data commit on every bot run.
    frame.to_csv(
        cache_dir / CACHE_PATTERN.format(year=int(year)),
        index=False,
        compression={"method": "gzip", "mtime": 0},
    )
    return frame


def load_history(
    cache_dir: Path,
    *,
    refresh_current: bool | None = None,
    current_year: int | None = None,
) -> pd.DataFrame:
    """Load cached years and optionally refresh the current licensed dataset.

    Closed years are immutable local inputs.  The current year refreshes by
    default in production, with a cache fallback if the source is unavailable.
    ``VALUEBETENNIS_NETWORK_REFRESH=0`` provides an explicit cache-only mode.
    """
    current = int(current_year or datetime.now(timezone.utc).year)
    if refresh_current is None:
        refresh_current = os.getenv("VALUEBETENNIS_NETWORK_REFRESH", "1").strip().casefold() not in {
            "0", "false", "no", "off",
        }
    frames: list[pd.DataFrame] = []
    for year in range(FIRST_YEAR, current + 1):
        path = cache_dir / CACHE_PATTERN.format(year=year)
        frame: pd.DataFrame | None = None
        if year == current and refresh_current:
            try:
                frame = refresh_year(cache_dir, year)
            except (requests.RequestException, OSError, ValueError, pd.errors.ParserError) as exc:
                print(f"[aviso] {SOURCE_NAME} {year}: refresh indisponível; cache preservada ({exc})")
        if frame is None and path.exists():
            try:
                frame = pd.read_csv(path, low_memory=False)
            except (OSError, ValueError, pd.errors.ParserError) as exc:
                print(f"[aviso] cache {SOURCE_NAME} {year} inválida: {exc}")
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["source_match_id"], keep="last")
    if "surface" in combined.columns:
        # Migra também caches antigos que preservavam os rótulos franceses
        # (incluindo os qualificadores indoor) antes desta normalização.
        source_surface = (
            combined["source_surface"]
            if "source_surface" in combined.columns
            else combined["surface"]
        )
        if "source_surface" not in combined.columns:
            combined["source_surface"] = source_surface
        detected_indoor = source_surface.map(_surface_is_indoor)
        if "indoor" in combined.columns:
            existing_indoor = combined["indoor"].map(
                lambda value: (
                    str(value).strip().casefold() in {"true", "1", "yes", "indoor", "i"}
                    if pd.notna(value)
                    else False
                )
            )
            combined["indoor"] = existing_indoor | detected_indoor
        else:
            combined["indoor"] = detected_indoor
        combined["surface"] = source_surface.map(_surface)
    combined.attrs.update({
        "source": SOURCE_NAME,
        "source_page": SOURCE_PAGE,
        "source_license": SOURCE_LICENSE,
        "source_citation": SOURCE_CITATION,
    })
    return combined.reset_index(drop=True)


def _snapshot_players(snapshot: Mapping[str, Any]) -> tuple[str, str]:
    player_a = snapshot.get("player_a") if isinstance(snapshot.get("player_a"), Mapping) else {}
    player_b = snapshot.get("player_b") if isinstance(snapshot.get("player_b"), Mapping) else {}
    return str(player_a.get("name") or "").strip(), str(player_b.get("name") or "").strip()


def _date(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return parsed.date() if pd.notna(parsed) else None


def canonical_odds_enrichment(
    snapshots: Iterable[Mapping[str, Any]], history: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Match missing-odds ATP snapshots without mutating their captured state."""
    if history.empty:
        return []
    index: dict[frozenset[str], list[Mapping[str, Any]]] = {}
    for row in history.to_dict("records"):
        played_on = _date(row.get("date"))
        names = frozenset((normalize_name(row.get("winner_name")), normalize_name(row.get("loser_name"))))
        if played_on and len(names) == 2 and "" not in names:
            index.setdefault(names, []).append(row)
    result: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if str(snapshot.get("tour") or "").casefold() != "atp":
            continue
        player_a, player_b = _snapshot_players(snapshot)
        captured = snapshot.get("market_odds_decimal") if isinstance(snapshot.get("market_odds_decimal"), Mapping) else {}
        if _number(captured.get(player_a)) is not None and _number(captured.get(player_b)) is not None:
            continue
        played_on = _date(snapshot.get("commence_time_utc"))
        if played_on is None:
            continue
        pair_candidates = index.get(
            frozenset((normalize_name(player_a), normalize_name(player_b))), []
        )
        candidates = [row for row in pair_candidates if _date(row.get("date")) == played_on]
        confidence = "exact_players_and_date_unique"
        if not candidates:
            # A night session can carry the local calendar date in one source
            # and UTC in another. Only bridge that one-day boundary when the
            # tournament is also exact and the resulting candidate is unique.
            tournament = normalize_name(snapshot.get("tournament"))
            candidates = [
                row for row in pair_candidates
                if tournament
                and normalize_name(row.get("tourney_name")) == tournament
                and _date(row.get("date")) is not None
                and abs((_date(row.get("date")) - played_on).days) == 1
            ]
            confidence = "exact_players_tournament_adjacent_date_unique"
        if len(candidates) != 1:
            continue
        row = candidates[0]
        source_date = _date(row.get("date"))
        winner = normalize_name(row.get("winner_name"))
        a_won = normalize_name(player_a) == winner
        result.append({
            "event_id": str(snapshot.get("canonical_match_instance_id") or snapshot.get("key") or ""),
            "snapshot_key": snapshot.get("key"),
            "match_date": played_on.isoformat(),
            "source_match_date": source_date.isoformat() if source_date else None,
            "date_delta_days": (source_date - played_on).days if source_date else None,
            "tournament": snapshot.get("tournament"),
            "player_a": player_a,
            "player_b": player_b,
            "opening_odd_a": _number(row.get("opening_winner_odd") if a_won else row.get("opening_loser_odd")),
            "opening_odd_b": _number(row.get("opening_loser_odd") if a_won else row.get("opening_winner_odd")),
            "closing_odd_a": _number(row.get("closing_winner_odd") if a_won else row.get("closing_loser_odd")),
            "closing_odd_b": _number(row.get("closing_loser_odd") if a_won else row.get("closing_winner_odd")),
            "source": SOURCE_NAME,
            "source_match_id": str(row.get("source_match_id") or ""),
            "source_license": SOURCE_LICENSE,
            "match_confidence": confidence,
            "semantics": "POST_HOC_ENRICHMENT_NOT_ORIGINAL_CAPTURE",
        })
    return result
