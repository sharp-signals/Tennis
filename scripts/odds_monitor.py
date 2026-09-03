"""Monitor SHADOW de movimento de odds para entradas PAPER pré-live abertas.

Não recalcula Fenzobot, pricing ou PAPER. Não usa LLM. Mantém duas camadas
explicitamente separadas:

1. ``market_observation`` — série temporal principal, baseada no feed
   ``upcoming`` observado pelo próprio monitor nesta execução. É uma observação
   atual do feed, mas sem timestamp do bookmaker; essa limitação fica explícita.
2. ``endpoints`` — dados auxiliares de ``recent-odds``, ``compare``, movimentos
   e arbitragem. Quotes com timestamp do fornecedor recebem ``quote_age_seconds``
   e são marcadas FRESH/STALE/UNKNOWN; dados stale nunca são promovidos a odd
   atual nem a arbitragem atual.

O monitor partilha o mesmo guardrail diário RapidAPI do pipeline principal.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src import fetch_data, market_ledger, paper_trading

PAPER_PATH = Path(os.environ.get("ODDS_MONITOR_PAPER_PATH", "data/paper_trades.json"))
OUTPUT_DIR = Path(os.environ.get("ODDS_MONITOR_OUTPUT_DIR", "data/odds_monitor"))
EVENT_MAP_PATH = OUTPUT_DIR / "event_map.json"
STATUS_PATH = OUTPUT_DIR / "status.json"
MARKET_ID = int(os.environ.get("ODDS_MONITOR_MARKET_ID", "1"))
HORIZON_HOURS = int(os.environ.get("ODDS_MONITOR_HORIZON_HOURS", "48"))
FRESH_MAX_AGE_SECONDS = int(
    os.environ.get(
        "ODDS_MONITOR_FRESH_MAX_AGE_SECONDS",
        str(fetch_data.RAPIDAPI_FRESH_MARKET_MAX_AGE_SECONDS),
    )
)
SCHEMA_VERSION = 2


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _provider_time(value: object) -> datetime | None:
    """Aceita Unix seconds/ms ou ISO e normaliza para UTC."""
    if value in (None, ""):
        return None
    try:
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return _parse_utc(value)


def _quote_age_seconds(provider_at: datetime | None, captured_at: datetime) -> int | None:
    if provider_at is None:
        return None
    return max(0, int((captured_at - provider_at).total_seconds()))


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "UNKNOWN"
    return "FRESH" if age_seconds <= FRESH_MAX_AGE_SECONDS else "STALE"


def load_open_paper_entries(path: Path = PAPER_PATH, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Seleciona apenas Moneyline PAPER ainda não liquidado e ainda pré-live."""
    now = now or _utc_now()
    horizon = now + timedelta(hours=HORIZON_HOURS)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return []

    excluded = paper_trading.excluded_keys()
    selected = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("mode") != "PAPER"
            or entry.get("settlement") is not None
            or str(entry.get("key")) in excluded
        ):
            continue
        pregame = entry.get("pregame")
        if not isinstance(pregame, dict) or pregame.get("market_type") != "Moneyline":
            continue
        start = _parse_utc(pregame.get("commence_time_utc"))
        if start is None or not (now < start <= horizon):
            continue
        selected.append(entry)
    return selected


def _entry_to_match(entry: dict[str, Any]) -> dict[str, Any]:
    """Converte o snapshot PAPER no shape mínimo esperado por ``fetch_data``."""
    pregame = entry.get("pregame") or {}
    players = pregame.get("players") or {}
    player_a = players.get("a") or {}
    player_b = players.get("b") or {}
    return {
        "id": pregame.get("match_id"),
        "_tour": pregame.get("tour"),
        "date": pregame.get("commence_time_utc"),
        "tournamentId": pregame.get("tournament_id"),
        "roundId": pregame.get("round_id"),
        "player1Id": player_a.get("id"),
        "player2Id": player_b.get("id"),
        "player1": {"id": player_a.get("id"), "name": player_a.get("name")},
        "player2": {"id": player_b.get("id"), "name": player_b.get("name")},
    }


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def extract_event_id(payload: Any) -> str | None:
    """Extrai eventId sem confundir IDs de jogadores/mercados com o evento."""
    for item in _iter_dicts(payload):
        for key in ("eventId", "event_id"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)

    event_markers = {"participant1", "participant2", "matchId", "startTimestamp", "league", "status"}
    for item in _iter_dicts(payload):
        value = item.get("id")
        if value not in (None, "") and len(event_markers.intersection(item)) >= 2:
            return str(value)
    return None


def _safe_payload(response) -> Any:
    try:
        return response.json()
    except (ValueError, AttributeError):
        text = getattr(response, "text", "") or ""
        return {"raw_text": text[:4000]} if text else None


def _request(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = fetch_data._rapidapi_get(url, params=params)
    except (fetch_data.RapidAPIBudgetExceeded, OSError, RuntimeError) as exc:
        return {"ok": False, "http_status": None, "access": "error", "error": str(exc), "payload": None}

    if response is None:
        return {"ok": False, "http_status": None, "access": "error", "error": "no_response", "payload": None}

    status = int(response.status_code)
    access = "allowed" if status == 200 else "forbidden" if status in {401, 403} else "unavailable"
    return {
        "ok": status == 200,
        "http_status": status,
        "access": access,
        "error": None if status == 200 else f"http_{status}",
        "payload": _safe_payload(response),
    }


def _summarize_quotes(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    fresh = sum(1 for item in quotes if item.get("freshness") == "FRESH")
    stale = sum(1 for item in quotes if item.get("freshness") == "STALE")
    unknown = sum(1 for item in quotes if item.get("freshness") == "UNKNOWN")
    ages = [item["quote_age_seconds"] for item in quotes if isinstance(item.get("quote_age_seconds"), int)]
    return {
        "fresh_max_age_seconds": FRESH_MAX_AGE_SECONDS,
        "quote_count": len(quotes),
        "fresh_count": fresh,
        "stale_count": stale,
        "unknown_count": unknown,
        "freshest_quote_age_seconds": min(ages) if ages else None,
        "quotes": quotes,
    }


def _annotate_recent_odds(result: dict[str, Any], *, captured_at: datetime) -> dict[str, Any]:
    market = (((result.get("payload") or {}).get("result") or {}).get("Full Time Result") or {})
    quotes = []
    if isinstance(market, dict):
        for bookmaker, raw in market.items():
            if not isinstance(raw, dict):
                continue
            provider_at = _provider_time(raw.get("addTime"))
            age = _quote_age_seconds(provider_at, captured_at)
            quotes.append(
                {
                    "bookmaker": str(bookmaker),
                    "od1": raw.get("od1"),
                    "od2": raw.get("od2"),
                    "provider_timestamp": provider_at.isoformat(timespec="seconds") if provider_at else None,
                    "quote_age_seconds": age,
                    "freshness": _freshness(age),
                }
            )
    result["quote_quality"] = _summarize_quotes(quotes)
    return result


def _annotate_compare(result: dict[str, Any], *, captured_at: datetime) -> dict[str, Any]:
    rows = ((result.get("payload") or {}).get("results") or [])
    quotes = []
    if isinstance(rows, list):
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            provider_at = _provider_time(raw.get("sourceAddTime"))
            age = _quote_age_seconds(provider_at, captured_at)
            quotes.append(
                {
                    "bookmaker": str(raw.get("bookmaker") or "N/D"),
                    "od1": raw.get("od1"),
                    "od2": raw.get("od2"),
                    "provider_timestamp": provider_at.isoformat(timespec="seconds") if provider_at else None,
                    "quote_age_seconds": age,
                    "freshness": _freshness(age),
                }
            )
    result["quote_quality"] = _summarize_quotes(quotes)
    return result


def _annotate_arbitrage(result: dict[str, Any], compare_result: dict[str, Any]) -> dict[str, Any]:
    arb = ((result.get("payload") or {}).get("result") or {})
    checked = arb.get("bookmakersChecked")
    try:
        checked = int(checked)
    except (TypeError, ValueError):
        checked = None

    by_bookmaker = {
        str(item.get("bookmaker")): item
        for item in ((compare_result.get("quote_quality") or {}).get("quotes") or [])
        if item.get("bookmaker")
    }
    best = arb.get("bestOdds") or {}
    best_bookmakers = []
    if isinstance(best, dict):
        for outcome in best.values():
            if isinstance(outcome, dict) and outcome.get("bookmaker"):
                best_bookmakers.append(str(outcome["bookmaker"]))

    statuses = [by_bookmaker.get(name, {}).get("freshness", "UNKNOWN") for name in best_bookmakers]
    if statuses and all(status == "FRESH" for status in statuses):
        input_status = "CURRENT_VERIFIED"
    elif any(status == "STALE" for status in statuses):
        input_status = "STALE_INPUTS"
    else:
        input_status = "UNKNOWN_INPUT_FRESHNESS"

    result["input_quality"] = {
        "status": input_status,
        "bookmaker_coverage": "MULTI_BOOKMAKER" if checked is not None and checked >= 2 else "SINGLE_BOOKMAKER",
        "bookmakers_checked": checked,
        "best_odds_bookmakers": best_bookmakers,
        "current_arbitrage_eligible": input_status == "CURRENT_VERIFIED" and checked is not None and checked >= 2,
    }
    return result


def _primary_market_observation(match: dict[str, Any]) -> dict[str, Any]:
    """Cria a série principal a partir do feed observado nesta execução."""
    odds, provenance = fetch_data.fetch_rapidapi_embedded_moneyline_with_provenance(match)
    if not odds or not provenance:
        return {
            "available": False,
            "series_eligible": False,
            "freshness": "UNAVAILABLE",
            "odds": None,
            "source": "RapidAPI upcoming feed",
        }

    captured_at = _parse_utc(provenance.get("captured_at_utc"))
    capture_age = _quote_age_seconds(captured_at, _utc_now()) if captured_at else None
    return {
        "available": True,
        "series_eligible": True,
        "freshness": "OBSERVED_AT_CAPTURE_UNVERIFIED_PROVIDER_TIME",
        "odds": dict(odds),
        "source": provenance.get("source"),
        "endpoint": provenance.get("endpoint"),
        "captured_at_utc": provenance.get("captured_at_utc"),
        "capture_age_seconds": capture_age,
        "provider_timestamp": None,
        "quote_age_seconds": None,
        "bookmaker": None,
        "raw_payload_sha256": provenance.get("raw_payload_sha256"),
        "identity_mapping_status": provenance.get("identity_mapping_status") or "VERIFIED",
        "caveat": "Feed observado nesta execução; hora de atualização do bookmaker não fornecida.",
    }


def _read_event_map(path: Path = EVENT_MAP_PATH) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": SCHEMA_VERSION, "events": {}}
    if not isinstance(document, dict) or not isinstance(document.get("events"), dict):
        return {"schema_version": SCHEMA_VERSION, "events": {}}
    document["schema_version"] = SCHEMA_VERSION
    return document


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _resolve_event(entry: dict[str, Any], event_map: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    key = str(entry.get("key") or "")
    cached = event_map["events"].get(key)
    if isinstance(cached, dict) and cached.get("event_id"):
        return str(cached["event_id"]), {
            "cached": True,
            "lookup": cached.get("lookup"),
            "participant1": cached.get("participant1"),
            "participant2": cached.get("participant2"),
            "identity_mapping_status": cached.get("identity_mapping_status") or "UNVERIFIED",
        }

    pregame = entry["pregame"]
    players = pregame.get("players") or {}
    player_a = ((players.get("a") or {}).get("name") or "").strip()
    player_b = ((players.get("b") or {}).get("name") or "").strip()
    start = _parse_utc(pregame.get("commence_time_utc"))
    if not player_a or not player_b or start is None:
        return None, {"cached": False, "error": "missing_players_or_start"}

    dates = [(start + timedelta(days=offset)).date().isoformat() for offset in (0, -1, 1)]
    attempts = []
    for date_only in dates:
        for left, right in ((player_a, player_b), (player_b, player_a)):
            url = f"{fetch_data.RAPIDAPI_EXTEND_BASE}/event/get/{quote(left, safe='')}/{quote(right, safe='')}/{date_only}"
            result = _request(url)
            attempts.append({"players": [left, right], "date": date_only, "http_status": result["http_status"]})
            if result["access"] == "forbidden":
                return None, {"cached": False, "access": "forbidden", "attempts": attempts}
            if result["ok"]:
                verified = fetch_data._validated_event_record(result["payload"], _entry_to_match(entry))
                event_id = str(verified.get("event_id")) if verified and verified.get("valid") else extract_event_id(result["payload"])
                if event_id:
                    participant1 = verified.get("participant1") if verified and verified.get("valid") else None
                    participant2 = verified.get("participant2") if verified and verified.get("valid") else None
                    event_map["events"][key] = {
                        "event_id": event_id,
                        "resolved_at_utc": _utc_now().isoformat(timespec="seconds"),
                        "lookup": attempts[-1],
                        "participant1": participant1,
                        "participant2": participant2,
                        "identity_mapping_status": "VERIFIED" if participant1 and participant2 else "UNVERIFIED",
                    }
                    return event_id, {
                        "cached": False,
                        "lookup": attempts[-1],
                        "participant1": participant1,
                        "participant2": participant2,
                        "identity_mapping_status": "VERIFIED" if participant1 and participant2 else "UNVERIFIED",
                    }
    return None, {"cached": False, "access": "unresolved", "attempts": attempts}


def _payload_fingerprint(value: dict[str, Any]) -> str:
    material = {
        key: value.get(key)
        for key in ("paper_key", "event_id", "market_observation", "endpoints")
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _last_fingerprint(path: Path) -> str | None:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (FileNotFoundError, OSError):
        return None
    if not lines:
        return None
    try:
        return json.loads(lines[-1]).get("fingerprint")
    except (json.JSONDecodeError, AttributeError):
        return None


def _append_snapshot(snapshot: dict[str, Any], *, output_dir: Path = OUTPUT_DIR) -> bool:
    day = snapshot["captured_at_utc"][:10]
    path = output_dir / f"{day}.jsonl"
    fingerprint = _payload_fingerprint(snapshot)
    snapshot["fingerprint"] = fingerprint
    if _last_fingerprint(path) == fingerprint:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return True


def _mapped_provider_odds(
    match: dict[str, Any],
    event_resolution: dict[str, Any],
    quote: dict[str, Any],
) -> tuple[dict[str, float] | None, str]:
    """Mapeia od1/od2 apenas quando a ordem veio do event/get já pedido."""
    player_a = str((match.get("player1") or {}).get("name") or "")
    player_b = str((match.get("player2") or {}).get("name") or "")
    participant1 = str(event_resolution.get("participant1") or "")
    participant2 = str(event_resolution.get("participant2") or "")
    if not player_a or not player_b or not participant1 or not participant2:
        return None, "UNVERIFIED"
    expected = {fetch_data._normalize_name(player_a), fetch_data._normalize_name(player_b)}
    actual = {fetch_data._normalize_name(participant1), fetch_data._normalize_name(participant2)}
    if expected != actual:
        return None, "UNVERIFIED"
    try:
        od1, od2 = float(quote.get("od1")), float(quote.get("od2"))
    except (TypeError, ValueError):
        return None, "VERIFIED"
    if od1 <= 1 or od2 <= 1:
        return None, "VERIFIED"
    if fetch_data._normalize_name(participant1) == fetch_data._normalize_name(player_a):
        return {player_a: od1, player_b: od2}, "VERIFIED"
    return {player_a: od2, player_b: od1}, "VERIFIED"


def _persist_market_ledger_best_effort(
    entry: dict[str, Any],
    match: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    ledger_root: Path = market_ledger.DEFAULT_ROOT,
) -> dict[str, Any]:
    """Normaliza apenas respostas já recolhidas; não chama qualquer endpoint."""
    results = []
    primary = snapshot.get("market_observation") or {}
    if primary.get("available") and isinstance(primary.get("odds"), dict):
        results.append(market_ledger.record_market_batch_best_effort(
            match,
            primary["odds"],
            {
                "source": primary.get("source"),
                "endpoint": primary.get("endpoint"),
                "event_id": snapshot.get("event_id"),
                "captured_at_utc": primary.get("captured_at_utc"),
                "capture_kind": "feed_observed_at_capture",
                "provider_timestamp": primary.get("provider_timestamp"),
                "bookmaker": primary.get("bookmaker"),
                "freshness_status": primary.get("freshness"),
                "identity_mapping_status": primary.get("identity_mapping_status") or "VERIFIED",
                "raw_payload_sha256": primary.get("raw_payload_sha256"),
                "github_run_id": os.environ.get("ODDS_MONITOR_GITHUB_RUN_ID"),
            },
            role="SHADOW_MONITOR",
            pipeline="ODDS_MONITOR",
            root=ledger_root,
        ))

    resolution = snapshot.get("event_resolution") or {}
    captured_at = snapshot.get("captured_at_utc")
    endpoint_specs = (
        ("recent_odds", f"{fetch_data.RAPIDAPI_EXTEND_BASE}/event/recent-odds/get/{snapshot.get('event_id')}", "RapidAPI Tennis API / recent-odds"),
        ("compare", f"{fetch_data.RAPIDAPI_EXTEND_BASE}/odds/compare/{snapshot.get('event_id')}", "RapidAPI Tennis API / odds compare"),
    )
    for endpoint_key, endpoint_url, source_name in endpoint_specs:
        endpoint = (snapshot.get("endpoints") or {}).get(endpoint_key) or {}
        payload = endpoint.get("payload")
        raw_hash = market_ledger.payload_sha256(payload) if payload is not None else None
        for quote in (endpoint.get("quote_quality") or {}).get("quotes") or []:
            odds, mapping_status = _mapped_provider_odds(match, resolution, quote)
            if not odds:
                continue
            # Em recent-odds, addTime é metadado comprovadamente pouco fiável;
            # a observação temporal é a resposta recebida nesta execução. No
            # compare mantemos a classificação temporal do próprio endpoint.
            freshness_status = (
                "OBSERVED_AT_CAPTURE" if endpoint_key == "recent_odds"
                else quote.get("freshness")
            )
            provider_timestamp_status = (
                "unreliable_for_freshness" if endpoint_key == "recent_odds"
                else "AVAILABLE" if quote.get("provider_timestamp") else "UNAVAILABLE"
            )
            results.append(market_ledger.record_market_batch_best_effort(
                match,
                odds,
                {
                    "source": source_name,
                    "endpoint": endpoint_url,
                    "event_id": snapshot.get("event_id"),
                    "captured_at_utc": captured_at,
                    "capture_kind": "monitor_response_observed_at_capture",
                    "provider_timestamp": quote.get("provider_timestamp"),
                    "provider_timestamp_status": provider_timestamp_status,
                    "bookmaker": quote.get("bookmaker"),
                    "freshness_status": freshness_status,
                    "identity_mapping_status": mapping_status,
                    "provider_side_a": "od1" if fetch_data._normalize_name(resolution.get("participant1")) == fetch_data._normalize_name((match.get("player1") or {}).get("name")) else "od2",
                    "provider_side_b": "od2" if fetch_data._normalize_name(resolution.get("participant1")) == fetch_data._normalize_name((match.get("player1") or {}).get("name")) else "od1",
                    "raw_payload_sha256": raw_hash,
                    "github_run_id": os.environ.get("ODDS_MONITOR_GITHUB_RUN_ID"),
                },
                role="SHADOW_MONITOR",
                pipeline="ODDS_MONITOR",
                root=ledger_root,
            ))
    return {
        "recorded": sum(len(item.get("observation_ids") or []) for item in results),
        "errors": [error for item in results for error in (item.get("errors") or [])],
    }


def monitor_entry(
    entry: dict[str, Any],
    event_map: dict[str, Any],
    *,
    match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pregame = entry["pregame"]
    match = match or _entry_to_match(entry)
    event_id, resolution = _resolve_event(entry, event_map)
    captured_at_text = _utc_now().isoformat(timespec="seconds")
    captured_at = _parse_utc(captured_at_text) or _utc_now()
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "mode": "SHADOW",
        "captured_at_utc": captured_at_text,
        "paper_key": entry.get("key"),
        "snapshot_key": pregame.get("snapshot_key"),
        "match_id": pregame.get("match_id"),
        "commence_time_utc": pregame.get("commence_time_utc"),
        "players": pregame.get("players"),
        "selected_player": pregame.get("selected_player"),
        "signal_odd": pregame.get("odd"),
        "signal_fair_odd": pregame.get("fair_odd"),
        "signal_edge_pct": pregame.get("expected_edge_pct"),
        "market_id": MARKET_ID,
        "event_id": event_id,
        "event_resolution": resolution,
        "market_observation": _primary_market_observation(match),
        "endpoints": {},
    }
    if not event_id:
        return snapshot

    base = fetch_data.RAPIDAPI_EXTEND_BASE
    recent = _annotate_recent_odds(
        _request(f"{base}/event/recent-odds/get/{event_id}"),
        captured_at=captured_at,
    )
    compare = _annotate_compare(
        _request(f"{base}/odds/compare/{event_id}", params={"market_id": MARKET_ID}),
        captured_at=captured_at,
    )
    movements = _request(f"{base}/odds/biggest-movements/{event_id}", params={"market_id": MARKET_ID})
    movements["interpretation"] = "HISTORICAL_AUXILIARY_NOT_CURRENT_QUOTE"
    arbitrage = _annotate_arbitrage(
        _request(f"{base}/odds/arbitrage/{event_id}", params={"market_id": MARKET_ID}),
        compare,
    )
    snapshot["endpoints"] = {
        "recent_odds": recent,
        "compare": compare,
        "biggest_movements": movements,
        "arbitrage": arbitrage,
    }
    return snapshot


def run() -> dict[str, Any]:
    fetch_data.reset_rapidapi_call_count()
    now = _utc_now()
    entries = load_open_paper_entries(now=now)
    if not entries:
        fetch_data.clear_rapidapi_checkpoint()
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": "SHADOW",
            "trigger": os.environ.get("ODDS_MONITOR_TRIGGER", "unknown"),
            "eligible_paper_entries": 0,
            "captured_entries": 0,
            "new_history_records": 0,
            "rapidapi_calls": 0,
            "access_counts": {},
            "llm_calls": 0,
        }

    matches = [_entry_to_match(entry) for entry in entries]
    feed_prepare_error = None
    try:
        fetch_data.prepare_rapidapi_odds_index(matches)
    except (fetch_data.RapidAPIBudgetExceeded, OSError, RuntimeError, ValueError) as exc:
        feed_prepare_error = str(exc)

    event_map = _read_event_map()
    captures = []
    written = 0
    ledger_records = 0
    ledger_errors = []

    try:
        for entry, match in zip(entries, matches):
            snapshot = monitor_entry(entry, event_map, match=match)
            captures.append(snapshot)
            if _append_snapshot(snapshot):
                written += 1
            ledger_result = _persist_market_ledger_best_effort(entry, match, snapshot)
            ledger_records += int(ledger_result.get("recorded") or 0)
            ledger_errors.extend(ledger_result.get("errors") or [])
    finally:
        _atomic_json(EVENT_MAP_PATH, event_map)
        access_counts: dict[str, int] = {}
        primary_series_records = 0
        recent_fresh = 0
        recent_stale = 0
        recent_unknown = 0
        current_arbitrage_eligible = 0
        stale_arbitrage_inputs = 0
        single_bookmaker_arbitrage = 0

        for capture in captures:
            if (capture.get("market_observation") or {}).get("series_eligible"):
                primary_series_records += 1
            for endpoint in capture.get("endpoints", {}).values():
                access = str(endpoint.get("access") or "unknown")
                access_counts[access] = access_counts.get(access, 0) + 1

            recent_quality = ((capture.get("endpoints") or {}).get("recent_odds") or {}).get("quote_quality") or {}
            recent_fresh += int(recent_quality.get("fresh_count") or 0)
            recent_stale += int(recent_quality.get("stale_count") or 0)
            recent_unknown += int(recent_quality.get("unknown_count") or 0)

            arb_quality = ((capture.get("endpoints") or {}).get("arbitrage") or {}).get("input_quality") or {}
            if arb_quality.get("current_arbitrage_eligible"):
                current_arbitrage_eligible += 1
            if arb_quality.get("status") == "STALE_INPUTS":
                stale_arbitrage_inputs += 1
            if arb_quality.get("bookmaker_coverage") == "SINGLE_BOOKMAKER":
                single_bookmaker_arbitrage += 1

        status = {
            "schema_version": SCHEMA_VERSION,
            "mode": "SHADOW",
            "trigger": os.environ.get("ODDS_MONITOR_TRIGGER", "unknown"),
            "github_run_id": os.environ.get("ODDS_MONITOR_GITHUB_RUN_ID"),
            "last_run_at_utc": _utc_now().isoformat(timespec="seconds"),
            "eligible_paper_entries": len(entries),
            "captured_entries": len(captures),
            "new_history_records": written,
            "market_ledger_records": ledger_records,
            "market_ledger_errors": ledger_errors[:20],
            "primary_series_records": primary_series_records,
            "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
            "access_counts": access_counts,
            "recent_odds_quote_quality": {
                "fresh": recent_fresh,
                "stale": recent_stale,
                "unknown": recent_unknown,
                "fresh_max_age_seconds": FRESH_MAX_AGE_SECONDS,
            },
            "arbitrage_quality": {
                "current_eligible_entries": current_arbitrage_eligible,
                "stale_input_entries": stale_arbitrage_inputs,
                "single_bookmaker_entries": single_bookmaker_arbitrage,
            },
            "feed_prepare_error": feed_prepare_error,
            "llm_calls": 0,
        }
        _atomic_json(STATUS_PATH, status)
        try:
            market_ledger.rotate_archives()
        except Exception as exc:
            status["market_ledger_errors"].append(f"rotation:{type(exc).__name__}:{exc}")
            _atomic_json(STATUS_PATH, status)
        fetch_data.persist_rapidapi_usage(status="odds_monitor", matches=len(captures))
    return status


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
