"""Monitor SHADOW de movimento de odds para entradas PAPER pré-live abertas.

Não recalcula Fenzobot, pricing ou PAPER. Não usa LLM. Consulta apenas a camada
RapidAPI Extend/Odds, preserva respostas observadas com timestamp e partilha o
mesmo guardrail diário de chamadas já usado pelo pipeline principal.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src import fetch_data

PAPER_PATH = Path(os.environ.get("ODDS_MONITOR_PAPER_PATH", "data/paper_trades.json"))
OUTPUT_DIR = Path(os.environ.get("ODDS_MONITOR_OUTPUT_DIR", "data/odds_monitor"))
EVENT_MAP_PATH = OUTPUT_DIR / "event_map.json"
STATUS_PATH = OUTPUT_DIR / "status.json"
MARKET_ID = int(os.environ.get("ODDS_MONITOR_MARKET_ID", "1"))
HORIZON_HOURS = int(os.environ.get("ODDS_MONITOR_HORIZON_HOURS", "48"))
SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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

    selected = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("mode") != "PAPER" or entry.get("settlement") is not None:
            continue
        pregame = entry.get("pregame")
        if not isinstance(pregame, dict) or pregame.get("market_type") != "Moneyline":
            continue
        start = _parse_utc(pregame.get("commence_time_utc"))
        if start is None or not (now < start <= horizon):
            continue
        selected.append(entry)
    return selected


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


def _read_event_map(path: Path = EVENT_MAP_PATH) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": SCHEMA_VERSION, "events": {}}
    if not isinstance(document, dict) or not isinstance(document.get("events"), dict):
        return {"schema_version": SCHEMA_VERSION, "events": {}}
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
        return str(cached["event_id"]), {"cached": True, "lookup": cached.get("lookup")}

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
                event_id = extract_event_id(result["payload"])
                if event_id:
                    event_map["events"][key] = {
                        "event_id": event_id,
                        "resolved_at_utc": _utc_now().isoformat(timespec="seconds"),
                        "lookup": attempts[-1],
                    }
                    return event_id, {"cached": False, "lookup": attempts[-1]}
    return None, {"cached": False, "access": "unresolved", "attempts": attempts}


def _payload_fingerprint(value: dict[str, Any]) -> str:
    material = {key: value.get(key) for key in ("paper_key", "event_id", "endpoints")}
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


def monitor_entry(entry: dict[str, Any], event_map: dict[str, Any]) -> dict[str, Any]:
    pregame = entry["pregame"]
    event_id, resolution = _resolve_event(entry, event_map)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "mode": "SHADOW",
        "captured_at_utc": _utc_now().isoformat(timespec="seconds"),
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
        "endpoints": {},
    }
    if not event_id:
        return snapshot

    base = fetch_data.RAPIDAPI_EXTEND_BASE
    snapshot["endpoints"] = {
        "recent_odds": _request(f"{base}/event/recent-odds/get/{event_id}"),
        "compare": _request(f"{base}/odds/compare/{event_id}", params={"market_id": MARKET_ID}),
        "biggest_movements": _request(
            f"{base}/odds/biggest-movements/{event_id}", params={"market_id": MARKET_ID}
        ),
        "arbitrage": _request(f"{base}/odds/arbitrage/{event_id}", params={"market_id": MARKET_ID}),
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
            "eligible_paper_entries": 0,
            "captured_entries": 0,
            "new_history_records": 0,
            "rapidapi_calls": 0,
            "access_counts": {},
            "llm_calls": 0,
        }

    event_map = _read_event_map()
    captures = []
    written = 0

    try:
        for entry in entries:
            snapshot = monitor_entry(entry, event_map)
            captures.append(snapshot)
            if _append_snapshot(snapshot):
                written += 1
    finally:
        _atomic_json(EVENT_MAP_PATH, event_map)
        access_counts: dict[str, int] = {}
        for capture in captures:
            for endpoint in capture.get("endpoints", {}).values():
                access = str(endpoint.get("access") or "unknown")
                access_counts[access] = access_counts.get(access, 0) + 1
        status = {
            "schema_version": SCHEMA_VERSION,
            "mode": "SHADOW",
            "last_run_at_utc": _utc_now().isoformat(timespec="seconds"),
            "eligible_paper_entries": len(entries),
            "captured_entries": len(captures),
            "new_history_records": written,
            "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
            "access_counts": access_counts,
            "llm_calls": 0,
        }
        _atomic_json(STATUS_PATH, status)
        fetch_data.persist_rapidapi_usage(status="odds_monitor", matches=len(captures))
    return status


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
