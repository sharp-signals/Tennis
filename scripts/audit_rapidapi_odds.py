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
from urllib.parse import quote

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


def _matching_upcoming_event(payload: Any, player_a: str, player_b: str) -> dict[str, Any] | None:
    expected = {fetch_data._normalize_name(player_a), fetch_data._normalize_name(player_b)}
    for item in _iter_dicts(payload):
        first = item.get("player1") or {}
        second = item.get("player2") or {}
        left = first.get("name") if isinstance(first, dict) else None
        right = second.get("name") if isinstance(second, dict) else None
        if {fetch_data._normalize_name(left), fetch_data._normalize_name(right)} == expected:
            return item
    return None


def audit(*, player_a: str, player_b: str, event_date: str, tour: str) -> dict[str, Any]:
    """Consulta as rotas de produção e devolve uma evidência serializável."""
    fetch_data.reset_rapidapi_call_count()
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_upcoming_url = f"{fetch_data.RAPIDAPI_ALL_UPCOMING_URL}/{tour}"
    upcoming = _request(all_upcoming_url, params={"page": 1, "limit": 100})
    matching = _matching_upcoming_event(upcoming.get("payload"), player_a, player_b)

    lookups = []
    event_id = None
    for left, right in ((player_a, player_b), (player_b, player_a)):
        url = f"{fetch_data.RAPIDAPI_EXTEND_BASE}/event/get/{quote(left, safe='')}/{quote(right, safe='')}/{event_date}"
        result = _request(url)
        result["players"] = [left, right]
        lookups.append(result)
        event_id = event_id or _event_id(result.get("payload"))

    endpoints: dict[str, Any] = {}
    if event_id:
        base = fetch_data.RAPIDAPI_EXTEND_BASE
        endpoints = {
            "recent_odds": _request(f"{base}/event/recent-odds/get/{event_id}"),
            "compare": _request(f"{base}/odds/compare/{event_id}", params={"market_id": 1}),
            "biggest_movements": _request(f"{base}/odds/biggest-movements/{event_id}", params={"market_id": 1}),
            "arbitrage": _request(f"{base}/odds/arbitrage/{event_id}", params={"market_id": 1}),
        }
    return {
        "schema_version": 1,
        "captured_at_utc": captured_at,
        "request": {"player_a": player_a, "player_b": player_b, "event_date": event_date, "tour": tour},
        "upcoming": {**upcoming, "matching_event": matching},
        "event_lookups": lookups,
        "event_id": event_id,
        "odds_endpoints": endpoints,
        "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
        "note": "Diagnóstico isolado: não gera relatório, snapshot ou PAPER.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player-a", required=True)
    parser.add_argument("--player-b", required=True)
    parser.add_argument("--event-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--tour", required=True, choices=("atp", "wta"))
    parser.add_argument("--output", default="artifacts/rapidapi_odds_audit/result.json")
    args = parser.parse_args()
    result = audit(player_a=args.player_a, player_b=args.player_b, event_date=args.event_date, tour=args.tour)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "event_id": result["event_id"],
        "rapidapi_calls": result["rapidapi_calls"],
        "upcoming_status": result["upcoming"]["http_status"],
        "odds_endpoint_statuses": {key: value["http_status"] for key, value in result["odds_endpoints"].items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
