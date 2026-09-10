"""Auditoria manual das rotas RapidAPI de odds, sem relatório nem PAPER.

Uso no GitHub Actions: indicar jogadores, tour e data do evento. O resultado
é guardado como artefacto de diagnóstico, nunca em ``docs/`` ou nos ledgers.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import fetch_data


SAFE_HEADERS = {"date", "age", "cache-control", "etag", "last-modified", "x-cache", "via"}


def _safe_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {}) or {}
    return {
        str(key).lower(): str(value)
        for key, value in headers.items()
        if str(key).lower() in SAFE_HEADERS
    }


def _payload(response: Any) -> Any:
    try:
        return response.json()
    except (ValueError, AttributeError):
        text = str(getattr(response, "text", "") or "")
        return {"raw_text": text[:4000]} if text else None


def _request(url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = fetch_data._rapidapi_get(url, **kwargs)
    except (fetch_data.RapidAPIBudgetExceeded, OSError, RuntimeError) as exc:
        return {"http_status": None, "error": str(exc), "headers": {}, "payload": None}
    return {
        "http_status": getattr(response, "status_code", None),
        "error": None,
        "headers": _safe_headers(response),
        "payload": _payload(response),
    }


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _event_id(value: Any) -> str | None:
    for item in _iter_dicts(value):
        candidate = item.get("eventId") or item.get("event_id")
        if candidate not in (None, ""):
            return str(candidate)
    for item in _iter_dicts(value):
        markers = {"participant1", "participant2", "matchId", "startTimestamp", "league", "status"}
        if item.get("id") not in (None, "") and len(markers.intersection(item)) >= 2:
            return str(item["id"])
    return None


def _matching_upcoming_event(
    payload: Any,
    player_a: str,
    player_b: str,
    player_a_id: int | None = None,
    player_b_id: int | None = None,
) -> dict[str, Any] | None:
    expected_ids = {str(player_a_id), str(player_b_id)} if None not in (player_a_id, player_b_id) else None
    expected = {fetch_data._normalize_name(player_a), fetch_data._normalize_name(player_b)}
    for item in _iter_dicts(payload):
        first = item.get("player1") or {}
        second = item.get("player2") or {}
        provider_ids = {
            str(first.get("id") or first.get("playerId")),
            str(second.get("id") or second.get("playerId")),
        } if isinstance(first, dict) and isinstance(second, dict) else None
        if expected_ids and provider_ids == expected_ids:
            return item
        left = first.get("name") if isinstance(first, dict) else None
        right = second.get("name") if isinstance(second, dict) else None
        if {
            fetch_data._rapidapi_exact_name_key(left),
            fetch_data._rapidapi_exact_name_key(right),
        } == {
            fetch_data._rapidapi_exact_name_key(name) for name in expected
        }:
            return item
    return None


def _match_from_audit_input(
    *, player_a: str, player_b: str, event_date: str, tour: str,
    player_a_id: int | None, player_b_id: int | None,
    tournament_id: int | None, round_id: int | None,
    upcoming_match: dict[str, Any] | None,
) -> dict[str, Any]:
    row = upcoming_match or {}
    start = row.get("date") or row.get("startTime") or row.get("startTimestamp")
    if not start:
        start = f"{event_date}T12:00:00+00:00"
    tournament = row.get("tournament") or {}
    return {
        "id": row.get("id") or f"audit:{tour}:{event_date}:{player_a}:{player_b}",
        "_tour": tour,
        "date": start,
        "tournament_name": (
            tournament.get("name") if isinstance(tournament, dict) else str(tournament or "")
        ) or row.get("tournamentName"),
        "player1Id": player_a_id,
        "player2Id": player_b_id,
        "player1": {"id": player_a_id, "name": player_a},
        "player2": {"id": player_b_id, "name": player_b},
        "tournamentId": tournament_id or row.get("tournamentId") or tournament.get("id"),
        "roundId": round_id or row.get("roundId") or (row.get("round") or {}).get("id"),
    }


def _embedded_summary(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {"available": False, "role": "OBSERVATION_ONLY", "paper_eligible": False}
    first, second = event.get("player1") or {}, event.get("player2") or {}
    odds = event.get("odds") or {}
    values = [first.get("odd") or odds.get("k1"), second.get("odd") or odds.get("k2")]
    return {
        "available": all(value not in (None, "") for value in values),
        "raw_decimal_odds": values,
        "bookmaker": None,
        "provider_timestamp": None,
        "role": "OBSERVATION_ONLY",
        "market_integrity_compatible": False,
        "paper_eligible": False,
    }


def _market_integrity_compatible(provenance: dict[str, Any] | None) -> bool:
    status = str((provenance or {}).get("market_integrity", {}).get("status") or "").upper()
    return status in {"AVAILABLE", "PASS"}


def audit(
    *, player_a: str, player_b: str, event_date: str, tour: str,
    player_a_id: int | None = None, player_b_id: int | None = None,
    tournament_id: int | None = None, round_id: int | None = None,
    audit_the_odds: bool = False,
) -> dict[str, Any]:
    """Consulta as rotas de produção e devolve uma evidência serializável."""
    fetch_data.reset_rapidapi_call_count()
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_upcoming_url = f"{fetch_data.RAPIDAPI_ALL_UPCOMING_URL}/{tour}"
    upcoming = _request(all_upcoming_url, params={"page": 1, "limit": 100})
    matching = _matching_upcoming_event(
        upcoming.get("payload"), player_a, player_b, player_a_id, player_b_id,
    )
    match = _match_from_audit_input(
        player_a=player_a, player_b=player_b, event_date=event_date, tour=tour,
        player_a_id=player_a_id, player_b_id=player_b_id,
        tournament_id=tournament_id, round_id=round_id, upcoming_match=matching,
    )
    extend_url = f"{fetch_data.RAPIDAPI_EXTEND_BASE}/events/upcoming/{tour}"
    extend = _request(extend_url, params={"page": 1, "limit": 100})
    record = (
        fetch_data._validated_event_record_by_match_id(
            matching, match, require_explicit_event_id=True,
        )
        or fetch_data._validated_event_record(
            matching, match, require_explicit_event_id=True,
        )
    )
    identity_source = None
    if record and record.get("valid"):
        identity_source = f"embedded_upcoming:{record.get('identity_source')}"
    else:
        record = (
            fetch_data._validated_event_record_by_match_id(extend.get("payload"), match)
            or fetch_data._validated_event_record(extend.get("payload"), match)
        )
        if record and record.get("valid"):
            identity_source = f"extend_upcoming:{record.get('identity_source')}"
    if record and record.get("valid"):
        record = dict(record)
        record["identity_source"] = identity_source
        fetch_data._RAPIDAPI_EVENT_INDEX[f"{tour}:fixture:{match['id']}"] = record
    else:
        # Usa exatamente o fallback limitado de produção. Não há produto
        # cartesiano escondido dentro da ferramenta de auditoria.
        record = fetch_data._rapidapi_event_record_for_match(match)
        identity_source = (record or {}).get("identity_source")
    event_id = str(record.get("event_id")) if record and record.get("valid") else None

    endpoints: dict[str, Any] = {}
    if event_id:
        odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        endpoints["recent_odds"] = {
            "available": bool(odds), "odds": odds, "provenance": provenance,
            "market_integrity_compatible": _market_integrity_compatible(provenance),
        }
        endpoints["compare"] = _request(
            f"{fetch_data.RAPIDAPI_EXTEND_BASE}/odds/compare/{event_id}", params={"market_id": 1},
        )
    the_odds = {"status": "NOT_RUN_DEFAULT_OFF", "paper_eligible": False}
    if audit_the_odds:
        fetch_data.prepare_the_odds_market_index([match])
        independent_odds, independent_provenance = fetch_data.fetch_the_odds_moneyline_with_provenance(match)
        the_odds = {
            "status": "AVAILABLE" if independent_odds else "UNAVAILABLE",
            "odds": independent_odds,
            "provenance": independent_provenance,
            "paper_eligible": False,
            "note": "Controlled comparison only; never promoted by this audit.",
        }
    identity_metrics = fetch_data.get_rapidapi_identity_metrics()
    diagnostic = next((
        item for item in identity_metrics.get("matches", [])
        if str(item.get("match_key")) == str(match.get("id"))
    ), {})
    return {
        "schema_version": 2,
        "captured_at_utc": captured_at,
        "request": {"player_a": player_a, "player_b": player_b, "event_date": event_date, "tour": tour},
        "upcoming": {**upcoming, "matching_event": matching},
        "embedded_odds": _embedded_summary(matching),
        "extend_upcoming": extend,
        "identity": {
            "verified": bool(record and record.get("valid")),
            "source": identity_source,
            "reason": None if record and record.get("valid") else (
                (record or {}).get("reason")
                or diagnostic.get("unavailable_reason")
                or "event_identity_unavailable"
            ),
            "diagnostics": identity_metrics,
        },
        "event_id": event_id,
        "odds_endpoints": endpoints,
        "the_odds_api": the_odds,
        "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
        "note": "Diagnóstico isolado: não gera relatório, snapshot ou PAPER.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player-a", required=True)
    parser.add_argument("--player-b", required=True)
    parser.add_argument("--event-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tour", required=True, choices=("atp", "wta"))
    parser.add_argument("--player-a-id", type=int)
    parser.add_argument("--player-b-id", type=int)
    parser.add_argument("--tournament-id", type=int)
    parser.add_argument("--round-id", type=int)
    parser.add_argument("--audit-the-odds", action="store_true")
    parser.add_argument("--output", default="artifacts/rapidapi_odds_audit/result.json")
    args = parser.parse_args()
    result = audit(
        player_a=args.player_a, player_b=args.player_b, event_date=args.event_date, tour=args.tour,
        player_a_id=args.player_a_id, player_b_id=args.player_b_id,
        tournament_id=args.tournament_id, round_id=args.round_id,
        audit_the_odds=args.audit_the_odds,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "event_id": result["event_id"],
        "rapidapi_calls": result["rapidapi_calls"],
        "upcoming_status": result["upcoming"]["http_status"],
        "odds_endpoint_statuses": {
            key: value.get("http_status", "AVAILABLE" if value.get("available") else "UNAVAILABLE")
            for key, value in result["odds_endpoints"].items()
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
