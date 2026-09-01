"""Idempotent historical acquisition through the shared RapidAPI guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from . import fetch_data
from .config import RAPIDAPI_BASE
from .historical_warehouse import HistoricalWarehouse, make_cache_key, payload_hash, utc_now


SOURCE = "rapidapi:tennis-api-atp-wta-itf"
SOURCE_VERSION = "tennis-v2"


def _iso_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _data(payload: Any) -> Any:
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def _is_empty_dynamic_payload(payload: Any) -> bool:
    """An empty 2xx is not cached forever because provider history can grow."""
    return _data(payload) in (None, [], {})


def _player(raw: Mapping[str, Any], number: int) -> tuple[str | None, str]:
    nested = raw.get(f"player{number}")
    nested = nested if isinstance(nested, dict) else {}
    player_id = raw.get(f"player{number}Id") or nested.get("id")
    name = (
        raw.get(f"player{number}Name")
        or nested.get("name")
        or nested.get("fullName")
        or f"Jogador {player_id or number}"
    )
    return (str(player_id) if player_id is not None else None, str(name))


def normalize_past_match(raw: Mapping[str, Any], *, tour: str, cache_key: str, fetched_at: str) -> dict[str, Any] | None:
    """Normalize only facts present in a past-match record; never infer time semantics."""
    event_start = _iso_date(raw.get("date") or raw.get("startTime") or raw.get("tourney_date"))
    if not event_start:
        return None
    player_a_id, player_a_name = _player(raw, 1)
    player_b_id, player_b_name = _player(raw, 2)
    provider_match_id = raw.get("id") or raw.get("matchId") or raw.get("fixtureId")
    canonical_id = f"{SOURCE}:{tour}:{provider_match_id}" if provider_match_id is not None else (
        f"{SOURCE}:{tour}:{event_start}:{player_a_id or player_a_name}:{player_b_id or player_b_name}"
    )
    winner = raw.get("match_winner") or raw.get("winnerId") or raw.get("winner")
    if isinstance(winner, dict):
        winner = winner.get("id") or winner.get("name")
    tournament = raw.get("tournament") if isinstance(raw.get("tournament"), dict) else {}
    tournament_id = raw.get("tournamentId") or tournament.get("id")
    tournament_name = raw.get("tournamentName") or tournament.get("name")
    record_hash = payload_hash(raw)
    normalized = {
        "canonical_match_id": canonical_id,
        "source": SOURCE,
        "endpoint": "getPlayerPastMatches",
        "provider_match_id": str(provider_match_id) if provider_match_id is not None else None,
        "provider_timestamp": raw.get("updatedAt") or raw.get("timestamp"),
        "fetched_at_utc": fetched_at,
        "source_version": SOURCE_VERSION,
        "payload_hash": record_hash,
        "raw_cache_key": cache_key,
        "tour": tour.upper(),
        "tournament": tournament_name,
        "tournament_id": str(tournament_id) if tournament_id is not None else None,
        "tournament_level": raw.get("tier") or tournament.get("tier"),
        "surface": raw.get("surface") or raw.get("court"),
        "event_start_utc": event_start,
        "date_precision": "event_exact" if "T" in str(raw.get("date") or raw.get("startTime") or "") else "day",
        "player_a_id": player_a_id,
        "player_a_name": player_a_name,
        "player_b_id": player_b_id,
        "player_b_name": player_b_name,
        "player_a_rank": raw.get("player1Rank") or raw.get("rank1"),
        "player_b_rank": raw.get("player2Rank") or raw.get("rank2"),
        "round": raw.get("round") or raw.get("roundName"),
        "best_of": raw.get("bestOf"),
        "identity_temporal_class": "EXACT_EX_ANTE",
        # Rank inside the historical record is safe only as a reconstruction,
        # until the capability audit proves its provider timestamp semantics.
        "ranking_temporal_class": "RECONSTRUCTED_EX_ANTE" if (
            raw.get("player1Rank") is not None or raw.get("rank1") is not None
            or raw.get("player2Rank") is not None or raw.get("rank2") is not None
        ) else "UNAVAILABLE",
        "outcome_winner_id": str(winner) if winner is not None else None,
        "outcome_result": raw.get("result") or raw.get("score"),
        "outcome_temporal_class": "EX_POST_ONLY",
    }
    normalized["quotes"] = []
    for number, selection in ((1, player_a_id or player_a_name), (2, player_b_id or player_b_name)):
        odd = raw.get(f"odd{number}")
        try:
            odd = float(odd)
        except (TypeError, ValueError):
            continue
        if odd <= 1:
            continue
        normalized["quotes"].append({
            "match_id": canonical_id,
            "bookmaker": raw.get("bookmaker"),
            "market": "moneyline",
            "selection": str(selection),
            "odd": odd,
            "provider_timestamp": raw.get("oddsTimestamp"),
            "temporal_role": "UNKNOWN",
            # Stored, but deliberately unavailable to an ex-ante replay until
            # the provider proves when the quote was observed.
            "temporal_class": "UNAVAILABLE",
            "source": SOURCE,
            "endpoint": "getPlayerPastMatches",
            "fetched_at_utc": fetched_at,
            "payload_hash": record_hash,
        })
    return normalized


@dataclass
class AcquisitionMetrics:
    calls_made: int = 0
    calls_avoided_via_cache: int = 0
    cache_hits: int = 0
    records_stored: int = 0
    failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return vars(self).copy()


class HistoricalAcquirer:
    def __init__(self, warehouse: HistoricalWarehouse):
        self.warehouse = warehouse
        self.metrics = AcquisitionMetrics()

    def fetch_json(self, endpoint: str, url: str, params: Mapping[str, Any] | None = None) -> tuple[Any, str, bool]:
        key = make_cache_key(SOURCE, endpoint, params, source_version=SOURCE_VERSION)
        cached = self.warehouse.get_raw_response(key)
        if cached is not None:
            self.metrics.cache_hits += 1
            self.metrics.calls_avoided_via_cache += 1
            return cached, key, True
        calls_before = fetch_data.get_rapidapi_purpose_counts().get("backfill", 0)
        try:
            response = fetch_data._rapidapi_get(url, params=dict(params or {}), rapidapi_purpose="backfill")
        finally:
            calls_after = fetch_data.get_rapidapi_purpose_counts().get("backfill", 0)
            self.metrics.calls_made += max(0, calls_after - calls_before)
        response.raise_for_status()
        payload = response.json()
        fetched_at = utc_now()
        if not _is_empty_dynamic_payload(payload):
            provider_timestamp = payload.get("timestamp") if isinstance(payload, dict) else None
            self.warehouse.put_raw_response(
                cache_key=key, source=SOURCE, endpoint=endpoint, params=params,
                fetched_at_utc=fetched_at, provider_timestamp=provider_timestamp,
                status=response.status_code, payload=payload, source_version=SOURCE_VERSION,
            )
        return payload, key, False

    def acquire_player_past_matches(
        self, tour: str, player_id: int, *, resume: bool = True, max_records: int | None = None,
    ) -> list[str]:
        tour = tour.lower()
        item_key = f"past_matches:{tour}:{int(player_id)}"
        state = self.warehouse.get_backfill_state(item_key)
        if resume and state and state.get("status") == "completed":
            self.metrics.calls_avoided_via_cache += 1
            return []
        offset = int((state or {}).get("cursor") or 0) if resume else 0
        self.warehouse.set_backfill_state(
            item_key, "running", cursor=str(offset), increment_attempt=True,
        )
        try:
            endpoint = "getPlayerPastMatches"
            url = f"{RAPIDAPI_BASE}/{tour}/player/past-matches/{int(player_id)}"
            payload, key, _ = self.fetch_json(endpoint, url, {"tour": tour, "player_id": int(player_id)})
            fetched_at = utc_now()
            rows = _data(payload)
            rows = rows if isinstance(rows, list) else []
            end = len(rows) if max_records is None else min(len(rows), offset + max(0, int(max_records)))
            selected_rows = rows[offset:end]
            match_ids: list[str] = []
            for raw in selected_rows:
                if not isinstance(raw, dict):
                    continue
                match = normalize_past_match(raw, tour=tour, cache_key=key, fetched_at=fetched_at)
                if not match:
                    continue
                quotes = match.pop("quotes")
                self.warehouse.upsert_match(match)
                for quote in quotes:
                    self.warehouse.add_market_quote(quote)
                match_ids.append(match["canonical_match_id"])
            self.metrics.records_stored += len(match_ids)
            status = "completed" if end >= len(rows) else "partial"
            self.warehouse.set_backfill_state(item_key, status, cursor=str(end))
            return match_ids
        except Exception as exc:
            self.metrics.failures += 1
            self.warehouse.set_backfill_state(item_key, "failed", cursor=str(offset), error=str(exc))
            raise


AUDIT_ENDPOINTS = {
    "getPlayerPastMatches": "{base}/{tour}/player/past-matches/{player_id}",
    "getPlayerPerfBreakdown": "{base}/{tour}/player/perf-breakdown/{player_id}",
    "getSinglesRanking": "{base}/{tour}/ranking/singles/",
    "getVsAllStats": "{base}/{tour}/h2h/vs-all-stats/{player_id}/",
}
