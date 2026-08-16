"""Snapshots pre-match imutaveis para calibracao futura, sem fuga temporal."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
DEFAULT_PATH = Path("data/calibration_snapshots.json")
MAX_ENTRIES = 5000

_LOCK = threading.Lock()
_METRIC_KEYS = (
    "market_adjusted_form_a", "market_adjusted_form_b",
    "opposition_quality_a", "opposition_quality_b",
    "pressure_profile_a", "pressure_profile_b",
    "surface_momentum_a", "surface_momentum_b",
    "recent_form_a", "recent_form_b",
    "serve_return_stats_a", "serve_return_stats_b",
    "deciding_set_stats_a", "deciding_set_stats_b",
    "set1_comeback_stats_a", "set1_comeback_stats_b",
    "ranking_a", "ranking_b", "features", "divergencia",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snapshot_key(payload: Mapping[str, Any]) -> str:
    match_id = payload.get("match_id")
    if match_id is not None:
        return f"{str(payload.get('tour') or '').lower()}:{match_id}"
    material = "|".join(str(payload.get(key) or "") for key in (
        "tour", "player_a_id", "player_b_id", "commence_time_utc",
    ))
    return "fallback:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def build_snapshot(payload: Mapping[str, Any], result: Mapping[str, Any] | None = None,
                   analyzed_at_utc: str | None = None) -> dict[str, Any]:
    """Cria uma fotografia compacta apenas com informacao conhecida pre-jogo."""
    snapshot = {
        "key": _snapshot_key(payload),
        "match_id": payload.get("match_id"),
        "tour": payload.get("tour"),
        "tournament_id": payload.get("tournament_id"),
        "tournament": payload.get("tournament"),
        "surface": payload.get("surface"),
        "commence_time_utc": payload.get("commence_time_utc"),
        "analyzed_at_utc": analyzed_at_utc or _utc_now(),
        "player_a": {"id": payload.get("player_a_id"), "name": payload.get("player_a")},
        "player_b": {"id": payload.get("player_b_id"), "name": payload.get("player_b")},
        "market_odds_decimal": payload.get("market_odds_decimal"),
        "metrics": {key: payload.get(key) for key in _METRIC_KEYS if payload.get(key) is not None},
        "analysis": {
            key: result.get(key) for key in ("flag", "signal_strength") if result and result.get(key) is not None
        },
        "outcome": None,
    }
    return snapshot


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("snapshots"), list):
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    return value


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def upsert_snapshots(snapshots: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH,
                     max_entries: int = MAX_ENTRIES) -> int:
    """Insere snapshots; uma repeticao nunca reescreve a fotografia original."""
    with _LOCK:
        document = _read(path)
        existing = {item.get("key"): item for item in document["snapshots"] if item.get("key")}
        added = 0
        for snapshot in snapshots:
            key = snapshot.get("key")
            if key and key not in existing:
                existing[key] = dict(snapshot)
                added += 1
        ordered = sorted(existing.values(), key=lambda item: item.get("analyzed_at_utc") or "")
        document["snapshots"] = ordered[-max_entries:]
        document["updated_at_utc"] = _utc_now()
        _write(path, document)
        return added


def settle_from_matches(matches: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH) -> int:
    """Preenche resultados usando jogos terminados; nao altera dados pre-match."""
    completed = {}
    for match in matches:
        match_id = match.get("id")
        winner_id = match.get("match_winner")
        if match_id is None or winner_id is None:
            continue
        if str(match.get("result_type") or "").lower() not in {"completed", "finished"}:
            continue
        completed[str(match_id)] = match

    with _LOCK:
        document = _read(path)
        settled = 0
        for snapshot in document["snapshots"]:
            if snapshot.get("outcome") is not None:
                continue
            match = completed.get(str(snapshot.get("match_id")))
            if not match:
                continue
            winner_id = match.get("match_winner")
            a_id = (snapshot.get("player_a") or {}).get("id")
            b_id = (snapshot.get("player_b") or {}).get("id")
            if str(winner_id) == str(a_id):
                side = "a"
            elif str(winner_id) == str(b_id):
                side = "b"
            else:
                continue
            snapshot["outcome"] = {
                "winner_side": side,
                "winner_id": winner_id,
                "result": match.get("result"),
                "settled_at_utc": _utc_now(),
            }
            settled += 1
        if settled:
            document["updated_at_utc"] = _utc_now()
            _write(path, document)
        return settled
