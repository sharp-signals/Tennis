"""Fail-closed identity checks for legacy ``tour:provider_match_id`` keys.

This is containment only.  It deliberately does not mint a new canonical
identity and never mutates the immutable pre-live record.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping


MATCH = "MATCH"
COLLISION = "COLLISION"
INSUFFICIENT = "INSUFFICIENT"
TIME_TOLERANCE_HOURS = 48


def _value(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _side(record: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    direct = record.get(f"player_{side}")
    if isinstance(direct, Mapping):
        return direct
    players = record.get("players")
    if isinstance(players, Mapping) and isinstance(players.get(side), Mapping):
        return players[side]
    provider_side = "player1" if side == "a" else "player2"
    provider = record.get(provider_side)
    return provider if isinstance(provider, Mapping) else {}


def _player_ids(record: Mapping[str, Any]) -> tuple[str, str] | None:
    result: list[str] = []
    for side, provider_key in (("a", "player1Id"), ("b", "player2Id")):
        value = _value(record, f"player_{side}_id", provider_key)
        if value in (None, ""):
            value = _side(record, side).get("id")
        if value in (None, ""):
            return None
        result.append(str(value))
    return result[0], result[1]


def normalize_name(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.casefold()).split())


def _player_names(record: Mapping[str, Any]) -> tuple[str, str] | None:
    result: list[str] = []
    for side in ("a", "b"):
        value = record.get(f"player_{side}")
        if isinstance(value, Mapping):
            value = value.get("name")
        if value in (None, ""):
            value = _side(record, side).get("name")
        normalized = normalize_name(value)
        if not normalized:
            return None
        result.append(normalized)
    return result[0], result[1]


def _pair(values: tuple[str, str] | None) -> frozenset[str] | None:
    return frozenset(values) if values and len(set(values)) == 2 else None


def _time(record: Mapping[str, Any]) -> datetime | None:
    value = _value(record, "commence_time_utc", "scheduled_start_utc", "date")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _collision(reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": COLLISION,
        "reason_code": "PROVIDER_MATCH_ID_REUSED",
        "detail_reason_code": "SNAPSHOT_IDENTITY_COLLISION",
        "conflict": reason,
        "evidence": evidence,
    }


def compare(
    candidate: Mapping[str, Any],
    persisted: Mapping[str, Any],
    *,
    time_tolerance_hours: int = TIME_TOLERANCE_HOURS,
) -> dict[str, Any]:
    """Compare two event representations without trusting provider ID alone."""
    candidate_ids = _pair(_player_ids(candidate))
    persisted_ids = _pair(_player_ids(persisted))
    candidate_names = _pair(_player_names(candidate))
    persisted_names = _pair(_player_names(persisted))
    evidence = {
        "bilateral_player_ids_available": bool(candidate_ids and persisted_ids),
        "bilateral_names_available": bool(candidate_names and persisted_names),
        "tour_compared": False,
        "tournament_id_compared": False,
        "commence_time_compared": False,
        "time_tolerance_hours": int(time_tolerance_hours),
    }

    if candidate_ids and persisted_ids:
        if candidate_ids != persisted_ids:
            return _collision("PLAYER_IDS_MISMATCH", evidence)
        player_source = "BILATERAL_PLAYER_IDS"
    elif candidate_names and persisted_names:
        if candidate_names != persisted_names:
            return _collision("PLAYER_NAMES_MISMATCH", evidence)
        player_source = "BILATERAL_EXACT_NORMALIZED_NAMES"
    else:
        return {
            "status": INSUFFICIENT,
            "reason_code": "SNAPSHOT_IDENTITY_INSUFFICIENT",
            "evidence": evidence,
        }

    candidate_tour = normalize_name(_value(candidate, "tour", "_tour"))
    persisted_tour = normalize_name(_value(persisted, "tour", "_tour"))
    if candidate_tour and persisted_tour:
        evidence["tour_compared"] = True
        if candidate_tour != persisted_tour:
            return _collision("TOUR_MISMATCH", evidence)

    candidate_tournament = _value(candidate, "tournament_id", "tournamentId")
    persisted_tournament = _value(persisted, "tournament_id", "tournamentId")
    if candidate_tournament not in (None, "") and persisted_tournament not in (None, ""):
        evidence["tournament_id_compared"] = True
        if str(candidate_tournament) != str(persisted_tournament):
            return _collision("TOURNAMENT_ID_MISMATCH", evidence)

    candidate_time = _time(candidate)
    persisted_time = _time(persisted)
    if candidate_time and persisted_time:
        evidence["commence_time_compared"] = True
        delta_hours = abs((candidate_time - persisted_time).total_seconds()) / 3600
        evidence["commence_time_delta_hours"] = round(delta_hours, 3)
        if delta_hours > time_tolerance_hours:
            return _collision("COMMENCE_TIME_OUTSIDE_TOLERANCE", evidence)

    return {
        "status": MATCH,
        "reason_code": "SNAPSHOT_IDENTITY_MATCH",
        "identity_source": player_source,
        "evidence": evidence,
    }


def public_linkage(comparison: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlisted linkage marker safe for reports and run telemetry."""
    status = str(comparison.get("status") or INSUFFICIENT)
    if status == MATCH:
        return {
            "status": "LINKED",
            "reason_code": "SNAPSHOT_IDENTITY_MATCH",
            "identity_source": comparison.get("identity_source"),
        }
    if status == COLLISION:
        return {
            "status": "COLLISION",
            "reason_code": "PROVIDER_MATCH_ID_REUSED",
            "detail_reason_code": "SNAPSHOT_IDENTITY_COLLISION",
            "conflict": comparison.get("conflict"),
        }
    return {
        "status": "UNLINKED",
        "reason_code": str(comparison.get("reason_code") or "SNAPSHOT_IDENTITY_INSUFFICIENT"),
    }
