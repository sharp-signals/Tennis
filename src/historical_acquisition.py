"""Idempotent historical acquisition through the shared RapidAPI guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Mapping

from . import fetch_data
from .config import RAPIDAPI_BASE
from .historical_warehouse import HistoricalWarehouse, make_cache_key, payload_hash, utc_now


SOURCE = "rapidapi:tennis-api-atp-wta-itf"
SOURCE_VERSION = "tennis-v2"
PAGINATION_CURSOR_VERSION = 2


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

    def fetch_json(
        self,
        endpoint: str,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        request_params: Mapping[str, Any] | None = None,
    ) -> tuple[Any, str, bool]:
        key = make_cache_key(SOURCE, endpoint, params, source_version=SOURCE_VERSION)
        cached = self.warehouse.get_raw_response(key)
        if cached is None:
            legacy_key = make_cache_key(
                SOURCE, endpoint, params, source_version=SOURCE_VERSION, schema_version=1,
            )
            cached = self.warehouse.get_raw_response(legacy_key)
            if cached is not None:
                key = legacy_key
        if cached is not None:
            self.metrics.cache_hits += 1
            self.metrics.calls_avoided_via_cache += 1
            return cached, key, True
        calls_before = fetch_data.get_rapidapi_purpose_counts().get("backfill", 0)
        try:
            actual_params = params if request_params is None else request_params
            response = fetch_data._rapidapi_get(
                url, params=dict(actual_params or {}), rapidapi_purpose="backfill",
            )
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

    @staticmethod
    def _parse_cursor(raw_cursor: Any) -> dict[str, Any]:
        """Migrate the v1 numeric row offset without claiming source exhaustion."""
        if isinstance(raw_cursor, dict):
            parsed = raw_cursor
        else:
            try:
                parsed = json.loads(str(raw_cursor)) if raw_cursor not in (None, "") else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = {}
        if isinstance(parsed, int):
            return {
                "version": PAGINATION_CURSOR_VERSION,
                "page": 1,
                "row_offset": max(0, parsed),
                "previous_page_fingerprint": None,
            }
        if not isinstance(parsed, dict) or int(parsed.get("version") or 1) < 2:
            try:
                legacy_offset = int(raw_cursor or 0)
            except (TypeError, ValueError):
                legacy_offset = 0
            return {
                "version": PAGINATION_CURSOR_VERSION,
                "page": 1,
                "row_offset": max(0, legacy_offset),
                "previous_page_fingerprint": None,
            }
        return {
            "version": PAGINATION_CURSOR_VERSION,
            "page": max(1, int(parsed.get("page") or 1)),
            "row_offset": max(0, int(parsed.get("row_offset") or 0)),
            "previous_page_fingerprint": parsed.get("previous_page_fingerprint"),
        }

    @staticmethod
    def _cursor_json(
        page: int, row_offset: int, previous_page_fingerprint: str | None,
    ) -> str:
        return json.dumps({
            "version": PAGINATION_CURSOR_VERSION,
            "page": int(page),
            "row_offset": int(row_offset),
            "previous_page_fingerprint": previous_page_fingerprint,
        }, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record_id(raw: Mapping[str, Any]) -> str | None:
        value = raw.get("id") or raw.get("matchId") or raw.get("fixtureId")
        return str(value) if value is not None else None

    @classmethod
    def _page_fingerprint(cls, rows: list[Any]) -> str:
        identifiers = [cls._record_id(row) for row in rows if isinstance(row, Mapping)]
        stable = sorted(identifiers) if identifiers and all(identifiers) else rows
        return payload_hash(stable)

    @staticmethod
    def _has_next_page(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        value = payload.get("hasNextPage")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return False

    @staticmethod
    def _provider_page(payload: Any) -> int | None:
        if not isinstance(payload, dict):
            return None
        value = payload.get("page") if payload.get("page") is not None else payload.get("pageNo")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def acquire_player_past_match_pages(
        self,
        tour: str,
        player_id: int,
        *,
        resume: bool = True,
        max_pages: int | None = None,
        max_records: int | None = None,
        max_calls: int | None = None,
    ) -> dict[str, Any]:
        """Acquire real provider pages with an idempotent per-page cache."""
        tour = tour.lower()
        item_key = f"past_matches:{tour}:{int(player_id)}"
        state = self.warehouse.get_backfill_state(item_key)
        if resume and state and state.get("status") == "source_exhausted":
            return {
                "tour": tour.upper(), "player_id": int(player_id), "match_ids": [],
                "pages": [], "stop_reason": "source_exhausted", "source_exhausted": True,
                "pages_requested": 0, "calls_made": 0, "cache_hits": 0, "raw_records": 0,
                "unique_matches": 0, "duplicates": 0, "malformed_records": 0,
            }
        cursor = self._parse_cursor((state or {}).get("cursor") if resume else None)
        page = cursor["page"]
        row_offset = cursor["row_offset"]
        previous_fingerprint = cursor["previous_page_fingerprint"]
        seen_fingerprints = {previous_fingerprint} if previous_fingerprint else set()
        calls_at_start = self.metrics.calls_made
        cache_hits_at_start = self.metrics.cache_hits
        pages_seen = pages_requested = 0
        raw_records = duplicates = malformed = 0
        unique_ids: set[str] = set()
        cumulative_dates: list[str] = []
        match_ids: list[str] = []
        page_reports: list[dict[str, Any]] = []
        stop_reason = "limit_reached"
        source_exhausted = False
        self.warehouse.set_backfill_state(
            item_key, "running",
            cursor=self._cursor_json(page, row_offset, previous_fingerprint),
            increment_attempt=True,
        )

        while True:
            if max_pages is not None and pages_seen >= max(0, int(max_pages)):
                stop_reason = "max_pages"
                break
            cache_params = {"tour": tour, "player_id": int(player_id), "page": page}
            page_calls_at_start = self.metrics.calls_made
            key = make_cache_key(
                SOURCE, "getPlayerPastMatches", cache_params, source_version=SOURCE_VERSION,
            )
            entry = self.warehouse.get_raw_response_entry(key)
            if entry is None:
                legacy_key = make_cache_key(
                    SOURCE, "getPlayerPastMatches", cache_params,
                    source_version=SOURCE_VERSION, schema_version=1,
                )
                legacy_entry = self.warehouse.get_raw_response_entry(legacy_key)
                if legacy_entry is not None:
                    key, entry = legacy_key, legacy_entry
            if entry is None and max_calls is not None and self.metrics.calls_made >= max_calls:
                stop_reason = "max_calls"
                break
            request_cursor = self._cursor_json(page, row_offset, previous_fingerprint)
            pages_requested += 1
            try:
                if entry is not None:
                    payload, cache_hit, http_status = entry["payload"], True, entry["status"]
                    self.metrics.cache_hits += 1
                    self.metrics.calls_avoided_via_cache += 1
                else:
                    url = f"{RAPIDAPI_BASE}/{tour}/player/past-matches/{int(player_id)}"
                    payload, key, cache_hit = self.fetch_json(
                        "getPlayerPastMatches", url, cache_params,
                        request_params={"page": page},
                    )
                    stored = self.warehouse.get_raw_response_entry(key)
                    http_status = stored["status"] if stored else 200
            except fetch_data.RapidAPIBudgetExceeded as exc:
                stop_reason = "budget_reached"
                self.warehouse.set_backfill_state(
                    item_key, "budget_reached",
                    cursor=self._cursor_json(page, row_offset, previous_fingerprint),
                    error=str(exc),
                )
                break
            except Exception as exc:
                self.metrics.failures += 1
                self.warehouse.set_backfill_state(
                    item_key, "failed",
                    cursor=self._cursor_json(page, row_offset, previous_fingerprint),
                    error=str(exc),
                )
                return {
                    "tour": tour.upper(), "player_id": int(player_id),
                    "match_ids": match_ids, "pages": page_reports,
                    "stop_reason": "failed", "source_exhausted": False,
                    "pages_requested": pages_requested,
                    "calls_made": self.metrics.calls_made - calls_at_start,
                    "cache_hits": self.metrics.cache_hits - cache_hits_at_start,
                    "raw_records": raw_records, "unique_matches": len(unique_ids),
                    "duplicates": duplicates, "malformed_records": malformed,
                    "error": str(exc),
                }

            rows = _data(payload)
            rows = rows if isinstance(rows, list) else []
            provider_page = self._provider_page(payload)
            has_next = self._has_next_page(payload)
            fingerprint = self._page_fingerprint(rows)
            if provider_page is not None and provider_page != page:
                stop_reason = "non_advancing_page"
                self.warehouse.set_backfill_state(
                    item_key, "failed",
                    cursor=self._cursor_json(page, row_offset, previous_fingerprint),
                    error=f"Provider devolveu página {provider_page} quando foi pedida {page}.",
                )
                break
            if rows and fingerprint in seen_fingerprints:
                stop_reason = "repeated_page"
                self.warehouse.set_backfill_state(
                    item_key, "failed",
                    cursor=self._cursor_json(page, row_offset, previous_fingerprint),
                    error="Provider repetiu a página anterior.",
                )
                break

            pages_seen += 1
            if rows:
                seen_fingerprints.add(fingerprint)
            raw_records += len(rows)
            dates: list[str] = []
            odds_records = bookmaker_count = odds_timestamp_count = ranking_count = missing_dates = 0
            page_malformed = 0
            valid_page_ids: list[str] = []
            for raw in rows:
                if not isinstance(raw, dict):
                    malformed += 1
                    page_malformed += 1
                    continue
                record_id = self._record_id(raw)
                if record_id:
                    valid_page_ids.append(record_id)
                date = raw.get("date") or raw.get("startTime") or raw.get("tourney_date")
                if date:
                    dates.append(str(date))
                else:
                    missing_dates += 1
                if raw.get("odd1") is not None or raw.get("odd2") is not None:
                    odds_records += 1
                bookmaker_count += int(bool(raw.get("bookmaker")))
                odds_timestamp_count += int(bool(raw.get("oddsTimestamp") or raw.get("provider_timestamp")))
                rank_values = (
                    raw.get("player1Rank"), raw.get("rank1"),
                    raw.get("player2Rank"), raw.get("rank2"),
                )
                ranking_count += int(any(value is not None for value in rank_values))

            page_unique_ids = set(valid_page_ids)
            page_duplicates = len(valid_page_ids) - len(page_unique_ids)
            cross_page_duplicates = len(page_unique_ids & unique_ids)
            duplicates += page_duplicates + cross_page_duplicates
            unique_ids.update(page_unique_ids)
            cumulative_dates.extend(dates)

            available = rows[row_offset:]
            if max_records is not None:
                remaining = max(0, int(max_records) - len(match_ids))
                available = available[:remaining]
            consumed_in_page = 0
            for raw in available:
                consumed_in_page += 1
                if not isinstance(raw, dict):
                    continue
                normalized = normalize_past_match(raw, tour=tour, cache_key=key, fetched_at=utc_now())
                if not normalized:
                    malformed += 1
                    page_malformed += 1
                    continue
                quotes = normalized.pop("quotes")
                canonical_id = normalized["canonical_match_id"]
                is_new_for_result = canonical_id not in match_ids
                self.warehouse.upsert_match(normalized)
                for quote in quotes:
                    self.warehouse.add_market_quote(quote)
                if is_new_for_result:
                    match_ids.append(canonical_id)

            next_offset = row_offset + consumed_in_page
            page_reports.append({
                "page": page, "provider_page": provider_page, "http_status": http_status,
                "request_cursor": request_cursor,
                "records_returned": len(rows), "unique_match_ids": len(page_unique_ids),
                "duplicates": page_duplicates + cross_page_duplicates,
                "has_next_page": has_next, "earliest_date": min(dates) if dates else None,
                "latest_date": max(dates) if dates else None,
                "odds_records": odds_records,
                "odds_coverage_pct": round(100 * odds_records / len(rows), 1) if rows else 0.0,
                "bookmaker_identified_count": bookmaker_count,
                "odds_timestamp_count": odds_timestamp_count,
                "ranking_fields_count": ranking_count,
                "missing_dates": missing_dates, "malformed_records": page_malformed,
                "cumulative_malformed_records": malformed,
                "cache_hit": cache_hit,
                "calls_consumed": self.metrics.calls_made - page_calls_at_start,
                "cumulative_earliest_date": min(cumulative_dates) if cumulative_dates else None,
                "cumulative_unique_matches": len(unique_ids),
                "fingerprint": fingerprint,
            })

            if not rows:
                stop_reason, source_exhausted = "empty_page", True
                row_offset = 0
                break
            if max_records is not None and len(match_ids) >= int(max_records):
                stop_reason = "max_records"
                if next_offset < len(rows):
                    row_offset = next_offset
                else:
                    page += 1
                    row_offset = 0
                    previous_fingerprint = fingerprint
                break
            if next_offset < len(rows):
                row_offset = next_offset
                stop_reason = "partial_page"
                break
            if not has_next:
                stop_reason, source_exhausted = "source_exhausted", True
                row_offset = len(rows)
                previous_fingerprint = fingerprint
                break
            previous_fingerprint = fingerprint
            page += 1
            row_offset = 0
            self.warehouse.set_backfill_state(
                item_key, "running",
                cursor=self._cursor_json(page, row_offset, previous_fingerprint),
            )

        status = "source_exhausted" if source_exhausted else (
            "budget_reached" if stop_reason in {"max_calls", "budget_reached"}
            else "failed" if stop_reason in {"repeated_page", "non_advancing_page"}
            else "limit_reached"
        )
        self.warehouse.set_backfill_state(
            item_key, status,
            cursor=self._cursor_json(page, row_offset, previous_fingerprint),
            error=None if status not in {"failed", "budget_reached"} else stop_reason,
        )
        self.metrics.records_stored += len(match_ids)
        return {
            "tour": tour.upper(), "player_id": int(player_id), "match_ids": match_ids,
            "pages": page_reports, "stop_reason": stop_reason,
            "source_exhausted": source_exhausted,
            "pages_requested": pages_requested,
            "calls_made": self.metrics.calls_made - calls_at_start,
            "cache_hits": self.metrics.cache_hits - cache_hits_at_start,
            "raw_records": raw_records, "unique_matches": len(unique_ids),
            "duplicates": duplicates, "malformed_records": malformed,
        }

    def acquire_player_past_matches(
        self, tour: str, player_id: int, *, resume: bool = True,
        max_records: int | None = None, max_pages: int | None = None,
        max_calls: int | None = None,
    ) -> list[str]:
        result = self.acquire_player_past_match_pages(
            tour, player_id, resume=resume, max_records=max_records,
            max_pages=max_pages, max_calls=max_calls,
        )
        return result["match_ids"]


AUDIT_ENDPOINTS = {
    "getPlayerPastMatches": "{base}/{tour}/player/past-matches/{player_id}",
    "getPlayerPerfBreakdown": "{base}/{tour}/player/perf-breakdown/{player_id}",
    "getSinglesRanking": "{base}/{tour}/ranking/singles/",
    "getVsAllStats": "{base}/{tour}/h2h/vs-all-stats/{player_id}/",
}
